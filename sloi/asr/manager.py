from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
from typing import Any

import numpy as np

from sloi.config import Config
from sloi.domain import AppError, Cancelled, InferenceOOM, Recognition
from sloi.media import popen_flags, terminate_process


class ModelManager:
    def __init__(self, config: Config):
        self.config = config
        self.process: subprocess.Popen[str] | None = None
        self.current_model: str | None = None
        self.responses: queue.Queue[dict[str, Any]] = queue.Queue()
        self.metadata: dict[str, Any] = {}
        self.last_use = time.monotonic()
        self.lock = threading.RLock()

    def environment_paths(self) -> dict[str, str]:
        active = self.config.root / "runtime" / "active.json"
        if active.is_file():
            return json.loads(active.read_text(encoding="utf-8")).get("environments", {})
        return {}

    def python_for(self, name: str) -> Path:
        raw = self.environment_paths().get(name)
        return (self.config.root / raw).resolve() if raw else self.config.worker_python(name)

    def is_installed(self, model_id: str) -> bool:
        spec = self.config["models"][model_id]
        path = self.config.root / spec["path"]
        stamp = self.config.root / "models" / model_id / ".sloi-model.json"
        return path.is_dir() and stamp.is_file() and self.python_for(spec["environment"]).is_file()

    def _read(self, process: subprocess.Popen[str], responses: queue.Queue[dict[str, Any]]) -> None:
        assert process.stdout
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                    if isinstance(message, dict):
                        responses.put(message)
                except ValueError:
                    continue
        finally:
            responses.put({"kind": "exited", "returncode": process.poll()})

    @staticmethod
    def _drain_errors(process: subprocess.Popen[str]) -> None:
        assert process.stderr
        for _ in process.stderr:
            pass

    def _receive(self, request_id: str | None, cancel: threading.Event, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancel.is_set():
                self.stop()
                raise Cancelled
            try:
                response = self.responses.get(timeout=0.15)
            except queue.Empty:
                if self.process is None or self.process.poll() is not None:
                    raise AppError("WORKER_EXITED", "Процесс модели завершился. Повторите задачу или запустите diagnose.bat.")
                continue
            if response.get("kind") == "exited":
                raise AppError("WORKER_EXITED", "Процесс модели аварийно завершился. Проверьте установку и доступную память.")
            if request_id is None and response.get("kind") == "ready":
                return response
            if response.get("id") == request_id:
                if not response.get("ok"):
                    if response.get("code") == "OOM":
                        raise InferenceOOM(response.get("message", "GPU out of memory"))
                    error = response.get("exception", "RuntimeError")
                    message = response.get("message", "")
                    raise AppError("ASR_ERROR", f"{error}: {message}")
                return response
        self.stop()
        raise AppError("MODEL_TIMEOUT", "Модель не ответила за отведённое время. Процесс остановлен.")

    def _request(self, command: str, payload: dict[str, Any], cancel: threading.Event) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        process = self.process
        if not process or not process.stdin:
            raise AppError("MODEL_NOT_LOADED", "Модель не загружена.")
        try:
            process.stdin.write(json.dumps({"id": request_id, "command": command, **payload}, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise AppError("WORKER_EXITED", "Потеряна связь с процессом модели.") from exc
        return self._receive(request_id, cancel, self.config["processing"]["worker_timeout_seconds"])

    def ensure(self, model_id: str, cancel: threading.Event) -> dict[str, Any]:
        with self.lock:
            if self.current_model == model_id and self.process and self.process.poll() is None:
                return {**self.metadata, "model_reused": True}
            self.stop()
            spec = dict(self.config["models"][model_id])
            executable = self.python_for(spec["environment"])
            if not self.is_installed(model_id):
                raise AppError("MODEL_NOT_INSTALLED", "Модель или окружение отсутствуют. Запустите install.bat; повторная установка докачает только недостающее.")
            spec["model_id"] = model_id
            spec["path"] = str((self.config.root / spec["path"]).resolve())
            spec["cpu_threads"] = self.config["processing"]["cpu_threads"]
            spec["gpu_index"] = self.config["processing"]["gpu_index"]
            transformer_python = self.python_for("transformers")
            cuda_directory = transformer_python.parent.parent / ("Lib/site-packages/torch/lib" if os.name == "nt" else f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages/torch/lib")
            spec["cuda_dll_directories"] = [str(cuda_directory)]
            env = os.environ.copy()
            env.update({"PYTHONPATH": str(Path(__file__).resolve().parents[2]), "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "SLOI_PARENT_PID": str(os.getpid()), "OMP_NUM_THREADS": str(spec["cpu_threads"]), "HF_HOME": str(self.config.root / "models" / ".cache")})
            self.responses = queue.Queue()
            self.process = subprocess.Popen([str(executable), "-m", "sloi.asr.worker"], cwd=self.config.root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", bufsize=1, env=env, **popen_flags())
            self.reader = threading.Thread(target=self._read, args=(self.process, self.responses), daemon=True)
            self.stderr_reader = threading.Thread(target=self._drain_errors, args=(self.process,), daemon=True)
            self.reader.start()
            self.stderr_reader.start()
            try:
                ready = self._receive(None, cancel, 45)
                response = self._request("load", {"spec": spec}, cancel)
                stamp = json.loads((self.config.root / "models" / model_id / ".sloi-model.json").read_text(encoding="utf-8"))
                self.current_model = model_id
                self.metadata = {**response["metadata"], "python": ready["python"], "model_repository": stamp.get("repository"), "model_revision": stamp.get("revision"), "model_reused": False}
                self.last_use = time.monotonic()
                return dict(self.metadata)
            except Exception:
                self.stop()
                raise

    def recognize(self, waves: list[np.ndarray], language: str, cancel: threading.Event) -> list[Recognition]:
        with self.lock:
            lengths = [len(w) for w in waves]
            size = sum(lengths)
            if not size:
                return [Recognition("") for _ in waves]
            memory = SharedMemory(create=True, size=size * 4)
            data = np.ndarray((size,), dtype=np.float32, buffer=memory.buf)
            slices, offset = [], 0
            try:
                for wave in waves:
                    data[offset:offset + len(wave)] = wave
                    slices.append([offset, len(wave)])
                    offset += len(wave)
                response = self._request("recognize", {"shared": {"name": memory.name, "samples": size, "slices": slices}, "language": language}, cancel)
                result = response["results"]
                if len(result) != len(waves):
                    raise AppError("RESULT_COUNT", "Модель вернула неверное число сегментов.")
                self.last_use = time.monotonic()
                return [Recognition(**r) for r in result]
            finally:
                del data
                memory.close()
                memory.unlink()

    def stop(self) -> None:
        with self.lock:
            if self.process:
                process, self.process = self.process, None
                terminate_process(process)
                for pipe in (process.stdin, process.stdout, process.stderr):
                    if pipe:
                        try:
                            pipe.close()
                        except OSError:
                            pass
            self.current_model = None
            self.metadata = {}
