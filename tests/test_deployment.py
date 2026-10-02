import hashlib
import json
import os
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

import numpy as np
import psutil
import pytest

from sloi.asr.manager import ModelManager
from sloi.instance import InstanceLock
from sloi.installation import safe_extract
from sloi.media import SourceRegistry
from sloi.updater import verify_bundle


def test_instance_lock_single_owner(config):
    with InstanceLock(config.root):
        with pytest.raises(RuntimeError):
            InstanceLock(config.root)
    with InstanceLock(config.root):
        pass


def bundle(path,entries):
    payload={n:hashlib.sha256(data).hexdigest() for n,data in entries.items()}
    with zipfile.ZipFile(path,'w') as z:
        for name,data in entries.items():z.writestr('SLOI/'+name,data)
        z.writestr('SLOI/package_manifest.json',json.dumps({'app':'sloi','schema':1,'files':payload}))
    return path


def test_update_validates_every_hash(tmp_path):
    file=bundle(tmp_path/'a.zip',{'sloi/__init__.py':b'__version__="test"','config/app.yaml':b'schema: 1'})
    names=verify_bundle(file,tmp_path/'stage')
    assert 'sloi/__init__.py' in names
    assert (tmp_path/'stage/config/app.yaml').read_text()=='schema: 1'


def test_update_cannot_modify_user_data(tmp_path):
    file=bundle(tmp_path/'bad.zip',{'data/state.db':b'bad'})
    with pytest.raises(ValueError,match='Forbidden'):verify_bundle(file,tmp_path/'stage')


def test_update_tampering_rejected(tmp_path):
    file=tmp_path/'tampered.zip'
    with zipfile.ZipFile(file,'w') as z:
        z.writestr('sloi/__init__.py',b'bad')
        z.writestr('package_manifest.json',json.dumps({'app':'sloi','schema':1,'files':{'sloi/__init__.py':'0'*64}}))
    with pytest.raises(ValueError,match='checksum'):verify_bundle(file,tmp_path/'stage')


def test_tool_zip_traversal_rejected(tmp_path):
    file=tmp_path/'tool.zip'
    with zipfile.ZipFile(file,'w') as z:z.writestr('../outside',b'bad')
    with pytest.raises(ValueError,match='Unsafe'):safe_extract(file,tmp_path/'stage')
    assert not (tmp_path/'outside').exists()


def test_real_worker_process_shared_memory_and_release(config,monkeypatch):
    real_popen=subprocess.Popen
    helper=Path(__file__).with_name('worker_fixture.py')
    def redirected(command,*args,**kwargs):
        return real_popen([sys.executable,str(helper)],*args,**kwargs)
    monkeypatch.setattr('sloi.asr.manager.subprocess.Popen',redirected)
    manager=ModelManager(config)
    monkeypatch.setattr(manager,'python_for',lambda name:Path(sys.executable))
    for model in ('gigaam','parakeet'):
        path=config.root/'models'/model;path.mkdir(parents=True)
        (path/'.sloi-model.json').write_text('{"repository":"test","revision":"test"}')
    try:
        metadata=manager.ensure('gigaam',threading.Event())
        assert metadata['runtime']=='test-process-not-asr'
        pid=manager.process.pid
        waves=[np.array([.125,.25],dtype=np.float32),np.array([.5,.75],dtype=np.float32)]
        results=manager.recognize(waves,'ru',threading.Event())
        assert [r.text for r in results]==['IPC TEST 0.125','IPC TEST 0.5']
        assert manager.ensure('gigaam',threading.Event())['model_reused'] is True
        manager.ensure('parakeet',threading.Event())
        assert not psutil.pid_exists(pid)
        last_pid=manager.process.pid
        manager.stop()
        assert not psutil.pid_exists(last_pid)
    finally:manager.stop()


@pytest.mark.skipif(os.name=='nt',reason='Sparse-file probe in Linux cloud; native drop is a separate Windows gate')
def test_ten_gib_sparse_video_registered_without_copy(config,store,tmp_path):
    file=tmp_path/'large.mp4'
    subprocess.run([config.executable('ffmpeg'),'-v','error','-f','lavfi','-i','color=c=black:s=16x16:d=1','-f','lavfi','-i','sine=frequency=400:duration=1','-c:v','mpeg4','-c:a','aac','-shortest',str(file)],check=True)
    with file.open('r+b') as stream:stream.truncate(10*1024**3)
    before=file.stat()
    sources,errors=SourceRegistry(config,store).register([str(file)])
    assert not errors and sources[0]['size']==10*1024**3
    assert file.stat().st_mtime_ns==before.st_mtime_ns
    assert file.stat().st_blocks==before.st_blocks
    assert not any(p.stat().st_size>10*1024**2 for p in config.root.rglob('*') if p.is_file())


def test_qwen_output_parser_preserves_ielts_repetitions():
    from sloi.asr.adapters import parse_qwen_raw
    raw='language English<asr_text>I I I was, well, I was there.'
    parsed=parse_qwen_raw(raw)
    assert parsed['language']=='English'
    assert parsed['transcription']=='I I I was, well, I was there.'
    assert parse_qwen_raw('A plain transcript')['transcription']=='A plain transcript'
