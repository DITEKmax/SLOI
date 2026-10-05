from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from sloi.app import create_app
from sloi.domain import AppError, Cancelled, Status
from sloi.jobs import JobManager
from sloi.media import probe
from sloi.telemetry import Aggregate, Telemetry
from sloi.uploads import UploadCache
from conftest import TestModels, make_wav


def stream_request(chunks: list[bytes], *, content_length: int | None = None, disconnect: bool = False, cancel: bool = False) -> Request:
    messages = [{"type": "http.request", "body": chunk, "more_body": True} for chunk in chunks]
    messages.append({"type": "http.disconnect"} if disconnect else {"type": "http.request", "body": b"", "more_body": False})
    headers = [(b"content-type", b"application/octet-stream")]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))

    async def receive():
        if cancel and not messages[:-1]:
            raise asyncio.CancelledError
        return messages.pop(0)

    return Request({"type": "http", "method": "POST", "path": "/api/files/upload", "headers": headers}, receive)


def uploaded_source(cache, config, store, audio):
    path = asyncio.run(cache.receive(stream_request([audio.read_bytes()]), audio.name))
    return store.register_source(str(path), {**probe(path, config), "name": audio.name, "source_upload": True})


def test_direct_upload_streams_large_body_and_queues(config, store, tmp_path):
    audio = make_wav(tmp_path / "Первая лекция.wav", 40)
    manager = JobManager(config, store, Telemetry(.5), TestModels())
    with TestClient(create_app(config, manager), base_url="http://127.0.0.1:8765") as client:
        token = client.get("/api/session").json()["csrf"]
        headers = {"X-Sloi-Csrf": token, "Content-Type": "application/octet-stream"}
        response = client.post("/api/files/upload", params={"name": audio.name, "model": "whisper", "language": "ru"}, content=audio.read_bytes(), headers=headers)
        assert response.status_code == 200, response.text
        job = store.job(response.json()["job_id"])
        source = store.source(job["source_id"])
        copy = Path(source["path"])
        assert job["name"] == audio.name and job["source_upload"] is True
        assert job["status"] == Status.WAITING and job["model"] == "whisper"
        assert copy != audio and copy.read_bytes() == audio.read_bytes()
        assert not list(copy.parent.glob("*.part"))
        assert "path" not in json.dumps(response.json())
        assert "path" not in json.dumps(client.get("/api/state").json())
        assert client.delete("/api/jobs/" + job["id"], headers=headers).status_code == 200
        assert not copy.exists() and audio.exists()


def test_upload_security_validation_and_invalid_media_cleanup(config, store, audio):
    manager = JobManager(config, store, Telemetry(.5), TestModels())
    with TestClient(create_app(config, manager), base_url="http://127.0.0.1:8765") as client:
        params = {"name": audio.name, "model": "whisper", "language": "ru"}
        assert client.post("/api/files/upload", params=params, content=b"media").status_code == 401
        token = client.get("/api/session").json()["csrf"]
        assert client.post("/api/files/upload", params=params, content=b"media").status_code == 403
        headers = {"X-Sloi-Csrf": token, "Content-Type": "application/octet-stream"}
        cases = [({"name": "bad.txt"}, "UNSUPPORTED_MEDIA"), ({"name": "../lecture.wav"}, "INVALID_FILENAME"), ({"model": "gigaam", "language": "en"}, "LANGUAGE_UNSUPPORTED"), ({"model": "unknown"}, "INVALID_CHOICE"), ({}, "INVALID_MEDIA")]
        for change, code in cases:
            response = client.post("/api/files/upload", params={**params, **change}, content=b"not media", headers=headers)
            assert response.json()["code"] == code
            assert not list(manager.uploads.root.iterdir())
        assert not store.jobs() and not store.sources()


def test_stream_size_limits_and_truncation_leave_no_copy(config, store):
    cache = UploadCache(config, store)
    cache.limits.update(max_file_bytes=5, cache_quota_bytes=100, min_free_bytes=0)
    cases = [(stream_request([b"sixsix"], content_length=6), "UPLOAD_TOO_LARGE"), (stream_request([b"abc", b"def"]), "UPLOAD_TOO_LARGE"), (stream_request([b"abc"], content_length=4), "UPLOAD_LENGTH"), (stream_request([], content_length=0), "UPLOAD_EMPTY")]
    for request, code in cases:
        with pytest.raises(AppError) as error:
            asyncio.run(cache.receive(request, "lecture.mp3"))
        assert error.value.code == code
        assert not list(cache.root.iterdir())


