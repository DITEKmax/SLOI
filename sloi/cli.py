from __future__ import annotations

import argparse
import hashlib
import json
import logging
import logging.handlers
import os
import platform
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from pathlib import Path
from typing import Any

import numpy as np

from . import __version__
from .asr.manager import ModelManager
from .config import Config, MODEL_CARDS
from .domain import AppError, Cancelled, Status, utc_now
from .instance import InstanceLock
from .media import PCMStream, SourceRegistry, full_fingerprint, popen_flags, probe
from .pipeline import Pipeline
from .results import Results, atomic_json, atomic_text
from .store import Store
from .telemetry import Aggregate, Telemetry
from .vad import SileroDetector


def setup_logging(config: Config):
    handler = logging.handlers.RotatingFileHandler(config.root / "logs" / "app.log", maxBytes=config["storage"]["log_max_bytes"], backupCount=config["storage"]["log_backup_count"], encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger = logging.getLogger("sloi")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)


def serve(config: Config, no_browser: bool):
    import uvicorn
    from .app import create_app
    host, port = config["server"]["host"], config["server"]["port"]
    url = f"http://{host}:{port}"
    root_id = hashlib.sha256(str(config.root).encode()).hexdigest()[:16]
    try:
        with urllib.request.urlopen(url + "/health", timeout=1) as response:
            health = json.load(response)
        if health.get("app") == "sloi" and health.get("root_id") == root_id:
            if not no_browser:
                webbrowser.open(url)
            print("SLOI already running:", url)
            return
        raise RuntimeError("Порт занят другой установкой. Закройте её или измените server.port в config/app.yaml.")
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        pass
    with InstanceLock(config.root):
        with socket.socket() as test:
            try:
                test.bind((host, port))
            except OSError as exc:
                raise RuntimeError("Порт занят. Не запущен ли другой backend?") from exc
        setup_logging(config)
        app = create_app(config)
        def ready_browser():
            for _ in range(80):
                time.sleep(.25)
                try:
                    with urllib.request.urlopen(url + "/health", timeout=.5) as response:
                        if json.load(response).get("root_id") == root_id:
                            webbrowser.open(url)
                            return
                except Exception:
                    pass
        if not no_browser:
            threading.Thread(target=ready_browser, daemon=True).start()
        print(f"SLOI {__version__}\n{url}\nKeep this window open while processing. Ctrl+C stops the backend.")
        uvicorn.run(app, host=host, port=port, access_log=False, log_level="warning", timeout_graceful_shutdown=25)


