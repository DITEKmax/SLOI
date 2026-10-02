from __future__ import annotations

import logging
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from .asr.manager import ModelManager
from .config import MODEL_CARDS, Config
from .domain import ACTIVE, LANGUAGES, RETRYABLE, AppError, Cancelled, InferenceOOM, Status, utc_now
from .media import SourceRegistry
from .pipeline import Pipeline
from .results import Results
from .store import Store
from .telemetry import Aggregate, Telemetry


logger = logging.getLogger("sloi.jobs")


class JobManager:
    def __init__(self, config: Config, store: Store, telemetry: Telemetry, models: Any | None = None, pipeline: Any | None = None):
        self.config, self.store, self.telemetry = config, store, telemetry
        self.models = models or ModelManager(config)
        self.results = Results(config.root)
        self.sources = SourceRegistry(config, store)
        self.pipeline = pipeline or Pipeline(config, self.models, self.results)
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.shutdown_event = threading.Event()
        self.cancel_event = threading.Event()
        self.running = False
        self.pause_after = False
        self.active_id: str | None = None
        self.live: dict[str, Any] = {}
        self.aggregate: Aggregate | None = None
        self.last_persist = 0.0
        self.sequence = 0
        self.store.recover()
        self._cleanup_orphans()
        telemetry.listener = self._sample

    def _cleanup_orphans(self) -> None:
        temporary = self.config.root / "runtime" / "temp"
        for path in temporary.iterdir():
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path)
        for path in (self.config.root / "data" / "results").rglob(".writing-*.tmp"):
            path.unlink(missing_ok=True)

    def _sample(self, sample: dict[str, Any]) -> None:
        with self.lock:
            aggregate = self.aggregate
        if aggregate:
            aggregate.add(sample)

    def start_service(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True, name="job-scheduler")
        self.thread.start()

    def _validate_choice(self, model: str, language: str) -> None:
        if model not in MODEL_CARDS or language not in LANGUAGES:
            raise AppError("INVALID_CHOICE", "Неизвестная модель или язык.")
        if model == "gigaam" and language == "en":
            raise AppError("LANGUAGE_UNSUPPORTED", "GigaAM v3 рассчитана на русский. Для EN выберите Qwen, Whisper или Parakeet.")

    def add(self, source_ids: list[str], model: str, language: str, benchmark: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self._validate_choice(model, language)
        if not 1 <= len(source_ids) <= 1000:
            raise AppError("QUEUE_LIMIT", "Добавьте от 1 до 1000 файлов за раз.")
        with self.lock:
            for source_id in source_ids:
                self.store.source(source_id)
            jobs = [self.store.create_job(source_id, model, language, benchmark) for source_id in source_ids]
            self.sequence += 1
            self.wake.set()
            return jobs

    def update(self, job_id: str, model: str, language: str) -> dict[str, Any]:
        self._validate_choice(model, language)
        with self.lock:
            job = self.store.job(job_id)
            if job["status"] != Status.WAITING:
                raise AppError("JOB_NOT_WAITING", "Модель и язык меняются только у ожидающей задачи.", 409)
            self.sequence += 1
            return self.store.update_job(job_id, model=model, language=language)

    def reorder(self, ids: list[str]) -> None:
        with self.lock:
            self.store.reorder_waiting(ids)
            self.sequence += 1

    def remove(self, job_id: str) -> None:
        with self.lock:
            self.store.remove_job(job_id)
            self.sequence += 1

    def retry(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.store.job(job_id)
            if job["status"] == Status.COMPLETE:
                return self.add([job["source_id"]], job["model"], job["language"])[0]
            if job["status"] not in RETRYABLE:
                raise AppError("CANNOT_RETRY", "Эту задачу нельзя перезапустить сейчас.", 409)
            source = self.store.source(job["source_id"], include_path=False)
            self.sequence += 1
            return self.store.update_job(job_id, status=Status.WAITING, error=None, progress=None, processed_seconds=0, elapsed_seconds=0, speed_x=None, eta_seconds=None, started_at=None, completed_at=None, warnings=[], speech_map=[], speech_regions=[], attempt=job["attempt"] + 1, source_mtime_ns=source["mtime_ns"], source_size=source["size"], source_fingerprint=source["fingerprint"])

    def relocate(self, job_id: str, source_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.store.job(job_id)
            if job["status"] not in RETRYABLE and job["status"] != Status.WAITING:
                raise AppError("JOB_ACTIVE", "Нельзя заменить исходник этой задачи.", 409)
            source = self.store.source(source_id, include_path=False)
            updated = self.store.update_job(job_id, source_id=source_id, name=source["name"], source_size=source["size"], size=source["size"], source_mtime_ns=source["mtime_ns"], source_fingerprint=source["fingerprint"], duration=source["duration"])
            with self.store.lock, self.store.db:
                self.store.db.execute("UPDATE jobs SET source_id=? WHERE id=?", (source_id, job_id))
            self.sequence += 1
            return updated

    def start_queue(self) -> None:
        with self.lock:
            self.running, self.pause_after = True, False
            self.sequence += 1
            self.wake.set()

    def pause_queue(self) -> None:
        with self.lock:
            if self.active_id:
                self.pause_after = True
            else:
                self.running = False
            self.sequence += 1

    def cancel_current(self) -> None:
        with self.lock:
            if not self.active_id:
                raise AppError("NO_ACTIVE_JOB", "Нет активной задачи.", 409)
            self.cancel_event.set()
            self.live["cancelling"] = True
            self.sequence += 1

    def _emit(self, **changes: Any) -> None:
        with self.lock:
            if not self.active_id:
                return
            old_status = self.live.get("status")
            self.live.update(changes)
            now = time.monotonic()
            if changes.get("status", old_status) != old_status or now - self.last_persist >= 1.5:
                self.store.update_job(self.active_id, **self.live)
                self.last_persist = now
            self.sequence += 1

    def _run(self) -> None:
        while not self.shutdown_event.is_set():
            job = None
            with self.lock:
                if self.running and not self.active_id:
                    waiting = [j for j in self.store.jobs() if j["status"] == Status.WAITING]
                    if waiting:
                        job = waiting[0]
                        self.active_id = job["id"]
                        self.cancel_event.clear()
                        self.aggregate = Aggregate()
                        self.aggregate.add(self.telemetry.snapshot(False))
                        job = self.store.update_job(job["id"], status=Status.PREPARING, started_at=utc_now(), error=None, cancelling=False)
                        self.live = dict(job)
                    else:
                        self.running = False
            if job:
                self._execute(job)
                continue
            if self.models.current_model and time.monotonic() - self.models.last_use > self.config["processing"]["idle_unload_seconds"]:
                self.models.stop()
            self.wake.wait(0.3)
            self.wake.clear()
        self.models.stop()

    def _execute(self, job: dict[str, Any]) -> None:
        logger.info("job_started id=%s model=%s", job["id"], job["model"])
        try:
            source = self.sources.validate_job_source(job)
            assert self.aggregate
            name, metadata = self.pipeline.run(job, source, self.cancel_event, self._emit, self.aggregate)
            with self.lock:
                self.store.update_job(job["id"], **{**self.live, "status": Status.COMPLETE, "completed_at": utc_now(), "result_name": name, "progress": 100.0, "error": None, "cancelling": False})
            logger.info("job_completed id=%s", job["id"])
        except Cancelled:
            self.models.stop()
            status = Status.INTERRUPTED if self.shutdown_event.is_set() else Status.CANCELLED
            with self.lock:
                self.store.update_job(job["id"], **{**self.live, "status": status, "eta_seconds": None, "cancelling": False, "completed_at": utc_now()})
            logger.info("job_cancelled id=%s", job["id"])
        except Exception as exc:
            self.models.stop()
            if isinstance(exc, AppError):
                code, message = exc.code, exc.message
            elif isinstance(exc, InferenceOOM):
                code, message = "GPU_OOM", "Не удалось выделить видеопамять. Освободите GPU и повторите задачу."
            else:
                code, message = "PROCESSING_ERROR", f"Ошибка обработки ({type(exc).__name__}). Проверьте diagnose.bat."
            status = Status.SOURCE_MISSING if code == "SOURCE_MISSING" else Status.FAILED
            with self.lock:
                self.store.update_job(job["id"], **{**self.live, "status": status, "error": {"code": code, "message": message[:1800]}, "eta_seconds": None, "completed_at": utc_now(), "cancelling": False})
            logger.error("job_failed id=%s code=%s exception=%s", job["id"], code, type(exc).__name__)
        finally:
            with self.lock:
                self.active_id, self.live, self.aggregate = None, {}, None
                if self.pause_after:
                    self.running, self.pause_after = False, False
                self.sequence += 1

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            jobs = self.store.jobs()
            if self.active_id:
                jobs = [{**j, **self.live} if j["id"] == self.active_id else j for j in jobs]
            for job in jobs:
                for private in ("source_mtime_ns", "source_size", "source_fingerprint"):
                    job.pop(private, None)
            return {"sequence": self.sequence, "running": self.running, "pause_after_current": self.pause_after, "active_id": self.active_id, "loaded_model": self.models.current_model, "jobs": jobs}

    def close(self) -> None:
        self.shutdown_event.set()
        self.cancel_event.set()
        self.wake.set()
        if hasattr(self, "thread"):
            self.thread.join(timeout=20)
        self.models.stop()
        self.telemetry.listener = None
