from __future__ import annotations

import copy
import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from .domain import AppError


MODEL_CARDS = {
    "gigaam": {"name": "GigaAM v3", "subtitle": "E2E RNN-T · русский", "short": "GIGAAM", "language_hint": False, "languages": ["ru"], "note": "Русскоязычная модель. Для английской записи выберите другую."},
    "qwen": {"name": "Qwen3 ASR", "subtitle": "0.6B · мультиязычная", "short": "QWEN3", "language_hint": True, "languages": ["ru", "en", "auto"], "note": "RU / EN задаёт язык декодирования. Смешанная речь требует проверки качества."},
    "whisper": {"name": "Whisper RU", "subtitle": "Large v3 Turbo · Stage AW", "short": "WHISPER", "language_hint": True, "languages": ["ru", "en", "auto"], "note": "Русский fine-tune. Английский поддерживается, но не равноценен исходному Turbo."},
    "parakeet": {"name": "Parakeet v3", "subtitle": "TDT 0.6B · мультиязычная", "short": "PARAKEET", "language_hint": False, "languages": ["ru", "en", "auto"], "note": "Определяет язык самостоятельно; RU / EN сохраняется как пожелание, но не передаётся модели."},
}


def deep_merge(base: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in user.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


class Config:
    def __init__(self, root: Path | str, overrides: dict[str, Any] | None = None):
        self.root = Path(root).resolve()
        base_path = self.root / "config" / "defaults.yaml"
        if not base_path.exists():
            base_path = Path(__file__).resolve().parent.parent / "config" / "defaults.yaml"
        base = yaml.safe_load(base_path.read_text(encoding="utf-8"))
        custom_path = self.root / "config" / "app.yaml"
        custom = yaml.safe_load(custom_path.read_text(encoding="utf-8")) or {} if custom_path.exists() else {}
        self.values = deep_merge(deep_merge(base, custom), overrides or {})
        self.validate()
        for name in ["data", "data/results", "data/backups", "data/reports", "logs", "runtime/temp"]:
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def validate(self) -> None:
        v = self.values
        if v["server"]["host"] != "127.0.0.1":
            raise ValueError("Only 127.0.0.1 is permitted")
        if not 1024 <= int(v["server"]["port"]) <= 65535:
            raise ValueError("Port must be in 1024..65535")
        if v.get("schema") != 1:
            raise ValueError("Unsupported configuration schema")
        if v["media"]["sample_rate"] != 16000:
            raise ValueError("This pipeline requires 16000 Hz")
        if not 0 <= v["vad"]["negative_threshold"] < v["vad"]["threshold"] <= 1:
            raise ValueError("Invalid VAD thresholds")
        if not 0.25 <= v["telemetry"]["interval_seconds"] <= 10:
            raise ValueError("Telemetry interval must be 0.25..10 seconds")
        for model in v["models"].values():
            if not 1 <= model["batch_size"] <= 16 or not 4 <= model["max_chunk_seconds"] <= 60:
                raise ValueError("Unsafe model batch/chunk configuration")
            if Path(model["path"]).is_absolute() or ".." in Path(model["path"]).parts:
                raise ValueError("Model paths must stay inside project")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", v["ui"]["default_accent"]):
            raise ValueError("Invalid accent")
        uploads = v["uploads"]
        if any(type(uploads[key]) is not int or uploads[key] < 0 for key in ("max_file_bytes", "cache_quota_bytes", "min_free_bytes")):
            raise ValueError("Upload limits must be non-negative byte counts")
        if not 1 <= uploads["max_file_bytes"] <= uploads["cache_quota_bytes"]:
            raise ValueError("Upload file limit must fit within cache quota")

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def executable(self, name: str) -> str:
        configured = self.values["media"].get(name, "auto")
        if configured != "auto":
            path = Path(configured)
            if not path.is_absolute():
                path = self.root / path
            if path.is_file():
                return str(path)
            raise AppError("MISSING_TOOL", f"Не найден {name}. Повторите install.bat.")
        suffix = ".exe" if os.name == "nt" else ""
        for path in (self.root / "runtime" / "ffmpeg" / f"{name}{suffix}", self.root / "runtime" / "ffmpeg" / "bin" / f"{name}{suffix}"):
            if path.is_file():
                return str(path)
        if found := shutil.which(name):
            return found
        raise AppError("MISSING_TOOL", f"Не найден {name}. Повторите install.bat.")

    def worker_python(self, environment: str) -> Path:
        relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
        return self.root / "runtime" / "envs" / environment / relative