def make_smoke_sources(config: Config) -> dict[str, Path]:
    folder = config.root / "runtime" / "temp" / ("smoke-" + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    results = {}
    if os.name != "nt":
        return results
    script = Path(__file__).resolve().parents[1] / "scripts" / "make_smoke.ps1"
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-OutputDirectory", str(folder)], check=True, timeout=90, **popen_flags())
    for lang in ("ru", "en"):
        path = folder / (lang + ".wav")
        if path.is_file():
            results[lang] = path
    return results


def diagnose(config: Config, smoke: bool = False, source: Path | None = None) -> dict[str, Any]:
    manager = ModelManager(config)
    telemetry = Telemetry(config["telemetry"]["interval_seconds"])
    telemetry.start()
    report: dict[str, Any] = {"app_version": __version__, "created_at": utc_now(), "platform": platform.platform(), "python": sys.version, "telemetry": telemetry.snapshot(False), "models": {}, "checks": {}, "scope": "local_diagnostics_not_quality_benchmark"}
    for binary in ("ffmpeg", "ffprobe"):
        try:
            output = subprocess.run([config.executable(binary), "-version"], capture_output=True, text=True, check=True, timeout=15, **popen_flags())
            report["checks"][binary] = {"ok": True, "version": output.stdout.splitlines()[0]}
        except Exception as exc:
            report["checks"][binary] = {"ok": False, "error": str(exc)}
    try:
        vad = SileroDetector(config)
        value = vad(np.zeros(512, dtype=np.float32))
        report["checks"]["vad"] = {"ok": 0 <= value <= 1, "silence_probability": value}
    except Exception as exc:
        report["checks"]["vad"] = {"ok": False, "error": str(exc)}
    for model_id in MODEL_CARDS:
        report["models"][model_id] = {"installed": manager.is_installed(model_id), "inference": "not_run"}
    generated: dict[str, Path] = {}
    try:
        if smoke:
            if source:
                sources = {"auto": source.resolve(strict=True)}
            else:
                generated = make_smoke_sources(config)
                sources = generated
            if not sources:
                report["checks"]["smoke_audio"] = {"ok": False, "error": "No system speech voice available. Run diagnose.bat --smoke --source path-to-short-speech.wav"}
            for model_id in MODEL_CARDS:
                row = report["models"][model_id]
                if not row["installed"]:
                    continue
                try:
                    before = telemetry.sample().get("gpu_memory_used_mb")
                    started = time.monotonic()
                    metadata = manager.ensure(model_id, threading.Event())
                    row.update({"load_seconds": round(time.monotonic() - started, 3), "runtime": metadata, "samples": []})
                    for lang, path in sources.items():
                        if model_id == "gigaam" and lang == "en":
                            continue
                        media = probe(path, config)
                        arrays, total = [], 0
                        with PCMStream(path, media["audio_stream_index"], config, threading.Event()) as pcm:
                            for block in pcm:
                                arrays.append(block)
                                total += len(block)
                                if total >= 16000 * 8:
                                    break
                        audio = np.concatenate(arrays)[:16000 * 8]
                        result = manager.recognize([audio], lang, threading.Event())
                        text = result[0].text.strip()
                        row["samples"].append({"language_requested": lang, "nonempty": bool(text), "characters": len(text), "transcript_sha256": hashlib.sha256(text.encode()).hexdigest(), "telemetry": telemetry.sample()})
                    row["inference"] = "passed" if row["samples"] and all(s["nonempty"] for s in row["samples"]) else "incomplete"
                    row["vram_before_mb"] = before
                except Exception as exc:
                    row.update({"inference": "failed", "error_type": type(exc).__name__, "error": str(exc)[:3000]})
                finally:
                    manager.stop()
                    time.sleep(.6)
                    row["vram_after_process_exit_mb"] = telemetry.sample().get("gpu_memory_used_mb")
        report["all_four_gpu_smoke_passed"] = smoke and all(row["inference"] == "passed" for row in report["models"].values()) and all(check.get("ok") for check in report["checks"].values())
        report["ru_en_smoke_coverage"] = bool(smoke and not source and set(generated) == {"ru", "en"})
        report["long_lecture_test"] = "not_performed_by_smoke_test"
        atomic_json(config.root / "data" / "reports" / "diagnostics.json", report)
        lines = [f"SLOI {__version__}", report["created_at"], f"GPU: {report['telemetry'].get('gpu_name') or 'not detected'}", ""]
        for model_id,row in report["models"].items():
            lines.append(f"{model_id:10} installed={row['installed']} inference={row['inference']}")
            if row.get("error"):
                lines.append(row["error"])
        lines.extend(["", "Full report: data/reports/diagnostics.json", "No accuracy/WER conclusion can be made from a smoke test."])
        atomic_text(config.root / "data" / "reports" / "diagnostics.txt", "\n".join(lines))
        print("\n".join(lines))
        return report
    finally:
        manager.stop()
        telemetry.close()
        for path in generated.values():
            path.unlink(missing_ok=True)
        for folder in {p.parent for p in generated.values()}:
            try:
                folder.rmdir()
            except OSError:
                pass


def benchmark(config: Config, source: Path, language: str, models: list[str]) -> int:
    with InstanceLock(config.root):
        store = Store(config.root / "data" / "state.db")
        manager = ModelManager(config)
        telemetry = Telemetry(config["telemetry"]["interval_seconds"])
        telemetry.start()
        cancel = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: cancel.set())
        results = Results(config.root)
        pipeline = Pipeline(config, manager, results)
        sources, errors = SourceRegistry(config, store).register([str(source)])
        if errors:
            raise AppError("SOURCE_ERROR", errors[0]["message"])
        source_id = sources[0]["id"]
        full_sha = full_fingerprint(source)
        run_id = uuid.uuid4().hex
        rows = []
        try:
            for model_id in models:
                if cancel.is_set():
                    break
                if model_id == "gigaam" and language == "en":
                    rows.append({"model": model_id, "status": "skipped", "reason": "GigaAM is Russian-only"})
                    continue
                job = store.create_job(source_id, model_id, language, {"run_id": run_id, "source_sha256": full_sha, "source_id": source_id, "cold_model_load": True, "reference_transcript": False})
                job = store.update_job(job["id"], started_at=utc_now(), status=Status.PREPARING)
                aggregate = Aggregate()
                telemetry.listener = aggregate.add
                aggregate.add(telemetry.sample())
                last_log = 0.0
                def emit(**data):
                    nonlocal last_log
                    store.update_job(job["id"], **data)
                    if time.monotonic() - last_log > 3:
                        print(model_id, data.get("status", ""), data.get("progress", ""), flush=True)
                        last_log = time.monotonic()
                try:
                    name, metadata = pipeline.run(job, store.source(source_id), cancel, emit, aggregate)
                    store.update_job(job["id"], status=Status.COMPLETE, completed_at=utc_now(), result_name=name)
                    rows.append({"model": model_id, "status": "complete", "result": f"data/results/{job['id']}/{name}", "timing": metadata["timing"]})
                except Exception as exc:
                    status = Status.CANCELLED if isinstance(exc, Cancelled) else Status.FAILED
                    store.update_job(job["id"], status=status, error={"code": type(exc).__name__, "message": str(exc)[:2000]})
                    rows.append({"model": model_id, "status": str(status), "error": str(exc)[:2000]})
                finally:
                    manager.stop()
                    telemetry.listener = None
            atomic_json(config.root / "data" / "reports" / f"benchmark-{run_id}.json", {"run_id": run_id, "source_sha256": full_sha, "runs": rows})
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 0 if all(r["status"] in {"complete", "skipped"} for r in rows) else 1
        finally:
            manager.stop()
            telemetry.close()
            store.close()


def main():
    parser = argparse.ArgumentParser(prog="sloi")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest="command", required=True)
    server = commands.add_parser("serve");server.add_argument("--no-browser", action="store_true")
    doctor = commands.add_parser("diagnose");doctor.add_argument("--smoke", action="store_true");doctor.add_argument("--source", type=Path)
    bench = commands.add_parser("benchmark");bench.add_argument("source", type=Path);bench.add_argument("--language", choices=["ru", "en", "auto"], default="ru");bench.add_argument("--models", nargs="+", choices=list(MODEL_CARDS), default=list(MODEL_CARDS))
    args = parser.parse_args()
    config = Config(args.root)
    if args.command == "serve":
        serve(config, args.no_browser)
    elif args.command == "diagnose":
        if args.smoke:
            with InstanceLock(config.root):
                report = diagnose(config, True, args.source)
            return 0 if report["all_four_gpu_smoke_passed"] else 2
        diagnose(config)
    elif args.command == "benchmark":
        return benchmark(config, args.source, args.language, args.models)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AppError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
