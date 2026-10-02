from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import threading
import time
from dataclasses import asdict
from multiprocessing.shared_memory import SharedMemory
from typing import Any

import numpy as np

from sloi.asr.adapters import load_adapter


os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
    sys.stdout.flush()


def watch_parent(parent: int) -> None:
    try:
        import psutil
        original = psutil.Process(parent).create_time()
        while True:
            time.sleep(2)
            if not psutil.pid_exists(parent) or psutil.Process(parent).create_time() != original:
                os._exit(3)
    except Exception:
        os._exit(3)


def run() -> None:
    parent = int(os.environ.get("SLOI_PARENT_PID", os.getppid()))
    threading.Thread(target=watch_parent, args=(parent,), daemon=True).start()
    adapter = None
    emit({"kind": "ready", "pid": os.getpid(), "python": sys.version.split()[0]})
    for line in sys.stdin:
        request_id = None
        try:
            request = json.loads(line)
            request_id = request["id"]
            command = request["command"]
            if command == "quit":
                return
            if command == "load":
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    adapter = load_adapter(request["spec"])
                emit({"id": request_id, "ok": True, "metadata": adapter.metadata()})
            elif command == "recognize":
                if adapter is None:
                    raise RuntimeError("Model not loaded")
                shared = request["shared"]
                options = {"track": False} if sys.version_info >= (3, 13) else {}
                memory = SharedMemory(name=shared["name"], **options)
                waves = []
                data = None
                try:
                    data = np.ndarray((shared["samples"],), dtype=np.float32, buffer=memory.buf)
                    waves = [data[o:o + n] for o, n in shared["slices"]]
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        result = adapter.recognize(waves, request["language"])
                    encoded = [asdict(r) for r in result]
                finally:
                    waves = []
                    data = None
                    memory.close()
                emit({"id": request_id, "ok": True, "results": encoded})
            else:
                raise ValueError("Unknown worker command")
        except Exception as exc:
            message = str(exc)
            lowered = message.lower()
            oom = any(key in lowered for key in ("out of memory", "cuda_error_out_of_memory", "failed to allocate memory", "bad allocation", "memory allocation", "cublas_status_alloc_failed"))
            emit({"id": request_id, "ok": False, "code": "OOM" if oom else "ASR_ERROR", "exception": type(exc).__name__, "message": message[:1800]})


if __name__ == "__main__":
    run()
