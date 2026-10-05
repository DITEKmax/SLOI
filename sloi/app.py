from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from . import __version__
from .config import MODEL_CARDS, Config
from .domain import AppError
from .jobs import JobManager
from .media import probe
from .native import choose_files, reveal_file
from .store import Store
from .telemetry import Telemetry


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AddBody(StrictBody):
    source_ids: list[str] = Field(min_length=1, max_length=1000)
    model: str
    language: Literal["auto", "ru", "en"]
    audio_stream_index: int | None = Field(default=None, ge=0, strict=True)


class ChoiceBody(StrictBody):
    model: str
    language: Literal["auto", "ru", "en"]
    audio_stream_index: int | None = Field(default=None, ge=0, strict=True)


class OrderBody(StrictBody):
    ids: list[str] = Field(max_length=10000)


class PreferenceBody(StrictBody):
    theme: Literal["carbon", "paper", "signal"]
    accent: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    default_model: Literal["gigaam", "qwen", "whisper", "parakeet"] | None = None
    default_language: Literal["auto", "ru", "en"] | None = None


class DropItem(StrictBody):
    name: str = Field(max_length=1024)
    size: int = Field(ge=0)
    last_modified: int = Field(ge=0)


class DropBody(StrictBody):
    files: list[DropItem] = Field(min_length=1, max_length=1000)


class RelocateBody(StrictBody):
    source_id: str