def test_disk_guard_and_cache_quota(config, store, monkeypatch):
    cache = UploadCache(config, store)
    cache.limits.update(max_file_bytes=10, cache_quota_bytes=10, min_free_bytes=1)
    first = asyncio.run(cache.receive(stream_request([b"12345678"]), "lecture.mp3"))
    with pytest.raises(AppError) as error:
        asyncio.run(cache.receive(stream_request([b"123"]), "next.mp3"))
    assert error.value.code == "UPLOAD_QUOTA"
    assert list(cache.root.iterdir()) == [first]
    monkeypatch.setattr("sloi.uploads.shutil.disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(AppError) as error:
        asyncio.run(cache.receive(stream_request([b"1"]), "next.mp3"))
    assert error.value.code == "UPLOAD_DISK_FULL"
    assert list(cache.root.iterdir()) == [first]


@pytest.mark.parametrize("kind", ["disconnect", "task_cancel"])
def test_abort_removes_partial_copy_and_unlocks_next_upload(config, store, kind):
    cache = UploadCache(config, store)
    request = stream_request([b"partial"], disconnect=kind == "disconnect", cancel=kind == "task_cancel")
    if kind == "disconnect":
        with pytest.raises(AppError) as error:
            asyncio.run(cache.receive(request, "lecture.mp3"))
        assert error.value.code == "UPLOAD_CANCELLED"
    else:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(cache.receive(request, "lecture.mp3"))
    assert not list(cache.root.iterdir())
    assert asyncio.run(cache.receive(stream_request([b"next"]), "next.mp3")).exists()


def test_success_releases_only_after_all_shared_jobs_complete(config, store, audio):
    cache = UploadCache(config, store)
    source = uploaded_source(cache, config, store, audio)
    path = Path(store.source(source["id"])["path"])
    first = store.create_job(source["id"], "whisper", "ru")
    second = store.create_job(source["id"], "qwen", "ru")
    store.update_job(first["id"], status=Status.COMPLETE)
    cache.release_if_unused(source["id"])
    assert path.exists()
    store.update_job(second["id"], status=Status.COMPLETE)
    cache.release_if_unused(source["id"])
    assert not path.exists() and store.job(first["id"])["status"] == Status.COMPLETE


@pytest.mark.parametrize("status", [Status.FAILED, Status.CANCELLED, Status.INTERRUPTED])
def test_retryable_upload_survives_restart_then_removal(config, store, audio, status):
    manager = JobManager(config, store, Telemetry(.5), TestModels())
    source = uploaded_source(manager.uploads, config, store, audio)
    job = manager.add([source["id"]], "whisper", "ru")[0]
    path = Path(store.source(source["id"])["path"])
    store.update_job(job["id"], status=status)
    restarted = JobManager(config, store, Telemetry(.5), TestModels())
    assert path.exists()
    assert restarted.retry(job["id"])["status"] == Status.WAITING
    restarted.remove(job["id"])
    assert not path.exists() and audio.exists()


def test_completion_hook_releases_upload_and_completed_retry_explains(config, store, audio):
    class Pipeline:
        def run(self, *args):
            return "result.md", {}

    manager = JobManager(config, store, Telemetry(.5), TestModels(), Pipeline())
    source = uploaded_source(manager.uploads, config, store, audio)
    job = manager.add([source["id"]], "whisper", "ru")[0]
    manager.aggregate = Aggregate()
    manager.live = dict(job)
    manager.active_id = job["id"]
    manager._execute(job)
    assert store.job(job["id"])["status"] == Status.COMPLETE
    assert not Path(store.source(source["id"])["path"]).exists()
    with pytest.raises(AppError) as error:
        manager.retry(job["id"])
    assert error.value.code == "UPLOAD_EXPIRED"


def test_restart_cleans_parts_orphans_and_preserves_original(config, store, audio):
    manager = JobManager(config, store, Telemetry(.5), TestModels())
    source = manager.sources.register([str(audio)])[0][0]
    job = manager.add([source["id"]], "whisper", "ru")[0]
    store.update_job(job["id"], status=Status.COMPLETE)
    cache = manager.uploads
    (cache.root / ("a" * 32 + ".mp3.part")).write_bytes(b"part")
    (cache.root / ("b" * 32 + ".mp3")).write_bytes(b"orphan")
    unrelated = cache.root / "keep-me.txt"
    unrelated.write_text("user file")
    cache.cleanup_orphans()
    cache.release_if_unused(source["id"])
    assert list(cache.root.iterdir()) == [unrelated] and audio.exists()


def test_upload_cleanup_refuses_forged_external_source(config, store, audio):
    cache = UploadCache(config, store)
    source = store.register_source(str(audio), {**probe(audio, config), "source_upload": True})
    cache.release_if_unused(source["id"])
    assert audio.exists()
