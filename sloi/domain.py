from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    WAITING = "WAITING"
    PREPARING = "PREPARING"
    LOADING_MODEL = "LOADING_MODEL"
    ANALYSING = "ANALYSING"
    TRANSCRIBING = "TRANSCRIBING"
    FINALIZING = "FINALIZING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"
    SOURCE_MISSING = "SOURCE_MISSING"


ACTIVE = frozenset({Status.PREPARING, Status.LOADING_MODEL, Status.ANALYSING, Status.TRANSCRIBING, Status.FINALIZING})
RETRYABLE = frozenset({Status.FAILED, Status.CANCELLED, Status.INTERRUPTED, Status.SOURCE_MISSING})
LANGUAGES = frozenset({"auto", "ru", "en"})
MEDIA_EXTENSIONS = frozenset({".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".aiff", ".aif", ".mka", ".mpga"})


class AppError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class Cancelled(Exception):
    pass


class InferenceOOM(Exception):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def finite(value: Any, default: float | None = None) -> float | None:
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError, OverflowError):
        return default


@dataclass(frozen=True)
class Region:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class Unit:
    index: int
    start: float
    end: float
    owned_start: float
    owned_end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def owned_duration(self) -> float:
        return max(0.0, self.owned_end - self.owned_start)


@dataclass
class Recognition:
    text: str
    language: str | None = None
    language_origin: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class Segment:
    start: float
    end: float
    text: str
    language: str | None = None
    language_origin: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def merge_regions(regions: list[Region], duration: float | None = None) -> list[Region]:
    out: list[Region] = []
    for region in sorted(regions, key=lambda r: (r.start, r.end)):
        start = max(0.0, region.start)
        end = min(region.end, duration) if duration is not None else region.end
        if end <= start:
            continue
        if out and start <= out[-1].end:
            out[-1] = Region(out[-1].start, max(out[-1].end, end))
        else:
            out.append(Region(start, end))
    return out


def make_plan(regions: list[Region], max_seconds: float, overlap_seconds: float = 0.35) -> list[Unit]:
    if max_seconds < 1 or not 0 <= overlap_seconds < max_seconds / 2:
        raise ValueError("Invalid segmentation limits")
    units: list[Unit] = []
    for region in merge_regions(regions):
        cursor = region.start
        while cursor < region.end - 1e-6:
            start = max(region.start, cursor - overlap_seconds) if cursor > region.start else cursor
            end = min(region.end, start + max_seconds)
            units.append(Unit(len(units), start, end, cursor, end))
            cursor = end
    return units


def merge_transcript(segments: list[Segment], min_overlap_words: int = 3) -> tuple[str, int]:
    pieces: list[str] = []
    removed = 0
    previous: Segment | None = None
    for segment in sorted(segments, key=lambda s: (s.start, s.end)):
        text = segment.text.strip()
        if not text:
            previous = segment
            continue
        if previous is not None and previous.end > segment.start + 0.01 and pieces:
            tail = pieces[-1].split()
            head = text.split()
            normalized_tail = [re.sub(r"[^\w]", "", t, flags=re.UNICODE).casefold() for t in tail]
            normalized_head = [re.sub(r"[^\w]", "", t, flags=re.UNICODE).casefold() for t in head]
            for count in range(min(len(tail), len(head), 12), min_overlap_words - 1, -1):
                if normalized_tail[-count:] == normalized_head[:count] and all(normalized_head[:count]):
                    text = " ".join(head[count:])
                    removed += count
                    break
        if text:
            pieces.append(text)
        previous = segment
    return " ".join(pieces), removed
