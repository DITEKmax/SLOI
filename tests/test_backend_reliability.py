"""Regressions for queue controls, source replacement and local file APIs."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import psutil
from fastapi.testclient import TestClient

from conftest import TestModels, make_wav
from sloi import native
from sloi.app import create_app
from sloi.domain import AppError, Status
from sloi.jobs import JobManager
from sloi.media import SourceRegistry
from sloi.results import Results
from sloi.telemetry import Telemetry


def manager_for(config, store):
    return JobManager(config, store, Telemetry(.5), TestModels())


def test_retry_clears_all_previous_attempt_display_values(config, store, audio):
    manager = manager_for(config, store)
    source = manager.sources.register([str(audio)])[0][0]
    job = manager.add([source['id']], 'whisper', 'ru')[0]
    store.update_job(job['id'], status=Status.CANCELLED, progress=91,
                     processed_seconds=9, planned_seconds=10, speech_seconds=8,
                     source_covered_seconds=9, analysis_seconds=10, elapsed_seconds=15,
                     eta_seconds=2, speed_x=.6, oom_retries=2, cancelling=True,
                     result_name='old.md', warnings=['old warning'], speech_map=[.7],
                     speech_regions=[[0, 8]])
    try:
        retried = manager.retry(job['id'])
        assert retried['status'] == 'WAITING' and retried['attempt'] == 2
        assert retried['progress'] is None and retried['planned_seconds'] is None
        assert retried['speech_seconds'] is None and retried['result_name'] is None
        assert all(retried[key] == 0 for key in ('processed_seconds', 'source_covered_seconds', 'analysis_seconds', 'elapsed_seconds', 'oom_retries'))
        assert retried['warnings'] == retried['speech_map'] == retried['speech_regions'] == []
        assert retried['speed_x'] is None and retried['eta_seconds'] is None
        assert retried['cancelling'] is False
    finally:
        manager.close()
        manager.telemetry.close()


def test_relocate_updates_foreign_key_and_source_properties_together(config, store, audio, tmp_path):
    manager = manager_for(config, store)
    original = manager.sources.register([str(audio)])[0][0]
    replacement_path = make_wav(tmp_path / 'Replacement.wav', 2)
    replacement = manager.sources.register([str(replacement_path)])[0][0]
    replacement = store.register_source(str(replacement_path), {**replacement, 'media_type': 'video', 'audio_stream_index': 3, 'audio_tracks': [{'index': 3, 'title': 'Лекция'}]})
    job = manager.add([original['id']], 'whisper', 'ru')[0]
    try:
        updated = manager.relocate(job['id'], replacement['id'])
        assert updated['source_id'] == replacement['id']
        assert updated['media_type'] == 'video' and updated['audio_stream_index'] == 3
        assert updated['audio_tracks'] == replacement['audio_tracks']
        assert store.db.execute('SELECT source_id FROM jobs WHERE id=?', (job['id'],)).fetchone()[0] == updated['source_id']
        assert manager.sources.validate_job_source(updated)['path'] == str(replacement_path)
    finally:
        manager.close()
        manager.telemetry.close()


def test_recover_stops_stale_cancellation_indicator(config, store, audio):
    source = SourceRegistry(config, store).register([str(audio)])[0][0]
    job = store.create_job(source['id'], 'whisper', 'ru')
    store.update_job(job['id'], status=Status.TRANSCRIBING, cancelling=True)
    assert store.recover() == 1
    interrupted = store.job(job['id'])
    assert interrupted['status'] == 'INTERRUPTED' and interrupted['cancelling'] is False
    assert interrupted['error']['code'] == 'INTERRUPTED'


def test_manual_audio_track_selection_validated_and_preserved(config, store, audio):
    manager = manager_for(config, store)
    source = manager.sources.register([str(audio)])[0][0]
    tracks = [{'index': 0, 'duration': 10}, {'index': 2, 'duration': 6}]
    store.register_source(str(audio), {**source, 'audio_tracks': tracks})
    try:
        job = manager.add([source['id']], 'whisper', 'ru', audio_stream_index=2)[0]
        assert job['audio_stream_index'] == 2 and job['duration'] == 6
        assert job['audio_tracks'] == tracks
        assert manager.update(job['id'], 'qwen', 'en')['audio_stream_index'] == 2
        assert manager.update(job['id'], 'qwen', 'en', audio_stream_index=0)['duration'] == 10
        with pytest.raises(AppError, match='отсутствует'):
            manager.update(job['id'], 'qwen', 'en', audio_stream_index=1)
        with pytest.raises(AppError):
            manager.add([source['id']], 'whisper', 'ru', audio_stream_index=1)
        assert len(store.jobs()) == 1
        store.update_job(job['id'], status=Status.COMPLETE)
        repeated = manager.retry(job['id'])
        assert repeated['id'] != job['id'] and repeated['audio_stream_index'] == 0
    finally:
        manager.close()
        manager.telemetry.close()


def test_api_persists_new_file_defaults_without_resetting_on_appearance_change(config, store, audio):
    manager = manager_for(config, store)
    source = manager.sources.register([str(audio)])[0][0]
    with TestClient(create_app(config, manager), base_url='http://127.0.0.1:8765') as client:
        csrf = client.get('/api/session').json()['csrf']
        headers = {'X-Sloi-Csrf': csrf}
        assert client.put('/api/preferences', json={'theme': 'paper', 'accent': '#224466', 'default_model': 'qwen', 'default_language': 'en'}, headers=headers).status_code == 200
        assert client.get('/api/state').json()['defaults'] == {'model': 'qwen', 'language': 'en'}
        assert client.put('/api/preferences', json={'theme': 'carbon', 'accent': '#c6f36b'}, headers=headers).status_code == 200
        assert client.get('/api/state').json()['defaults'] == {'model': 'qwen', 'language': 'en'}
        assert client.put('/api/preferences', json={'theme': 'paper', 'accent': '#224466', 'default_model': 'gigaam', 'default_language': 'en'}, headers=headers).status_code == 400
        assert client.get('/api/state').json()['defaults']['model'] == 'qwen'
        added = client.post('/api/jobs', json={'source_ids': [source['id']], 'model': 'whisper', 'language': 'ru', 'audio_stream_index': 0}, headers=headers)
        assert added.status_code == 200 and len(added.json()['job_ids']) == 1
        assert client.post('/api/jobs', json={'source_ids': [source['id']], 'model': 'whisper', 'language': 'ru', 'audio_stream_index': False}, headers=headers).status_code == 422


def test_native_picker_explicit_utf8_and_recoverable_invalid_reply(monkeypatch):
    monkeypatch.setattr(native, 'os', SimpleNamespace(name='nt', environ={}))
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(['C:\\Лекции\\Аудио.wav'], ensure_ascii=False))

    monkeypatch.setattr(native.subprocess, 'run', run)
    assert native.choose_files() == ['C:\\Лекции\\Аудио.wav']
    args, options = calls[0]
    assert args[1:3] == ['-X', 'utf8']
    assert options['env']['PYTHONIOENCODING'] == 'utf-8'
    assert options['cwd'] == Path(native.__file__).resolve().parents[1]
    monkeypatch.setattr(native.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='bad json'))
    with pytest.raises(AppError) as error:
        native.choose_files()
    assert error.value.code == 'NATIVE_DIALOG_FAILED'
    # A failed native response must release the dialog lock for the next attempt.
    monkeypatch.setattr(native.subprocess, 'run', run)
    assert native.choose_files()


def test_result_cannot_resolve_into_another_job_folder(config):
    results = Results(config.root)
    other = results.directory / 'other'
    other.mkdir()
    (other / 'secret.md').write_text('text', encoding='utf-8')
    with pytest.raises(AppError) as error:
        results.path({'id': 'this', 'result_name': '../other/secret.md'})
    assert error.value.code == 'RESULT_MISSING'


def test_remove_source_only_when_no_job_references_remain(config, store, audio):
    source = SourceRegistry(config, store).register([str(audio)])[0][0]
    job = store.create_job(source['id'], 'whisper', 'ru')
    store.remove_source(source['id'])
    assert store.source(source['id'])
    store.remove_job(job['id'])
    store.remove_source(source['id'])
    with pytest.raises(AppError) as error:
        store.source(source['id'])
    assert error.value.code == 'SOURCE_NOT_FOUND'


def test_unavailable_process_telemetry_is_null_and_does_not_block_app(monkeypatch):
    def inaccessible_process():
        raise psutil.AccessDenied(pid=123)

    monkeypatch.setattr(psutil, 'Process', inaccessible_process)
    telemetry = Telemetry(.5)
    try:
        sample = telemetry.snapshot()
        assert sample['process_tree_rss_mb'] is None
        assert sample['system_ram_total_mb'] > 0
        assert sample['cpu_utilization_pct'] is not None
    finally:
        telemetry.close()
