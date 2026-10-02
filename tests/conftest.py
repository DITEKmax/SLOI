from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sloi.config import Config
from sloi.domain import AppError, Cancelled, InferenceOOM, Recognition
from sloi.store import Store


class TestModels:
    __test__ = False
    def __init__(self, fail=False, oom_once=False, delay=0):
        self.current_model = None
        self.last_use = time.monotonic()
        self.loads = 0
        self.stops = 0
        self.calls = 0
        self.fail, self.oom_once, self.delay = fail, oom_once, delay

    def is_installed(self, model):
        return True

    def ensure(self, model, cancel):
        reused = self.current_model == model
        if not reused:
            self.loads += 1
        self.current_model = model
        self.last_use = time.monotonic()
        return {"runtime": "test-double-not-an-ASR", "model_revision": "test", "model_reused": reused, "language_hint_supported": True}

    def recognize(self, waves, language, cancel):
        self.calls += 1
        if self.delay:
            for _ in range(10):
                time.sleep(self.delay / 10)
                if cancel.is_set():
                    raise Cancelled
        if self.fail:
            raise AppError("TEST_FAILURE", "Intentional test failure")
        if self.oom_once and self.calls == 1:
            raise InferenceOOM("Intentional test OOM")
        return [Recognition("ТЕСТ КОНВЕЙЕРА. Это не результат распознавания речи.", "ru", "detected") for _ in waves]

    def stop(self):
        self.stops += 1
        self.current_model = None


def make_wav(path: Path, seconds: float = 5, silent=False) -> Path:
    samples = np.arange(round(seconds * 16000))
    values = np.zeros_like(samples) if silent else np.sin(samples / 16000 * 440 * 2 * np.pi) * 8000
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(values.astype("<i2").tobytes())
    return path


@pytest.fixture
def config(tmp_path):
    return Config(tmp_path / "project", {"vad": {"enabled": False}, "models": {name: {"max_chunk_seconds": 4} for name in ("gigaam", "qwen", "whisper", "parakeet")}})


@pytest.fixture
def store(config):
    result = Store(config.root / "data/state.db")
    yield result
    try:
        result.close()
    except Exception:
        pass


@pytest.fixture
def audio(tmp_path):
    return make_wav(tmp_path / "Лекция IELTS.wav", 10)
