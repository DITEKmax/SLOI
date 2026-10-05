from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect, Request

from .config import Config
from .domain import MEDIA_EXTENSIONS, AppError, Status
from .store import Store


logger = logging.getLogger("sloi.uploads")
WRITE_CHUNK_BYTES = 1024 * 1024
DEFAULT_LIMITS = {
    "max_file_bytes": 20 * 1024 ** 3,
    "cache_quota_bytes": 40 * 1024 ** 3,
    "min_free_bytes": 512 * 1024 ** 2,
}


class UploadCache:
    """Disk-backed browser copies; native registered paths are never owned here."""

    def __init__(self, config: Config, store: Store):
        self.config, self.store = config, store
        self.root = config.root / "runtime" / "uploads"
        if self.root.is_symlink():
            raise AppError("UPLOAD_CACHE_UNSAFE", "Папка временных загрузок не должна быть ссылкой.")
        self.root.mkdir(parents=True, exist_ok=True)
        self.limits = {**DEFAULT_LIMITS, **config.values.get("uploads", {})}
        self._lock = threading.Lock()
        self._receiving = False
        extensions = "|".join(re.escape(ext[1:]) for ext in sorted(MEDIA_EXTENSIONS))
        self._owned_name = re.compile(rf"^[a-f0-9]{{32}}\.(?:{extensions})(?:\.part)?$")

    @staticmethod
    def validate_name(name: str) -> str:
        # Browser File.name is a basename. Do not accept server paths or controls.
        if not name or len(name) > 1024 or name in {".", ".."} or any(c in name for c in "/\\\x00") or any(ord(c) < 32 for c in name):
            raise AppError("INVALID_FILENAME", "У файла недопустимое имя.")
        suffix = Path(name).suffix.lower()
        if suffix not in MEDIA_EXTENSIONS:
            raise AppError("UNSUPPORTED_MEDIA", "Выберите аудио или видео поддерживаемого формата.", 415)
        return suffix

    def _owns(self, path: Path) -> bool:
        # No recursive deletes and no paths outside the dedicated cache.
        return path.parent == self.root and bool(self._owned_name.fullmatch(path.name))

    def usage(self) -> int:
        total = 0
        for path in self.root.iterdir():
            if self._owns(path) and not path.is_symlink() and path.is_file():
                total += path.stat().st_size
        return total

    def _space_for(self, incoming: int) -> int:
        cached = self.usage()
        if cached + incoming > self.limits["cache_quota_bytes"]:
            raise AppError("UPLOAD_QUOTA", "Временные загрузки заняли лимит диска. Удалите ненужные задачи или добавьте файл без копирования.", 413)
        self._check_free(incoming)
        return cached

    def _check_free(self, incoming: int) -> None:
        if shutil.disk_usage(self.root).free - incoming < self.limits["min_free_bytes"]:
            raise AppError("UPLOAD_DISK_FULL", "Недостаточно свободного места для временной копии. Освободите диск или добавьте файл без копирования.", 507)

    def _write(self, stream: BinaryIO, data: bytes) -> None:
        # disk_usage is a single filesystem call. Cache quota uses one initial
        # snapshot rather than scanning every queued file for each megabyte.
        self._check_free(len(data))
        stream.write(data)

    @staticmethod
    def _finish(stream: BinaryIO, partial: Path, target: Path) -> None:
        stream.flush()
        os.fsync(stream.fileno())
        stream.close()
        partial.replace(target)

    async def receive(self, request: Request, name: str) -> Path:
        suffix = self.validate_name(name)
        raw_length = request.headers.get("content-length")
        try:
            expected = int(raw_length) if raw_length is not None else None
        except ValueError as exc:
            raise AppError("UPLOAD_LENGTH", "Некорректный размер загрузки.") from exc
        if expected is not None and expected < 0:
            raise AppError("UPLOAD_LENGTH", "Некорректный размер загрузки.")
        if expected is not None and expected > self.limits["max_file_bytes"]:
            raise AppError("UPLOAD_TOO_LARGE", "Файл превышает лимит браузерной загрузки. Добавьте его без копирования или увеличьте uploads.max_file_bytes.", 413)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/octet-stream":
            raise AppError("UPLOAD_CONTENT_TYPE", "Передайте файл как двоичные данные.", 415)
        with self._lock:
            if self._receiving:
                raise AppError("UPLOAD_BUSY", "Другой файл ещё загружается. Дождитесь завершения и повторите.", 409)
            self._receiving = True
        target = self.root / (uuid.uuid4().hex + suffix)
        partial = target.with_name(target.name + ".part")
        stream: BinaryIO | None = None
        received = 0
        complete = False
        try:
            cached_bytes = await run_in_threadpool(self._space_for, expected or 0)
            stream = await run_in_threadpool(partial.open, "xb")
            async for chunk in request.stream():
                if not chunk:
                    continue
                received += len(chunk)
                if received > self.limits["max_file_bytes"]:
                    raise AppError("UPLOAD_TOO_LARGE", "Файл превышает лимит браузерной загрузки.", 413)
                if expected is not None and received > expected:
                    raise AppError("UPLOAD_LENGTH", "Размер загрузки не совпал с ожидаемым.")
                if cached_bytes + received > self.limits["cache_quota_bytes"]:
                    # A job may have freed its copy while this upload ran. Only
                    # rescan near the limit, accounting for bytes already saved.
                    await run_in_threadpool(stream.flush)
                    used = await run_in_threadpool(self._space_for, len(chunk))
                    cached_bytes = used - (received - len(chunk))
                for offset in range(0, len(chunk), WRITE_CHUNK_BYTES):
                    await run_in_threadpool(self._write, stream, chunk[offset:offset + WRITE_CHUNK_BYTES])
            if not received:
                raise AppError("UPLOAD_EMPTY", "Файл пустой. Выберите запись с аудио.")
            if expected is not None and received != expected:
                raise AppError("UPLOAD_LENGTH", "Файл загрузился не полностью. Повторите добавление.")
            await run_in_threadpool(self._finish, stream, partial, target)
            complete = True
            return target
        except ClientDisconnect as exc:
            raise AppError("UPLOAD_CANCELLED", "Загрузка прервана; временная копия удалена.", 499) from exc
        except OSError as exc:
            raise AppError("UPLOAD_WRITE_FAILED", "Не удалось сохранить временную копию. Проверьте свободное место и доступ к папке приложения.", 507) from exc
        finally:
            # Also runs when the browser aborts or the server task is cancelled.
            if stream and not stream.closed:
                stream.close()
            if not complete:
                self.discard(partial)
                self.discard(target)
            with self._lock:
                self._receiving = False

    def discard(self, path: Path) -> None:
        if self._owns(path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("upload_cleanup_failed file=%s", path.name)

    def release_if_unused(self, source_id: str) -> None:
        """Release after success/removal; failed and cancelled jobs keep retry data."""
        try:
            source = self.store.source(source_id)
            if not source.get("source_upload"):
                return
            path = Path(source["path"])
            if not self._owns(path):
                logger.warning("upload_cleanup_refused source=%s", source_id)
                return
            references = [j for j in self.store.jobs() if j["source_id"] == source_id]
            if any(j["status"] != Status.COMPLETE for j in references):
                return
            self.discard(path)
            if not references:
                self.store.remove_source(source_id)
        except (AppError, OSError):
            logger.warning("upload_cleanup_failed source=%s", source_id)

    def cleanup_orphans(self) -> None:
        """Run at startup; completed history stays, resumable copies survive."""
        try:
            sources = {Path(s["path"]): s for s in self.store.sources() if s.get("source_upload")}
            for path in self.root.iterdir():
                if not self._owns(path):
                    continue
                if path.name.endswith(".part") or path not in sources:
                    self.discard(path)
                else:
                    self.release_if_unused(sources[path]["id"])
        except OSError:
            logger.warning("upload_orphan_cleanup_failed")
