"""Real FFmpeg fixtures verify media fidelity independently of ASR models."""
from __future__ import annotations

import hashlib
import subprocess
import threading

import numpy as np
import pytest

from conftest import TestModels
from sloi.domain import AppError, utc_now
from sloi.media import PCMStream, SourceRegistry, probe
from sloi.pipeline import Pipeline
from sloi.results import Results
from sloi.telemetry import Aggregate


@pytest.fixture
def two_track_video(config, tmp_path):
    path = tmp_path / "Две дорожки.mkv"
    subprocess.run([
        config.executable("ffmpeg"), "-v", "error",
        "-f", "lavfi", "-i", "color=s=16x16:d=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2:sample_rate=44100",
        "-f", "lavfi", "-i", "sine=frequency=880:duration=2:sample_rate=48000",
        "-map", "0:v", "-map", "1:a", "-map", "2:a",
        "-c:v", "mpeg4", "-c:a", "pcm_s16le", "-ac:a:1", "2",
        "-metadata:s:a:0", "title=Лектор", "-metadata:s:a:0", "language=rus",
        "-metadata:s:a:1", "title=Translation", "-metadata:s:a:1", "language=eng",
        "-disposition:a:0", "0", "-disposition:a:1", "default", str(path),
    ], check=True, capture_output=True)
    return path


def reference_pcm(config, path, index):
    raw = subprocess.check_output([
        config.executable("ffmpeg"), "-v", "error", "-i", str(path),
        "-map", f"0:{index}", "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000",
        "-f", "f32le", "-c:a", "pcm_f32le", "pipe:1",
    ])
    return np.frombuffer(raw, dtype="<f4")


def dominant_frequency(wave):
    return np.fft.rfftfreq(len(wave), 1 / 16000)[np.argmax(abs(np.fft.rfft(wave)))]


def test_probe_reports_default_and_distinguishable_tracks(config, two_track_video):
    info = probe(two_track_video, config)
    assert info["media_type"] == "video"
    assert info["audio_stream_index"] == 2  # absolute stream index, after video
    assert info["audio_stream_count"] == 2
    assert [(t["index"], t["title"], t["language"], t["default"], t["channels"])
            for t in info["audio_tracks"]] == [
        (1, "Лектор", "rus", False, 1), (2, "Translation", "eng", True, 2),
    ]


@pytest.mark.parametrize("index,frequency", [(1, 440), (2, 880)])
def test_video_pcm_matches_reference_without_copying_or_modifying_source(config, two_track_video, index, frequency):
    before = hashlib.sha256(two_track_video.read_bytes()).hexdigest()
    with PCMStream(two_track_video, index, config, threading.Event(), block_samples=11003) as stream:
        actual = np.concatenate(list(stream))
    expected = reference_pcm(config, two_track_video, index)
    assert np.array_equal(actual, expected)
    assert len(actual) == 32000
    assert dominant_frequency(actual) == pytest.approx(frequency, abs=1)
    assert stream.samples_read == len(actual)
    assert hashlib.sha256(two_track_video.read_bytes()).hexdigest() == before
    assert not list((config.root / "runtime/temp").iterdir())


class CapturingModels(TestModels):
    def __init__(self):
        super().__init__()
        self.waves = []

    def recognize(self, waves, language, cancel):
        self.waves.extend(w.copy() for w in waves)
        return super().recognize(waves, language, cancel)


@pytest.mark.parametrize("index,frequency", [(1, 440), (2, 880)])
def test_pipeline_uses_chosen_track_for_both_passes_and_result_metadata(config, store, two_track_video, index, frequency):
    added, errors = SourceRegistry(config, store).register([str(two_track_video)])
    assert not errors
    source = store.source(added[0]["id"])
    job = store.create_job(source["id"], "whisper", "ru")
    job.update(audio_stream_index=index, started_at=utc_now())
    models = CapturingModels()
    _, metadata = Pipeline(config, models, Results(config.root)).run(
        job, source, threading.Event(), lambda **event: None, Aggregate(),
    )
    assert metadata["audio_stream_index"] == index
    assert metadata["audio_track"]["index"] == index
    assert metadata["source_duration_seconds"] == 2
    assert metadata["processing"]["source_channels"] == (1 if index == 1 else 2)
    assert len(models.waves) == 1
    assert np.array_equal(models.waves[0], reference_pcm(config, two_track_video, index))
    assert dominant_frequency(models.waves[0]) == pytest.approx(frequency, abs=1)
    assert any(f"дорожка {index}" in warning for warning in metadata["warnings"])


def test_pipeline_rejects_missing_track_before_model_load(config, store, two_track_video):
    source_id = SourceRegistry(config, store).register([str(two_track_video)])[0][0]["id"]
    job = store.create_job(source_id, "whisper", "ru")
    job.update(audio_stream_index=99, started_at=utc_now())
    models = CapturingModels()
    with pytest.raises(AppError) as failure:
        Pipeline(config, models, Results(config.root)).run(
            job, store.source(source_id), threading.Event(), lambda **event: None, Aggregate(),
        )
    assert failure.value.code == "AUDIO_TRACK_MISSING"
    assert models.loads == 0
