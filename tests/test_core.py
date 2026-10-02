import hashlib
import json
import math
import sqlite3
import subprocess
import threading
import time
import zipfile
from pathlib import Path

import numpy as np
import pytest
import yaml
from fastapi.testclient import TestClient

from sloi.app import create_app
from sloi.config import Config
from sloi.domain import ACTIVE, AppError, Cancelled, Region, Segment, Status, make_plan, merge_regions, merge_transcript, utc_now
from sloi.jobs import JobManager
from sloi.media import PCMStream, SourceRegistry, extract_units, probe
from sloi.pipeline import Pipeline
from sloi.results import Results, atomic_text, filename, safe_stem
from sloi.store import Store
from sloi.telemetry import Aggregate, Telemetry
from sloi.vad import analyse, make_speech_map, regions_from_probabilities
from conftest import TestModels, make_wav


@pytest.mark.parametrize("duration,max_s,overlap", [(90,22,.35),(5400,28,.35),(3,4,0),(500,12,.9),(50,10,3)])
def test_plan_unique_coverage(duration,max_s,overlap):
    units=make_plan([Region(0,duration)],max_s,overlap)
    assert sum(u.owned_duration for u in units)==pytest.approx(duration)
    assert all(0 < u.duration <= max_s + 1e-8 for u in units)
    assert all(a.owned_end==b.owned_start for a,b in zip(units,units[1:]))


def test_plan_silence_gaps():
    regions=merge_regions([Region(-2,3),Region(2,5),Region(8,20)],10)
    assert regions==[Region(0,5),Region(8,10)]
    assert sum(u.owned_duration for u in make_plan(regions,4))==7


@pytest.mark.parametrize("name",['CON','a: b? / x','Лекция API','...','NUL.txt','a'*200])
def test_safe_windows_name(name):
    clean=safe_stem(name)
    assert not any(c in clean for c in '<>:"/\\|?*')
    assert len(clean)<=81 and clean.strip(' .')==clean
    assert clean.split('.')[0].upper() not in {'CON','NUL'}


def test_merge_only_overlaps():
    segments=[Segment(0,10,'Мы изучаем pandas data frame'),Segment(9.6,19,'pandas data frame и merge.'),Segment(20,22,'и merge.')]
    text,removed=merge_transcript(segments)
    assert text=='Мы изучаем pandas data frame и merge. и merge.'
    assert removed==3


def test_no_loose_rewriting():
    text,n=merge_transcript([Segment(0,2,'ээ ну, сегодня'),Segment(2,4,'ээ ну, сегодня')])
    assert text=='ээ ну, сегодня ээ ну, сегодня' and n==0


