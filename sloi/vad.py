from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np

from .config import Config
from .domain import AppError, Region, merge_regions
from .media import PCMStream


class Detector(Protocol):
    def __call__(self, frame: np.ndarray) -> float: ...


class SileroDetector:
    def __init__(self, config: Config):
        path = config.root / config["vad"]["model"]
        if not path.is_file():
            raise AppError("VAD_NOT_INSTALLED", "Silero VAD не установлен. Запустите install.bat.")
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise AppError("VAD_RUNTIME_MISSING", "Не установлен ONNX Runtime для VAD.") from exc
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        self.session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
        inputs = {i.name for i in self.session.get_inputs()}
        if inputs != {"input", "state", "sr"}:
            raise AppError("VAD_INCOMPATIBLE", "Несовместимый файл Silero VAD: ожидается input/state/sr.")
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, 64), dtype=np.float32)
        self.sample_rate = np.array(16000, dtype=np.int64)

    def __call__(self, frame: np.ndarray) -> float:
        values = np.zeros((1, 512), dtype=np.float32)
        values[0, :len(frame)] = frame
        wave = np.concatenate((self.context, values), axis=1)
        result, self.state = self.session.run(None, {"input": wave, "state": self.state, "sr": self.sample_rate})
        self.context = values[:, -64:].copy()
        value = float(np.asarray(result).reshape(-1)[0])
        if not np.isfinite(value):
            raise AppError("VAD_INVALID", "VAD вернул некорректную вероятность речи.")
        return min(1.0, max(0.0, value))


@dataclass
class Analysis:
    duration: float
    speech_regions: list[Region]
    padded_regions: list[Region]
    speech_seconds: float
    speech_map: list[float]
    rms: float
    warnings: list[str]


def regions_from_probabilities(probabilities: list[float], duration: float, config: Config) -> list[Region]:
    settings = config["vad"]
    step = 512 / 16000
    min_speech = settings["min_speech_ms"] / 1000
    min_silence = settings["min_silence_ms"] / 1000
    start: float | None = None
    silence: float | None = None
    regions = []
    for index, probability in enumerate(probabilities):
        timestamp = index * step
        if probability >= settings["threshold"]:
            if start is None:
                start = timestamp
            silence = None
        elif probability < settings["negative_threshold"] and start is not None:
            if silence is None:
                silence = timestamp
            if timestamp + step - silence >= min_silence:
                if silence - start >= min_speech:
                    regions.append(Region(start, silence))
                start, silence = None, None
    if start is not None:
        end = silence if silence is not None and duration - silence >= min_silence else duration
        if end - start >= min_speech:
            regions.append(Region(start, end))
    return merge_regions(regions, duration)


def make_speech_map(regions: list[Region], duration: float, bins: int = 320) -> list[float]:
    if duration <= 0:
        return [0.0] * bins
    width = duration / bins
    values = np.zeros(bins, dtype=np.float64)
    for region in merge_regions(regions, duration):
        first = max(0, int(region.start / width))
        last = min(bins - 1, int(region.end / width))
        for i in range(first, last + 1):
            values[i] += max(0.0, min(region.end, (i + 1) * width) - max(region.start, i * width)) / width
    return np.clip(values, 0, 1).round(4).tolist()


def analyse(stream: PCMStream, config: Config, on_progress: Callable[[float], None], detector: Detector | None = None) -> Analysis:
    enabled = config["vad"]["enabled"]
    model = detector or (SileroDetector(config) if enabled else None)
    buffer = np.empty(0, dtype=np.float32)
    probabilities: list[float] = []
    samples = 0
    energy = 0.0
    last_event = 0.0
    for block in stream:
        samples += len(block)
        energy += float(np.dot(block.astype(np.float64), block.astype(np.float64)))
        buffer = np.concatenate((buffer, block))
        count = len(buffer) // 512
        for index in range(count):
            frame = buffer[index * 512:(index + 1) * 512]
            probabilities.append(model(frame) if model else 1.0)
        buffer = buffer[count * 512:]
        if time.monotonic() - last_event >= 0.35:
            on_progress(samples / 16000)
            last_event = time.monotonic()
    if len(buffer):
        probabilities.append(model(buffer) if model else 1.0)
    duration = samples / 16000
    on_progress(duration)
    if not samples:
        raise AppError("EMPTY_AUDIO", "FFmpeg вернул пустой аудиопоток.")
    rms = float(np.sqrt(energy / samples))
    regions = regions_from_probabilities(probabilities, duration, config) if enabled else [Region(0, duration)]
    warnings = []
    if not regions and rms > 1e-5 and config["vad"]["fallback_if_non_silent"]:
        regions = [Region(0, duration)]
        warnings.append("VAD_NO_SPEECH_NON_SILENT_FALLBACK: речь не найдена, но запись не тиха; распознаётся весь файл.")
    if not regions:
        warnings.append("NO_SPEECH_DETECTED: участки речи не обнаружены; ASR не вызывался.")
    padding = config["vad"]["padding_ms"] / 1000
    padded = merge_regions([Region(max(0, r.start - padding), min(duration, r.end + padding)) for r in regions], duration)
    return Analysis(duration, regions, padded, sum(r.duration for r in regions), make_speech_map(regions, duration), rms, warnings)
