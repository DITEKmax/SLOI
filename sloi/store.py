from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from .domain import ACTIVE, AppError, Status, utc_now


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS schema_info(version INTEGER NOT NULL);
        INSERT INTO schema_info(version) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_info);
        CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id), position INTEGER NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS jobs_status_position ON jobs(status,position);
        CREATE TABLE IF NOT EXISTS preferences(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        version = self.db.execute("SELECT version FROM schema_info").fetchone()[0]
        if version != 1:
            raise RuntimeError(f"Unsupported database version: {version}")
        self.db.commit()

    def close(self) -> None:
        with self.lock:
            self.db.close()

    def backup(self, target: Path) -> None:
        with self.lock, sqlite3.connect(target) as destination:
            self.db.backup(destination)

    def register_source(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock, self.db:
            row = self.db.execute("SELECT id FROM sources WHERE path=?", (path,)).fetchone()
            source_id = row[0] if row else uuid.uuid4().hex
            item = {**payload, "id": source_id}
            self.db.execute("INSERT INTO sources(id,path,payload) VALUES(?,?,?) ON CONFLICT(path) DO UPDATE SET payload=excluded.payload", (source_id, path, json.dumps(item, ensure_ascii=False)))
            return item

    def source(self, source_id: str, include_path: bool = True) -> dict[str, Any]:
        with self.lock:
            row = self.db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
            if not row:
                raise AppError("SOURCE_NOT_FOUND", "Исходник не найден в реестре.", 404)
            item = json.loads(row["payload"])
            if include_path:
                item["path"] = row["path"]
            return item

    def sources(self) -> list[dict[str, Any]]:
        with self.lock:
            return [{**json.loads(r["payload"]), "path": r["path"]} for r in self.db.execute("SELECT * FROM sources")]

    def create_job(self, source_id: str, model: str, language: str, benchmark: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.lock, self.db:
            source = self.source(source_id, include_path=False)
            position = self.db.execute("SELECT COALESCE(MAX(position),0)+1 FROM jobs").fetchone()[0]
            job_id = uuid.uuid4().hex
            payload = {
                "id": job_id, "source_id": source_id, "name": source["name"], "duration": source["duration"],
                "size": source["size"], "media_type": source["media_type"], "source_mtime_ns": source["mtime_ns"],
                "source_size": source["size"], "source_fingerprint": source["fingerprint"],
                "model": model, "language": language, "created_at": utc_now(), "started_at": None, "completed_at": None,
                "progress": None, "processed_seconds": 0.0, "planned_seconds": None, "speech_seconds": None,
                "source_covered_seconds": 0.0, "elapsed_seconds": 0.0, "speed_x": None, "eta_seconds": None,
                "analysis_seconds": 0.0, "speech_map": [], "speech_regions": [], "warnings": [],
                "error": None, "result_name": None, "attempt": 1, "benchmark": benchmark,
            }
            self.db.execute("INSERT INTO jobs VALUES(?,?,?,?,?)", (job_id, source_id, position, Status.WAITING, json.dumps(payload, ensure_ascii=False)))
            return {**payload, "position": position, "status": Status.WAITING}

    def jobs(self) -> list[dict[str, Any]]:
        with self.lock:
            return [self._job(r) for r in self.db.execute("SELECT * FROM jobs ORDER BY position")]

    @staticmethod
    def _job(row: sqlite3.Row) -> dict[str, Any]:
        return {**json.loads(row["payload"]), "position": row["position"], "status": row["status"]}

    def job(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise AppError("JOB_NOT_FOUND", "Задача не найдена.", 404)
            return self._job(row)

    def update_job(self, job_id: str, **changes: Any) -> dict[str, Any]:
        with self.lock, self.db:
            current = self.job(job_id)
            current.update(changes)
            status, position = current.pop("status"), current.pop("position")
            self.db.execute("UPDATE jobs SET status=?,position=?,payload=? WHERE id=?", (status, position, json.dumps(current, ensure_ascii=False, allow_nan=False), job_id))
            return {**current, "status": status, "position": position}

    def reorder_waiting(self, ids: list[str]) -> None:
        with self.lock, self.db:
            jobs = [j for j in self.jobs() if j["status"] == Status.WAITING]
            if len(ids) != len(set(ids)) or set(ids) != {j["id"] for j in jobs}:
                raise AppError("QUEUE_CHANGED", "Очередь изменилась. Обновите порядок и повторите.", 409)
            positions = sorted(j["position"] for j in jobs)
            self.db.executemany("UPDATE jobs SET position=? WHERE id=?", [(p, i) for p, i in zip(positions, ids)])

    def remove_job(self, job_id: str) -> None:
        with self.lock, self.db:
            job = self.job(job_id)
            if job["status"] in ACTIVE:
                raise AppError("JOB_ACTIVE", "Сначала отмените текущую обработку.", 409)
            self.db.execute("DELETE FROM jobs WHERE id=?", (job_id,))

    def recover(self) -> int:
        count = 0
        with self.lock:
            for job in self.jobs():
                if job["status"] in ACTIVE:
                    self.update_job(job["id"], status=Status.INTERRUPTED, error={"code": "INTERRUPTED", "message": "Обработка прервалась. Повторный запуск начнёт файл сначала."}, eta_seconds=None, speed_x=None)
                    count += 1
        return count

    def preferences(self) -> dict[str, Any]:
        with self.lock:
            return {r["key"]: json.loads(r["value"]) for r in self.db.execute("SELECT * FROM preferences")}

    def set_preferences(self, values: dict[str, Any]) -> None:
        with self.lock, self.db:
            self.db.executemany("INSERT INTO preferences(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", [(k, json.dumps(v, ensure_ascii=False)) for k, v in values.items()])
