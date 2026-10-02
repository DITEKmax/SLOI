from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any, Callable

import numpy as np

from . import PIPELINE_VERSION, __version__
from .config import MODEL_CARDS, Config
from .domain import AppError, Cancelled, InferenceOOM, Recognition, Segment, Status, Unit, make_plan, merge_transcript, utc_now
from .media import PCMStream, extract_units
from .results import Results, atomic_json
from .telemetry import Aggregate
from .vad import Detector, analyse


class LinkedStop:
    def __init__(self, external: threading.Event):
        self.external = external
        self.internal = threading.Event()

    def is_set(self) -> bool:
        return self.external.is_set() or self.internal.is_set()


class Pipeline:
    def __init__(self, config: Config, models: Any, results: Results, detector_factory: Callable[[], Detector] | None = None):
        self.config, self.models, self.results = config, models, results
        self.detector_factory = detector_factory

    def run(self, job: dict[str, Any], source: dict[str, Any], cancel: threading.Event, emit: Callable[..., None], aggregate: Aggregate) -> tuple[str, dict[str, Any]]:
        beginning = time.monotonic()
        spec = self.config["models"][job["model"]]
        source_path = Path(source["path"])
        warnings: list[str] = []
        if source.get("audio_stream_count", 1) > 1:
            warnings.append(f"MULTIPLE_AUDIO_STREAMS: выбрана дорожка {source['audio_stream_index']}; остальные не смешивались.")
        if not MODEL_CARDS[job["model"]]["language_hint"] and job["language"] != "auto":
            warnings.append("LANGUAGE_HINT_NOT_SUPPORTED: пожелание языка сохранено, но runtime не принимает языковую подсказку.")
        emit(status=Status.ANALYSING, progress=None)
        stage = time.monotonic()
        with PCMStream(source_path, source["audio_stream_index"], self.config, cancel) as stream:
            detector = self.detector_factory() if self.detector_factory else None
            analysis = analyse(stream, self.config, lambda seconds: emit(analysis_seconds=seconds, elapsed_seconds=time.monotonic() - beginning), detector)
        vad_seconds = time.monotonic() - stage
        warnings.extend(analysis.warnings)
        units = make_plan(analysis.padded_regions, float(spec["max_chunk_seconds"]), self.config["processing"]["overlap_seconds"])
        planned = sum(u.owned_duration for u in units)
        emit(duration=analysis.duration, speech_seconds=analysis.speech_seconds, planned_seconds=planned, speech_map=analysis.speech_map, speech_regions=[[r.start, r.end] for r in analysis.speech_regions[:5000]], warnings=warnings[:], progress=0.0 if units else None)
        if cancel.is_set():
            raise Cancelled
        model_metadata: dict[str, Any] = {"runtime": spec["runtime"], "compute_type": spec["compute_type"], "model_reused": False, "model_invoked": False}
        loading_seconds = 0.0
        inference_seconds = 0.0
        asr_seconds = 0.0
        processed = 0.0
        committed = 0
        retries = 0
        segments: list[Segment] = []
        effective_batches: set[int] = set()
        retry_events: list[dict[str, Any]] = []
        request_durations: deque[tuple[float, float]] = deque(maxlen=12)
        if units:
            emit(status=Status.LOADING_MODEL)
            stage = time.monotonic()
            try:
                model_metadata = {**self.models.ensure(job["model"], cancel), "model_invoked": True}
            except InferenceOOM as exc:
                raise AppError("MODEL_LOAD_OOM", "Недостаточно VRAM для загрузки весов. Закройте другие GPU-приложения. Сокращение сегментов здесь не поможет.") from exc
            loading_seconds = time.monotonic() - stage
            if source_path.stat().st_mtime_ns != job["source_mtime_ns"] or source_path.stat().st_size != job["source_size"]:
                raise AppError("SOURCE_CHANGED", "Запись изменилась во время анализа.")
            emit(status=Status.TRANSCRIBING, progress=0.0)
            stage = time.monotonic()
            stop = LinkedStop(cancel)
            prepared: queue.Queue[Any] = queue.Queue(maxsize=self.config["processing"]["prefetch_batches"])
            batch_size = 1 if spec["runtime"] == "faster-whisper" else int(spec["batch_size"])

            def offer(item: Any) -> None:
                while not stop.is_set():
                    try:
                        prepared.put(item, timeout=0.1)
                        return
                    except queue.Full:
                        pass

            def prepare() -> None:
                try:
                    with PCMStream(source_path, source["audio_stream_index"], self.config, stop) as pcm:
                        batch: list[tuple[Unit, np.ndarray]] = []
                        for pair in extract_units(pcm, units):
                            if stop.is_set():
                                return
                            batch.append(pair)
                            if len(batch) >= batch_size:
                                offer(batch)
                                batch = []
                        if batch:
                            offer(batch)
                    offer(None)
                except Exception as exc:
                    offer(exc)

            producer = threading.Thread(target=prepare, daemon=True, name="audio-prefetch")
            producer.start()

            def recognize(batch: list[tuple[Unit, np.ndarray]]) -> None:
                nonlocal retries, inference_seconds, processed, committed
                if cancel.is_set():
                    raise Cancelled
                request_start = time.monotonic()
                try:
                    output: list[Recognition] = self.models.recognize([w for _, w in batch], job["language"], cancel)
                except InferenceOOM:
                    inference_seconds += time.monotonic() - request_start
                    retries += 1
                    if retries > self.config["processing"]["max_oom_retries"]:
                        raise AppError("GPU_OOM", "Исчерпан лимит повторов после нехватки видеопамяти.")
                    self.models.stop()
                    self.models.ensure(job["model"], cancel)
                    retry_events.append({"attempt": retries, "batch": len(batch), "chunk_seconds": round(batch[0][0].duration, 3)})
                    emit(warnings=[*warnings, f"OOM_RECOVERY: повтор {retries}, уменьшаем пакет или длину сегмента."], oom_retries=retries)
                    if len(batch) > 1:
                        split = len(batch) // 2
                        recognize(batch[:split])
                        recognize(batch[split:])
                    else:
                        unit, wave = batch[0]
                        if unit.duration < 2 * self.config["processing"]["min_oom_chunk_seconds"]:
                            raise AppError("GPU_OOM", "Модель не помещается даже с коротким сегментом. Освободите VRAM или выберите другую модель.")
                        middle_sample = len(wave) // 2
                        middle = unit.start + middle_sample / 16000
                        first = Unit(unit.index, unit.start, middle, unit.owned_start, middle)
                        second = Unit(unit.index, middle, unit.end, middle, unit.owned_end)
                        recognize([(first, wave[:middle_sample])])
                        recognize([(second, wave[middle_sample:])])
                    return
                duration = time.monotonic() - request_start
                inference_seconds += duration
                if len(output) != len(batch):
                    raise AppError("RESULT_COUNT", "Число результатов не совпало с числом сегментов.")
                effective_batches.add(len(batch))
                owned = sum(u.owned_duration for u, _ in batch)
                request_durations.append((owned, duration))
                for (unit, _), item in zip(batch, output):
                    segments.append(Segment(unit.start, unit.end, item.text, item.language, item.language_origin))
                    warnings.extend(w for w in item.warnings if w not in warnings)
                    processed += unit.owned_duration
                    committed += 1
                elapsed = time.monotonic() - beginning
                covered = min(analysis.duration, max(u.owned_end for u, _ in batch))
                recent_seconds = sum(t for _, t in request_durations)
                recent_audio = sum(a for a, _ in request_durations)
                rate = recent_audio / recent_seconds if recent_seconds > 0 else None
                eta = (planned - processed) / rate if rate and committed >= 2 else None
                emit(progress=min(100.0, processed / planned * 100), processed_seconds=processed, source_covered_seconds=covered, elapsed_seconds=elapsed, speed_x=covered / elapsed if elapsed else None, eta_seconds=max(0.0, eta) if eta is not None else None, warnings=warnings[:], oom_retries=retries)

            try:
                while True:
                    if cancel.is_set():
                        raise Cancelled
                    try:
                        batch = prepared.get(timeout=0.15)
                    except queue.Empty:
                        if not producer.is_alive():
                            raise AppError("PIPELINE_STOPPED", "Конвейер чтения аудио остановился.")
                        continue
                    if batch is None:
                        break
                    if isinstance(batch, Exception):
                        raise batch
                    recognize(batch)
            finally:
                stop.internal.set()
                producer.join(timeout=8)
                if producer.is_alive():
                    raise AppError("DECODER_STOP_TIMEOUT", "Не удалось корректно остановить декодер.")
            asr_seconds = time.monotonic() - stage
        if cancel.is_set():
            raise Cancelled
        final_stat = source_path.stat()
        if final_stat.st_size != job["source_size"] or final_stat.st_mtime_ns != job["source_mtime_ns"]:
            raise AppError("SOURCE_CHANGED", "Исходная запись была изменена во время обработки. Результат не сохранён как готовый.")
        emit(status=Status.FINALIZING, eta_seconds=None)
        text, deduplicated = merge_transcript(segments)
        if planned and not text:
            warnings.append("EMPTY_TRANSCRIPT: участки речи были найдены, но ASR не вернул текст.")
        if retries:
            warnings.append(f"OOM_RECOVERED: автоматических повторов после нехватки памяти: {retries}.")
        detected = Counter(s.language for s in segments if s.language_origin == "detected" and s.language)
        pipeline_config = {"vad": self.config["vad"], "model": {k: v for k, v in spec.items() if k != "path"}, "overlap_seconds": self.config["processing"]["overlap_seconds"]}
        total = time.monotonic() - beginning
        metadata: dict[str, Any] = {
            "app_version": __version__, "pipeline_version": PIPELINE_VERSION, "job_id": job["id"],
            "source_file": job["name"], "source_type": source["media_type"], "source_duration_seconds": round(analysis.duration, 3),
            "source_fingerprint": job["source_fingerprint"], "source_fingerprint_kind": "sha256_size_head_tail_1MiB", "source_size_bytes": job["source_size"],
            "audio_stream_index": source["audio_stream_index"], "detected_speech_seconds": round(analysis.speech_seconds, 3), "planned_audio_seconds": round(planned, 3),
            "language_requested": job["language"], "language_hint_applied": bool(model_metadata.get("language_hint_supported") and job["language"] != "auto"),
            "detected_languages": dict(detected) if detected else None,
            "model": job["model"], **model_metadata,
            "started_at": job["started_at"], "completed_at": utc_now(),
            "timing": {"total_processing_seconds": round(total, 3), "vad_seconds": round(vad_seconds, 3), "model_load_seconds": round(loading_seconds, 3), "asr_stage_seconds": round(asr_seconds, 3), "inference_calls_seconds": round(inference_seconds, 3), "end_to_end_speed_x": round(analysis.duration / total, 3) if total > 0 else None, "asr_stage_speed_x": round(analysis.duration / asr_seconds, 3) if asr_seconds > 0 else None, "definition": "speed_x = source_seconds / elapsed_seconds; ASR stage includes second-pass decode and IPC; total excludes queue wait and final file write"},
            "telemetry": {"sampling_interval_seconds": self.config["telemetry"]["interval_seconds"], "memory_scope": "GPU/device-wide; RAM/system-wide; process_tree_rss may count shared pages more than once", **aggregate.summary()},
            "processing": {"sample_rate": 16000, "channels": 1, "audio_speed": 1.0, "vad": "silero-onnx-cpu" if self.config["vad"]["enabled"] else "disabled", "vad_settings": self.config["vad"], "requested_batch_size": spec["batch_size"], "observed_batch_sizes": sorted(effective_batches), "max_chunk_seconds": spec["max_chunk_seconds"], "overlap_seconds": self.config["processing"]["overlap_seconds"], "oom_retries": retries, "oom_events": retry_events, "overlap_words_removed": deduplicated, "configuration_sha256": hashlib.sha256(json.dumps(pipeline_config, sort_keys=True).encode()).hexdigest()},
            "warnings": warnings,
            "quality_metrics": {"wer": None, "cer": None, "ground_truth_available": False, "note": "Точность, пропуски и галлюцинации не вычисляются без эталона и проверки аудио."},
        }
        if job.get("benchmark"):
            metadata["benchmark"] = job["benchmark"]
        name = self.results.write(job, metadata, text)
        if self.config["storage"]["keep_debug_segments"]:
            atomic_json(self.config.root / "data" / "reports" / f"{job['id']}.segments.json", {"segments": [s.to_dict() for s in segments]})
        emit(elapsed_seconds=total, speed_x=analysis.duration / total if total else None, progress=100.0, processed_seconds=planned, source_covered_seconds=analysis.duration, warnings=warnings, eta_seconds=0)
        return name, metadata
