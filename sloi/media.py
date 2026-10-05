from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from .config import Config
from .domain import MEDIA_EXTENSIONS, AppError, Cancelled, Unit, finite
from .store import Store


def popen_flags() -> dict[str, Any]:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def terminate_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def _track_metadata(stream: dict[str, Any]) -> dict[str, Any]:
    tags = stream.get("tags", {})
    return {
        "index": stream["index"], "title": tags.get("title", ""),
        "language": tags.get("language", "und"),
        "default": bool(stream.get("disposition", {}).get("default")),
        "codec": stream.get("codec_name"), "channels": stream.get("channels"),
        "sample_rate": stream.get("sample_rate"), "duration": finite(stream.get("duration")),
        "start_time": finite(stream.get("start_time")),
    }


def probe(path: Path, config: Config) -> dict[str, Any]:
    if not path.is_file():
        raise AppError("SOURCE_MISSING", "Файл недоступен: возможно, он перемещён или отключён диск.")
    if path.suffix.lower() not in MEDIA_EXTENSIONS:
        raise AppError("UNSUPPORTED_MEDIA", "Этот формат не входит в список аудио и видео.")
    if str(path).startswith("\\\\") and not config["media"]["allow_network_paths"]:
        raise AppError("NETWORK_PATH", "Сетевые пути отключены. Выберите файл на локальном диске.")
    args = [config.executable("ffprobe"), "-v", "error", "-protocol_whitelist", "file,pipe", "-show_streams", "-show_format", "-of", "json", str(path)]
    try:
        run = subprocess.run(args, capture_output=True, timeout=30, **popen_flags())
    except subprocess.TimeoutExpired as exc:
        raise AppError("PROBE_TIMEOUT", "Не удалось прочитать свойства файла за 30 секунд.") from exc
    if run.returncode:
        raise AppError("INVALID_MEDIA", "FFprobe не смог прочитать файл. Проверьте, что запись не повреждена.")
    try:
        media = json.loads(run.stdout)
    except (ValueError, UnicodeError) as exc:
        raise AppError("INVALID_MEDIA", "Неверные метаданные контейнера.") from exc
    audio = [s for s in media.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio:
        raise AppError("NO_AUDIO", "В файле нет аудиодорожки.")
    selected = next((s for s in audio if s.get("disposition", {}).get("default") == 1), audio[0])
    duration = finite(selected.get("duration")) or finite(media.get("format", {}).get("duration"))
    if not duration or duration <= 0:
        raise AppError("UNKNOWN_DURATION", "Не удалось определить длительность аудио.")
    if duration > config["media"]["max_duration_hours"] * 3600:
        raise AppError("DURATION_LIMIT", "Запись превышает ограничение длительности в config/app.yaml.")
    stat = path.stat()
    return {
        "name": path.name, "duration": duration, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
        "media_type": "video" if any(s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic") for s in media["streams"]) else "audio",
        "audio_stream_index": selected["index"], "audio_stream_count": len(audio), "audio_codec": selected.get("codec_name"),
        "audio_tracks": [_track_metadata(s) for s in audio],
        "sample_rate": selected.get("sample_rate"), "channels": selected.get("channels"), "fingerprint": sampled_fingerprint(path),
    }


def sampled_fingerprint(path: Path) -> str:
    stat = path.stat()
    digest = hashlib.sha256(str(stat.st_size).encode("ascii"))
    with path.open("rb") as stream:
        digest.update(stream.read(1024 * 1024))
        if stat.st_size > 1024 * 1024:
            stream.seek(max(1024 * 1024, stat.st_size - 1024 * 1024))
            digest.update(stream.read(1024 * 1024))
    return digest.hexdigest()


def full_fingerprint(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class SourceRegistry:
    def __init__(self, config: Config, store: Store):
        self.config, self.store = config, store

    def register(self, paths: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        good, errors = [], []
        seen: set[str] = set()
        for raw in paths[:1000]:
            name = Path(raw).name
            try:
                path = Path(raw).resolve(strict=True)
                if str(path) in seen:
                    continue
                seen.add(str(path))
                data = probe(path, self.config)
                good.append(self.store.register_source(str(path), data))
            except (AppError, OSError) as exc:
                errors.append({"name": name, "message": exc.message if isinstance(exc, AppError) else "Не удалось открыть файл."})
        return good, errors

    def match_drop(self, descriptors: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        sources = self.store.sources()
        found, missing = [], []
        for item in descriptors:
            candidates = [s for s in sources if s["name"] == item["name"] and s["size"] == item["size"] and abs(s["mtime_ns"] / 1e6 - item["last_modified"]) < 2100 and Path(s["path"]).is_file()]
            if len(candidates) == 1:
                source = candidates[0]
                stat = Path(source["path"]).stat()
                if stat.st_size == source["size"] and stat.st_mtime_ns == source["mtime_ns"]:
                    found.append({k: v for k, v in source.items() if k != "path"})
                    continue
            missing.append(item["name"])
        return found, missing

    def validate_job_source(self, job: dict[str, Any]) -> dict[str, Any]:
        source = self.store.source(job["source_id"])
        path = Path(source["path"])
        try:
            stat = path.stat()
        except OSError as exc:
            raise AppError("SOURCE_MISSING", "Исходник недоступен. Найдите файл заново.") from exc
        if stat.st_size != job["source_size"] or stat.st_mtime_ns != job["source_mtime_ns"]:
            raise AppError("SOURCE_CHANGED", "Файл изменился после добавления. Добавьте актуальную версию заново.")
        return source


class PCMStream:
    def __init__(self, path: Path, stream_index: int, config: Config, cancel: threading.Event, block_samples: int = 16000):
        self.path, self.stream_index, self.config, self.cancel = path, stream_index, config, cancel
        self.block_samples = block_samples
        self.process: subprocess.Popen[bytes] | None = None
        self._stop = threading.Event()
        self._queue: queue.Queue[bytes | Exception | None] = queue.Queue(maxsize=3)
        self._stderr = bytearray()
        self.samples_read = 0

    def __enter__(self) -> PCMStream:
        args = [self.config.executable("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file,pipe", "-threads", "2", "-i", str(self.path), "-map", f"0:{self.stream_index}", "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-c:a", "pcm_f32le", "pipe:1"]
        self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **popen_flags())
        self.reader = threading.Thread(target=self._read, daemon=True, name="pcm-reader")
        self.errors_reader = threading.Thread(target=self._read_errors, daemon=True, name="ffmpeg-errors")
        self.reader.start()
        self.errors_reader.start()
        return self

    def _put(self, data: bytes | Exception | None) -> None:
        while not self._stop.is_set():
            try:
                self._queue.put(data, timeout=0.1)
                return
            except queue.Full:
                pass

    def _read(self) -> None:
        try:
            assert self.process and self.process.stdout
            size = self.block_samples * 4
            while not self._stop.is_set():
                data = self.process.stdout.read(size)
                if not data:
                    break
                self._put(data)
            self._put(None)
        except Exception as exc:
            self._put(exc)

    def _read_errors(self) -> None:
        assert self.process and self.process.stderr
        while chunk := self.process.stderr.read(1024):
            self._stderr.extend(chunk)
            if len(self._stderr) > 8192:
                del self._stderr[:-8192]

    def __iter__(self) -> Iterator[np.ndarray]:
        last = time.monotonic()
        remainder = b""
        while True:
            if self.cancel.is_set():
                raise Cancelled
            try:
                data = self._queue.get(timeout=0.15)
            except queue.Empty:
                if time.monotonic() - last > 60:
                    raise AppError("DECODE_TIMEOUT", "FFmpeg перестал передавать аудио.")
                continue
            last = time.monotonic()
            if isinstance(data, Exception):
                raise AppError("DECODE_FAILED", "Ошибка чтения аудиопотока.") from data
            if data is None:
                assert self.process
                if self.process.wait(timeout=5) != 0:
                    raise AppError("DECODE_FAILED", "FFmpeg завершился с ошибкой. Проверьте исходную запись.")
                if remainder:
                    raise AppError("DECODE_FAILED", "Неполный PCM-сэмпл.")
                return
            data = remainder + data
            usable = len(data) - len(data) % 4
            remainder = data[usable:]
            if usable:
                wave = np.frombuffer(data[:usable], dtype="<f4")
                if not np.isfinite(wave).all():
                    raise AppError("INVALID_AUDIO", "В аудиопотоке некорректные числовые значения.")
                self.samples_read += len(wave)
                yield wave

    def __exit__(self, *_: Any) -> None:
        self._stop.set()
        if self.process:
            terminate_process(self.process)
            self.reader.join(timeout=3)
            self.errors_reader.join(timeout=3)
            for pipe in (self.process.stdout, self.process.stderr):
                if pipe:
                    pipe.close()


def extract_units(stream: PCMStream, units: list[Unit]) -> Iterator[tuple[Unit, np.ndarray]]:
    iterator = iter(stream)
    buffer = np.empty(0, dtype=np.float32)
    offset = 0
    exhausted = False
    for unit_position, unit in enumerate(units):
        begin, end = round(unit.start * 16000), round(unit.end * 16000)
        while offset + len(buffer) < end and not exhausted:
            try:
                chunk = next(iterator)
            except StopIteration:
                exhausted = True
                break
            buffer = np.concatenate((buffer, chunk))
            discard = min(max(0, begin - offset), len(buffer))
            if discard:
                buffer = buffer[discard:]
                offset += discard
        if begin < offset:
            raise AppError("PIPELINE_ORDER", "Нарушен порядок сегментов.")
        if end > offset + len(buffer) + 2:
            raise AppError("AUDIO_TRUNCATED", "Аудио закончилось раньше построенной карты речи.")
        wave = buffer[begin - offset:min(end - offset, len(buffer))].copy()
        yield unit, wave
        keep_from = max(offset, min(end, round(units[unit_position + 1].start * 16000))) if unit_position + 1 < len(units) else end
        buffer = buffer[keep_from - offset:]
        offset = keep_from