def create_app(config: Config, manager: JobManager | None = None) -> FastAPI:
    store = manager.store if manager else Store(config.root / "data" / "state.db")
    telemetry = manager.telemetry if manager else Telemetry(config["telemetry"]["interval_seconds"], config["telemetry"]["history_seconds"], config["processing"]["gpu_index"])
    jobs = manager or JobManager(config, store, telemetry)
    cookie_name = "sloi_session"
    session_secret, csrf_secret = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    host = f"127.0.0.1:{config['server']['port']}"
    allowed_hosts = {host, f"localhost:{config['server']['port']}"}
    allowed_origins = {"http://" + value for value in allowed_hosts}
    root_id = __import__("hashlib").sha256(str(config.root).encode()).hexdigest()[:16]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        telemetry.start()
        jobs.start_service()
        yield
        await run_in_threadpool(jobs.close)
        telemetry.close()
        store.close()

    app = FastAPI(title="SLOI", version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.manager = jobs

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.headers.get("host") not in allowed_hosts or origin and origin not in allowed_origins or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"code": "FORBIDDEN_ORIGIN", "message": "Доступ разрешён только локальному интерфейсу SLOI."}, status_code=403)
        path = request.url.path
        if path.startswith("/api/") and path != "/api/session":
            if not secrets.compare_digest(request.cookies.get(cookie_name, ""), session_secret):
                return JSONResponse({"code": "SESSION_REQUIRED", "message": "Обновите страницу приложения."}, status_code=401)
            if request.method not in {"GET", "HEAD", "OPTIONS"} and not secrets.compare_digest(request.headers.get("x-sloi-csrf", ""), csrf_secret):
                return JSONResponse({"code": "CSRF_REQUIRED", "message": "Обновите страницу приложения."}, status_code=403)
        content_length = request.headers.get("content-length", "0")
        try:
            if int(content_length) < 0:
                return Response(status_code=400)
            if path != "/api/files/upload" and int(content_length) > 1024 * 1024:
                return JSONResponse({"code": "BODY_TOO_LARGE", "message": "Запрос слишком большой."}, status_code=413)
        except ValueError:
            return Response(status_code=400)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self' ws://127.0.0.1:* ws://localhost:*; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if path.startswith("/api/") or path == "/health":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(AppError)
    async def application_error(request: Request, exc: AppError):
        return JSONResponse({"code": exc.code, "message": exc.message}, status_code=exc.http_status)

    @app.get("/health")
    def health():
        return {"app": "sloi", "version": __version__, "root_id": root_id, "ready": True}

    @app.get("/api/session")
    def session():
        response = JSONResponse({"csrf": csrf_secret, "version": __version__})
        response.set_cookie(cookie_name, session_secret, httponly=True, samesite="strict", secure=False, path="/")
        return response

    def model_cards():
        return [{"id": key, **card, "installed": jobs.models.is_installed(key)} for key, card in MODEL_CARDS.items()]

    def state():
        preferences = {"theme": config["ui"]["default_theme"], "accent": config["ui"]["default_accent"], **store.preferences()}
        return {"version": __version__, "queue": jobs.snapshot(), "telemetry": telemetry.snapshot(), "models": model_cards(), "preferences": preferences, "defaults": {"model": preferences.get("default_model", config["ui"]["default_model"]), "language": preferences.get("default_language", config["ui"]["default_language"])}, "native_available": __import__("os").name == "nt", "upload_limits": jobs.uploads.limits}

    @app.get("/api/state")
    def get_state():
        return state()

    @app.post("/api/native/{mode}")
    async def native(mode: Literal["picker", "drop"]):
        paths = await run_in_threadpool(choose_files, mode)
        sources, errors = await run_in_threadpool(jobs.sources.register, paths) if paths else ([], [])
        return {"sources": sources, "errors": errors}

    @app.post("/api/files/drop")
    def browser_drop(body: DropBody):
        sources, missing = jobs.sources.match_drop([item.model_dump() for item in body.files])
        return {"sources": sources, "missing": missing}

    @app.post("/api/files/upload")
    async def browser_upload(request: Request, name: str, model: str, language: Literal["auto", "ru", "en"]):
        jobs._validate_choice(model, language)
        path = await jobs.uploads.receive(request, name)
        source: dict[str, Any] | None = None
        queued = False
        try:
            data = await run_in_threadpool(probe, path, config)
            data.update(name=name, source_upload=True)
            if await request.is_disconnected():
                raise AppError("UPLOAD_CANCELLED", "Загрузка отменена; временная копия удалена.", 499)
            # Queue and source registration share the scheduler lock. A crash
            # between SQLite commits is cleaned as an orphan at the next start.
            with jobs.lock:
                source = store.register_source(str(path), data)
                added = jobs.add([source["id"]], model, language)[0]
                queued = True
            return {"ok": True, "job_id": added["id"], "source_id": source["id"], "source": source}
        finally:
            if not queued:
                await run_in_threadpool(jobs.uploads.discard, path)
                if source:
                    await run_in_threadpool(store.remove_source, source["id"])

    @app.post("/api/jobs")
    def add_jobs(body: AddBody):
        added = jobs.add(body.source_ids, body.model, body.language, audio_stream_index=body.audio_stream_index)
        return {"ok": True, "job_ids": [job["id"] for job in added]}

    @app.put("/api/jobs/{job_id}")
    def change_job(job_id: str, body: ChoiceBody):
        jobs.update(job_id, body.model, body.language, audio_stream_index=body.audio_stream_index)
        return {"ok": True}

    @app.delete("/api/jobs/{job_id}")
    def remove_job(job_id: str):
        jobs.remove(job_id)
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/retry")
    def retry(job_id: str):
        retried = jobs.retry(job_id)
        return {"ok": True, "job_id": retried["id"]}

    @app.post("/api/jobs/{job_id}/relocate")
    def relocate(job_id: str, body: RelocateBody):
        jobs.relocate(job_id, body.source_id)
        return {"ok": True}

    @app.put("/api/queue/order")
    def reorder(body: OrderBody):
        jobs.reorder(body.ids)
        return {"ok": True}

    @app.post("/api/queue/{action}")
    def queue_action(action: Literal["start", "pause", "cancel"]):
        {"start": jobs.start_queue, "pause": jobs.pause_queue, "cancel": jobs.cancel_current}[action]()
        return {"ok": True}

    @app.put("/api/preferences")
    def preferences(body: PreferenceBody):
        values = body.model_dump(exclude_none=True)
        current = store.preferences()
        jobs._validate_choice(values.get("default_model", current.get("default_model", config["ui"]["default_model"])), values.get("default_language", current.get("default_language", config["ui"]["default_language"])))
        store.set_preferences(values)
        return {"ok": True}

    def result_path(job_id: str):
        job = store.job(job_id)
        return jobs.results.path(job)

    @app.get("/api/results/{job_id}/download")
    def download(job_id: str):
        path = result_path(job_id)
        return FileResponse(path, media_type="text/markdown; charset=utf-8", filename=path.name)

    @app.get("/api/results/{job_id}/text")
    def text(job_id: str):
        return {"text": jobs.results.text(store.job(job_id))}

    @app.post("/api/results/{job_id}/reveal")
    def reveal(job_id: str):
        reveal_file(result_path(job_id))
        return {"ok": True}

    @app.get("/api/results.zip")
    def download_all():
        completed = [job for job in store.jobs() if job.get("result_name") and job["status"] == "COMPLETE"]
        if not completed:
            raise AppError("NO_RESULTS", "Нет готовых результатов.", 404)
        path = jobs.results.archive(completed)
        return FileResponse(path, media_type="application/zip", filename="SLOI_transcripts.zip", background=BackgroundTask(path.unlink, missing_ok=True))

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        origin = ws.headers.get("origin")
        if ws.headers.get("host") not in allowed_hosts or origin not in allowed_origins or not secrets.compare_digest(ws.cookies.get(cookie_name, ""), session_secret):
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            while True:
                snapshot = await run_in_threadpool(state)
                await ws.send_json(snapshot)
                await asyncio.sleep(config["telemetry"]["interval_seconds"])
        except (WebSocketDisconnect, RuntimeError, OSError):
            return

    dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app