def test_source_and_ffmpeg_zero_copy(config,store,audio):
    before=hashlib.sha256(audio.read_bytes()).hexdigest()
    registry=SourceRegistry(config,store)
    sources,errors=registry.register([str(audio)])
    assert not errors and len(sources)==1
    data=store.source(sources[0]['id'])
    assert 'path' not in sources[0]
    with PCMStream(audio,data['audio_stream_index'],config,threading.Event()) as stream:
        blocks=list(stream)
    assert sum(map(len,blocks))==160000
    assert hashlib.sha256(audio.read_bytes()).hexdigest()==before
    assert list((config.root/'runtime/temp').iterdir())==[]
    desc={'name':audio.name,'size':audio.stat().st_size,'last_modified':audio.stat().st_mtime_ns//1000000}
    found,missing=registry.match_drop([desc])
    assert len(found)==1 and not missing
    found,missing=registry.match_drop([{**desc,'name':'unknown.mp4'}])
    assert not found and missing==['unknown.mp4']


def test_extract_overlap_matches_pcm(config,audio):
    p=probe(audio,config)
    with PCMStream(audio,p['audio_stream_index'],config,threading.Event()) as stream:
        full=np.concatenate(list(stream))
    units=make_plan([Region(0,3),Region(5,10)],4,.35)
    with PCMStream(audio,p['audio_stream_index'],config,threading.Event()) as stream:
        for unit,wave in extract_units(stream,units):
            assert np.array_equal(wave,full[round(unit.start*16000):round(unit.end*16000)])


def test_video_unchanged(config,tmp_path):
    video=tmp_path/'test.mp4'
    subprocess.run([config.executable('ffmpeg'),'-v','error','-f','lavfi','-i','color=c=black:s=16x16:d=2','-f','lavfi','-i','sine=frequency=400:duration=2','-c:v','mpeg4','-c:a','aac','-shortest',str(video)],check=True)
    original=video.read_bytes(); p=probe(video,config)
    assert p['media_type']=='video'
    with PCMStream(video,p['audio_stream_index'],config,threading.Event()) as stream:
        assert sum(map(len,stream))>30000
    assert video.read_bytes()==original
    assert not list(tmp_path.glob('*.wav'))


def test_no_audio_stream(config,tmp_path):
    video=tmp_path/'silent.mp4'
    subprocess.run([config.executable('ffmpeg'),'-v','error','-f','lavfi','-i','color=s=16x16:d=1','-an','-c:v','mpeg4',str(video)],check=True)
    with pytest.raises(AppError):probe(video,config)


def test_cancel_decode(config,audio):
    cancel=threading.Event();cancel.set()
    with pytest.raises(Cancelled):
        with PCMStream(audio,0,config,cancel) as stream:list(stream)


def test_vad_regions_and_map(config):
    config.values['vad']['enabled']=True
    p=[0]*10+[.9]*40+[0]*30+[.9]*30
    regions=regions_from_probabilities(p,110*.032,config)
    assert len(regions)==2 and regions[0].start==pytest.approx(.32)
    values=make_speech_map(regions,110*.032,100)
    assert len(values)==100 and all(0<=v<=1 for v in values)


def test_silence_no_model(config,store,tmp_path):
    config.values['vad']['enabled']=True
    path=make_wav(tmp_path/'silence.wav',2,True)
    source=SourceRegistry(config,store).register([str(path)])[0][0]
    job=store.create_job(source['id'],'whisper','auto');job['started_at']=utc_now()
    models=TestModels();results=Results(config.root)
    name,meta=Pipeline(config,models,results,lambda:lambda frame:0.).run(job,store.source(source['id']),threading.Event(),lambda **kw:None,Aggregate())
    assert models.loads==0 and meta['model_invoked'] is False
    job['result_name']=name
    assert results.text(job)=='' and meta['warnings']


def test_pipeline_real_media_test_double_asr(config,store,audio):
    source=SourceRegistry(config,store).register([str(audio)])[0][0]
    job=store.create_job(source['id'],'whisper','ru');job['started_at']=utc_now()
    models=TestModels();results=Results(config.root);events=[]
    name,meta=Pipeline(config,models,results).run(job,store.source(source['id']),threading.Event(),lambda **event:events.append(event),Aggregate())
    assert meta['runtime']=='test-double-not-an-ASR'
    assert meta['planned_audio_seconds']==pytest.approx(10)
    numbers=[e['progress'] for e in events if e.get('progress') is not None]
    assert numbers==sorted(numbers) and numbers[-1]==100
    job['result_name']=name
    text=results.path(job).read_text()
    assert text.startswith('---\n') and str(audio.parent) not in text
    assert yaml.safe_load(text.split('---',2)[1])['quality_metrics']['wer'] is None
    assert 'ТЕСТ КОНВЕЙЕРА' in results.text(job)


def test_oom_retry_unique_progress(config,store,audio):
    config.values['models']['qwen']['max_chunk_seconds']=10
    source=SourceRegistry(config,store).register([str(audio)])[0][0]
    job=store.create_job(source['id'],'qwen','ru');job['started_at']=utc_now()
    models=TestModels(oom_once=True);events=[]
    _,meta=Pipeline(config,models,Results(config.root)).run(job,store.source(source['id']),threading.Event(),lambda **event:events.append(event),Aggregate())
    assert meta['processing']['oom_retries']==1
    assert events[-1]['processed_seconds']==10
    assert models.loads==2


def test_store_reorder_recover(config,store,audio):
    source=SourceRegistry(config,store).register([str(audio)])[0][0]
    jobs=[store.create_job(source['id'],'whisper','ru') for _ in range(4)]
    store.reorder_waiting([j['id'] for j in reversed(jobs)])
    assert store.jobs()[0]['id']==jobs[-1]['id']
    with pytest.raises(AppError):store.reorder_waiting([jobs[0]['id']]*4)
    store.update_job(jobs[0]['id'],status=Status.TRANSCRIBING)
    with pytest.raises(AppError):store.remove_job(jobs[0]['id'])
    assert store.recover()==1
    assert store.job(jobs[0]['id'])['status']=='INTERRUPTED'
    store.backup(config.root/'data/backups/test.db')
    with sqlite3.connect(config.root/'data/backups/test.db') as db:assert db.execute('select count(*) from jobs').fetchone()[0]==4


def test_file_changes_detected(config,store,audio):
    registry=SourceRegistry(config,store);source=registry.register([str(audio)])[0][0];job=store.create_job(source['id'],'whisper','ru')
    with audio.open('ab') as f:f.write(b'changed')
    with pytest.raises(AppError,match='изменился'):registry.validate_job_source(job)
    audio.unlink()
    with pytest.raises(AppError,match='недоступен'):registry.validate_job_source(job)


def test_results_no_overwrite_and_archive(config,store,audio):
    source=SourceRegistry(config,store).register([str(audio)])[0][0]
    job=store.create_job(source['id'],'whisper','ru');job['started_at']=utc_now()
    result=Results(config.root)
    a=result.write(job,{'x':'value: yaml'},'Текст.');b=result.write(job,{},'Другой.')
    assert a!=b and '__02.md' in b and 'Лекция' in a
    job['result_name']=a
    archive=result.archive([job,job])
    with zipfile.ZipFile(archive) as z:assert len(set(z.namelist()))==2 and all(n.endswith('.md') for n in z.namelist())
    assert result.text(job)=='Текст.'


def test_aggregate_real_nulls():
    a=Aggregate();a.add({'monotonic':0,'cpu_utilization_pct':10});a.add({'monotonic':2,'cpu_utilization_pct':30})
    out=a.summary();assert out['cpu_utilization_pct']['average']==20 and out['gpu_utilization_pct'] is None


def wait_for(test,seconds=8):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if test():return
        time.sleep(.04)
    raise AssertionError('Condition timed out')


def test_scheduler_one_model_reuse_and_persistence(config,store,audio):
    telemetry=Telemetry(.5);models=TestModels();manager=JobManager(config,store,telemetry,models)
    source=manager.sources.register([str(audio)])[0][0]
    jobs=manager.add([source['id']]*3,'whisper','ru');manager.start_service();manager.start_queue()
    try:
        wait_for(lambda:all(j['status']=='COMPLETE' for j in store.jobs()),15)
        assert models.loads==1
        assert len(list((config.root/'data/results').glob('*/*.md')))==3
    finally:manager.close();telemetry.close()
    again=Store(config.root/'data/state.db')
    assert all(j['status']=='COMPLETE' for j in again.jobs());again.close()


def test_failed_job_does_not_kill_queue(config,store,audio):
    telemetry=Telemetry(.5);models=TestModels();manager=JobManager(config,store,telemetry,models)
    source=manager.sources.register([str(audio)])[0][0]
    jobs=manager.add([source['id']]*2,'whisper','ru')
    store.update_job(jobs[0]['id'],source_mtime_ns=0)
    manager.start_service();manager.start_queue()
    try:
        wait_for(lambda:store.job(jobs[1]['id'])['status']=='COMPLETE')
        assert store.job(jobs[0]['id'])['status']=='FAILED'
    finally:manager.close();telemetry.close()


def test_pause_cancel_queue(config,store,audio):
    telemetry=Telemetry(.5);models=TestModels(delay=.2);manager=JobManager(config,store,telemetry,models)
    source=manager.sources.register([str(audio)])[0][0]
    jobs=manager.add([source['id']]*2,'whisper','ru');manager.start_service();manager.start_queue()
    try:
        wait_for(lambda:manager.active_id is not None)
        manager.pause_queue()
        wait_for(lambda:store.job(jobs[0]['id'])['status']=='COMPLETE')
        time.sleep(.2);assert store.job(jobs[1]['id'])['status']=='WAITING'
        manager.start_queue();wait_for(lambda:manager.active_id==jobs[1]['id']);manager.cancel_current()
        wait_for(lambda:store.job(jobs[1]['id'])['status']=='CANCELLED')
        assert not list((config.root/'data/results'/jobs[1]['id']).glob('*.md'))
    finally:manager.close();telemetry.close()


def test_api_security_and_crud(config,store,audio):
    telemetry=Telemetry(.5);models=TestModels();manager=JobManager(config,store,telemetry,models)
    source=manager.sources.register([str(audio)])[0][0]
    app=create_app(config,manager)
    with TestClient(app,base_url='http://127.0.0.1:8765') as c:
        assert c.get('/health').status_code==200
        assert c.get('/api/state').status_code==401
        assert c.get('/health',headers={'Host':'evil.example'}).status_code==403
        assert c.get('/api/session',headers={'Origin':'https://evil.example'}).status_code==403
        token=c.get('/api/session').json()['csrf'];headers={'X-Sloi-Csrf':token}
        assert c.post('/api/queue/start').status_code==403
        state=c.get('/api/state').json();assert 'path' not in json.dumps(state)
        assert c.post('/api/jobs',json={'source_ids':[source['id']],'model':'gigaam','language':'en'},headers=headers).status_code==400
        assert c.post('/api/jobs',json={'source_ids':[source['id']],'model':'whisper','language':'ru','path':str(audio)},headers=headers).status_code==422
        response=c.post('/api/jobs',json={'source_ids':[source['id']],'model':'whisper','language':'ru'},headers=headers)
        assert response.status_code==200
        assert c.put('/api/preferences',json={'theme':'paper','accent':'#224466'},headers=headers).status_code==200
        assert c.get('/api/state').json()['preferences']['theme']=='paper'
        assert c.post('/api/queue/start',headers=headers).status_code==200
        wait_for(lambda:store.jobs()[0]['status']=='COMPLETE')
        job=store.jobs()[0]
        data=c.get('/api/results/'+job['id']+'/download')
        assert data.status_code==200 and data.text.startswith('---\n')
        assert 'attachment;' in data.headers['content-disposition']
        assert c.get('/api/results/'+job['id']+'/text').json()['text'].startswith('ТЕСТ')
        assert c.get('/api/results.zip').status_code==200
        assert not list((config.root/'runtime/temp').glob('*.zip'))
        assert 'unsafe-eval' not in c.get('/').headers['content-security-policy']


def test_websocket_origin_and_initial_state(config,store):
    app=create_app(config,JobManager(config,store,Telemetry(.5),TestModels()))
    with TestClient(app,base_url='http://127.0.0.1:8765') as c:
        c.get('/api/session')
        with c.websocket_connect('ws://127.0.0.1:8765/ws',headers={'Origin':'http://127.0.0.1:8765'}) as socket:
            state=socket.receive_json();assert state['queue']['jobs']==[]
