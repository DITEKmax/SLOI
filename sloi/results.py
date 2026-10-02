from __future__ import annotations

import json
import os
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .config import MODEL_CARDS
from .domain import AppError


RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_stem(name: str, max_length: int = 80) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")[:max_length].rstrip(" .") or "recording"
    if name.split(".")[0].upper() in RESERVED:
        name = "_" + name
    return name


def filename(job: dict[str, Any]) -> str:
    stamp = datetime.fromisoformat(job["started_at"] or job["created_at"]).astimezone().strftime("%Y-%m-%d_%H%M%S")
    model = MODEL_CARDS[job["model"]]["short"]
    return f"{safe_stem(Path(job['name']).stem)}__{model}__{job['language'].upper()}__{stamp}.md"


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".writing-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))


class Results:
    def __init__(self, root: Path):
        self.root = root
        self.directory = root / "data" / "results"
        self.directory.mkdir(parents=True, exist_ok=True)

    def write(self, job: dict[str, Any], metadata: dict[str, Any], text: str) -> str:
        name = filename(job)
        folder = self.directory / job["id"]
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        number = 2
        while target.exists():
            target = folder / f"{Path(name).stem}__{number:02}.md"
            number += 1
        yaml_text = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False, width=110)
        atomic_text(target, f"---\n{yaml_text}---\n\n{text.strip()}\n")
        return target.name

    def path(self, job: dict[str, Any]) -> Path:
        name = job.get("result_name")
        if not name:
            raise AppError("RESULT_NOT_READY", "Результат ещё не готов.", 409)
        path = (self.directory / job["id"] / name).resolve()
        if not path.is_relative_to(self.directory.resolve()) or not path.is_file():
            raise AppError("RESULT_MISSING", "Файл результата отсутствует.", 404)
        return path

    def text(self, job: dict[str, Any]) -> str:
        content = self.path(job).read_text(encoding="utf-8")
        if content.startswith("---\n"):
            end = content.find("\n---\n", 4)
            if end >= 0:
                return content[end + 5:].strip()
        return content.strip()

    def archive(self, jobs: list[dict[str, Any]]) -> Path:
        temporary = self.root / "runtime" / "temp"
        temporary.mkdir(parents=True, exist_ok=True)
        fd, raw = tempfile.mkstemp(prefix="transcripts-", suffix=".zip", dir=temporary)
        os.close(fd)
        path = Path(raw)
        used: set[str] = set()
        try:
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for job in jobs:
                    source = self.path(job)
                    name = source.name
                    n = 2
                    while name.casefold() in used:
                        name = f"{source.stem}__{n:02}.md"
                        n += 1
                    used.add(name.casefold())
                    archive.write(source, name)
            return path
        except Exception:
            path.unlink(missing_ok=True)
            raise
