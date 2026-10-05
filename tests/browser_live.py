"""Run the real local API/frontend with synthetic audio and a labeled ASR double.

Usage: python tests/browser_live.py --root ../qa/live-project --port 8765
This is a QA server only: it does not download or run speech recognition models.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import uvicorn
from fastapi.responses import HTMLResponse


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from conftest import TestModels, make_wav
from sloi.app import create_app
from sloi.config import Config
from sloi.jobs import JobManager
from sloi.store import Store
from sloi.telemetry import Telemetry


def build_qa_app(root: Path, port: int = 8765, delay: float = 2.5):
    config = Config(root, {
        'server': {'port': port},
        'vad': {'enabled': False},
        'telemetry': {'interval_seconds': .25},
        'ui': {'default_model': 'whisper', 'default_language': 'ru'},
        'models': {name: {'max_chunk_seconds': 4} for name in ('gigaam', 'qwen', 'whisper', 'parakeet')},
    })
    fixture_dir = config.root / 'fixtures'
    fixture_dir.mkdir(parents=True, exist_ok=True)
    audio = make_wav(fixture_dir / 'Лекция — браузерный тест.wav', 3)
    cancel_audio = make_wav(fixture_dir / 'Отмена — браузерный тест.wav', 12)
    store = Store(config.root / 'data' / 'state.db')
    telemetry = Telemetry(.25)
    models = TestModels(delay=delay)
    manager = JobManager(config, store, telemetry, models)
    app = create_app(config, manager)

    @app.middleware('http')
    async def label_qa_frontend(request, call_next):
        response = await call_next(request)
        if request.method != 'GET' or request.url.path != '/' or not response.headers.get('content-type', '').startswith('text/html'):
            return response
        body = b''.join([chunk async for chunk in response.body_iterator]).decode('utf-8')
        label = '<div id="live-qa-label" style="position:fixed;bottom:0;left:0;right:0;z-index:9999;background:#101217;color:#e4e4ea;text-align:center;font:11px Arial;padding:5px;letter-spacing:.4px">LIVE API QA · СИНТЕТИЧЕСКОЕ АУДИО / ASR TEST DOUBLE · НЕ ОЦЕНКА РАСПОЗНАВАНИЯ</div>'
        headers = {key: value for key, value in response.headers.items() if key.lower() != 'content-length'}
        return HTMLResponse(body.replace('</body>', label + '</body>'), status_code=response.status_code, headers=headers)

    return app, {'url': f'http://127.0.0.1:{port}', 'root': str(config.root), 'audio': str(audio), 'cancel_audio': str(cancel_audio), 'asr': 'TestModels; synthetic text; not real ASR', 'delay_per_batch_seconds': delay}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=PROJECT.parent / 'qa' / 'live-project')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--asr-delay', type=float, default=2.5)
    args = parser.parse_args()
    if args.asr_delay < 0:
        parser.error('--asr-delay must be non-negative')
    if args.root.resolve() == PROJECT:
        parser.error('QA data must use a separate root, not the application project')
    app, details = build_qa_app(args.root, args.port, args.asr_delay)
    print(json.dumps({'live_qa': details}, ensure_ascii=False), flush=True)
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning', access_log=False)


if __name__ == '__main__':
    main()
