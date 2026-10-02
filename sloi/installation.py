from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from . import __version__
from .config import Config
from .domain import utc_now
from .instance import InstanceLock
from .results import atomic_json, atomic_text


FFMPEG_URL = 'https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-8.1.2-essentials_build.zip'
FFMPEG_SHA = 'db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec'
FONTS = {
    'Unbounded': ('unbounded', 'Unbounded[wght].ttf'),
    'GolosText': ('golostext', 'GolosText[wght].ttf'),
    'Commissioner': ('commissioner', 'Commissioner[FLAR,VOLM,slnt,wght].ttf'),
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def download(url: str, destination: Path, expected: str | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and (expected is None or digest(destination) == expected):
        return
    temporary = destination.with_name(destination.name + '.partial')
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'SLOI/' + __version__})
            with urllib.request.urlopen(req, timeout=90) as response, temporary.open('wb') as out:
                shutil.copyfileobj(response, out, length=2 * 1024**2)
            if expected and digest(temporary) != expected:
                raise ValueError('Checksum mismatch: ' + destination.name)
            os.replace(temporary, destination)
            return
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def safe_extract(archive: Path, folder: Path) -> None:
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            path = (folder / entry.filename).resolve()
            if not path.is_relative_to(folder.resolve()) or '\\' in entry.filename or entry.filename.startswith('/'):
                raise ValueError('Unsafe archive entry')
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Archive symlinks are not allowed')
        z.extractall(folder)


def install_ffmpeg(root: Path) -> dict[str, Any]:
    destination = root / 'runtime' / 'ffmpeg'
    stamp_path = destination / '.sloi-tool.json'
    if stamp_path.exists():
        stamp = json.loads(stamp_path.read_text(encoding='utf-8'))
        if stamp.get('archive_sha256') == FFMPEG_SHA and all((destination / file).is_file() and digest(destination / file) == sha for file, sha in stamp.get('files', {}).items()) and (destination / 'ffmpeg.exe').is_file() and (destination / 'ffprobe.exe').is_file():
            return stamp
    archive = root / 'runtime' / 'bootstrap' / 'ffmpeg-8.1.2.zip'
    download(FFMPEG_URL, archive, FFMPEG_SHA)
    stage = root / 'runtime' / 'bootstrap' / 'ffmpeg-extract'
    if stage.exists():
        shutil.rmtree(stage)
    safe_extract(archive, stage)
    binaries = {name: next(stage.rglob(name), None) for name in ('ffmpeg.exe', 'ffprobe.exe')}
    if not all(binaries.values()):
        raise ValueError('FFmpeg executables missing in verified archive')
    destination.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, path in binaries.items():
        shutil.copy2(path, destination / name)
        files[name] = digest(destination / name)
    for path in stage.rglob('*'):
        if path.is_file() and any(part in path.name.lower() for part in ('license', 'readme')):
            target = destination / 'notices' / path.name
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(path, target)
    report = {'version': '8.1.2', 'url': FFMPEG_URL, 'archive_sha256': FFMPEG_SHA, 'files': files}
    atomic_json(stamp_path, report)
    shutil.rmtree(stage)
    archive.unlink(missing_ok=True)
    return report


def install_fonts(root: Path) -> dict[str, Any]:
    from fontTools.ttLib import TTFont
    report = {}
    target = root / 'frontend' / 'dist' / 'fonts'
    for family, (folder, filename) in FONTS.items():
        base = 'https://raw.githubusercontent.com/google/fonts/main/ofl/' + folder + '/'
        file = target / ({'Unbounded': 'unbounded', 'GolosText': 'golos', 'Commissioner': 'commissioner'}[family] + '.ttf')
        download(base + urllib.parse.quote(filename), file)
        download(base + 'OFL.txt', target / (family + '-OFL.txt'))
        try:
            with TTFont(file) as font:
                cmap = font.getBestCmap() or {}
                absent = [char for char in 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя0123456789' if ord(char) not in cmap]
                if absent:
                    raise ValueError(f'{family}: Cyrillic/number glyphs missing: {absent}')
                axes = [axis.axisTag for axis in font['fvar'].axes] if 'fvar' in font else []
        except Exception:
            file.unlink(missing_ok=True)
            raise
        report[family] = {'source': base + urllib.parse.quote(filename), 'sha256': digest(file), 'cyrillic_checked': True, 'axes': axes}
    atomic_json(root / 'data' / 'reports' / 'fonts.json', report)
    return report


def download_model_ranges(url: str, destination: Path, expected_size: int, expected_sha: str) -> Path:
    import httpx

    expected_sha = expected_sha.lower()
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + '.partial')
    if destination.is_file() and destination.stat().st_size == expected_size and digest(destination) == expected_sha:
        return destination

    def quarantine_partial(reason: str) -> None:
        if not partial.is_file():
            return
        stamp = time.strftime('%Y%m%dT%H%M%S', time.gmtime())
        quarantined = partial.with_name(partial.name + '.invalid-' + stamp)
        suffix = 1
        while quarantined.exists():
            quarantined = partial.with_name(partial.name + '.invalid-' + stamp + '-' + str(suffix))
            suffix += 1
        os.replace(partial, quarantined)
        print('MODEL_PARTIAL_QUARANTINED', destination.name, reason, flush=True)

    if partial.is_file() and partial.stat().st_size > expected_size:
        quarantine_partial('oversized')

    chunk_size = 8 * 1024**2
    timeout = httpx.Timeout(90.0, connect=30.0)
    sha_restarts = 0
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        failures = 0
        while True:
            offset = partial.stat().st_size if partial.exists() else 0
            if offset == expected_size:
                actual_sha = digest(partial)
                if actual_sha != expected_sha:
                    quarantine_partial('sha256-mismatch')
                    if sha_restarts:
                        raise ValueError('Model SHA-256 mismatch after a fresh download: ' + destination.name)
                    sha_restarts += 1
                    continue
                os.replace(partial, destination)
                return destination
            start = offset
            end = min(start + chunk_size, expected_size) - 1
            if start == 0 or start % (128 * 1024**2) == 0:
                print('MODEL_RANGE', destination.name, start, '/', expected_size, flush=True)
            try:
                with client.stream('GET', url, headers={'Range': f'bytes={start}-{end}'}) as response:
                    if response.status_code != 206:
                        raise ValueError('Model range request returned HTTP ' + str(response.status_code))
                    content_range = response.headers.get('Content-Range', '')
                    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', content_range)
                    if not match or tuple(map(int, match.groups())) != (start, end, expected_size):
                        raise ValueError('Model range response did not match pinned size/offset: ' + destination.name)
                    expected_bytes = end - start + 1
                    received = 0
                    with partial.open('ab' if start else 'wb') as output:
                        for block in response.iter_bytes():
                            if received + len(block) > expected_bytes:
                                raise ValueError('Model range response exceeded requested length: ' + destination.name)
                            output.write(block)
                            received += len(block)
                    if received != expected_bytes:
                        raise OSError(f'Model range was short: received {received} of {expected_bytes} bytes')
                failures = 0
            except (httpx.HTTPError, OSError, ValueError) as exc:
                failures += 1
                if failures >= 3:
                    raise
                print('MODEL_RANGE_RETRY', destination.name, start, type(exc).__name__, failures, flush=True)
                time.sleep(failures)


def install_models(root: Path) -> dict[str, Any]:
    from huggingface_hub import HfApi, hf_hub_download
    manifest = json.loads((root / 'config' / 'models.manifest.json').read_text(encoding='utf-8'))
    api = HfApi()
    report = {}
    for model_id, spec in manifest.items():
        if model_id == 'schema':
            continue
        print('MODEL', model_id, spec['repository'], flush=True)
        info = api.model_info(spec['repository'], revision=spec['revision'], files_metadata=True)
        if info.sha != spec['revision']:
            raise ValueError('Model revision mismatch: ' + model_id)
        available = {file.rfilename: file for file in info.siblings}
        selected = list(spec.get('files', []))
        for pattern in spec.get('patterns', []) + spec.get('optional_patterns', []):
            selected.extend(name for name in available if fnmatch.fnmatch(name, pattern))
        selected = sorted(set(selected))
        if not selected or any(file not in available for file in selected):
            raise ValueError('Pinned model manifest is incomplete: ' + model_id)
        folder = root / 'models' / model_id
        folder.mkdir(parents=True, exist_ok=True)
        files = {}
        range_mode = os.environ.get('SLOI_MODEL_RANGE_DOWNLOAD') == '1'
        for file in selected:
            metadata = available[file]
            lfs = getattr(metadata, 'lfs', None)
            expected_sha = getattr(lfs, 'sha256', None) if lfs else None
            if isinstance(lfs, dict):
                expected_sha = lfs.get('sha256')
            relative = Path(file)
            destination = (folder / relative).resolve()
            if not destination.is_relative_to(folder.resolve()) or relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Unsafe model manifest path: ' + file)
            if range_mode and metadata.size is not None and expected_sha:
                url = 'https://huggingface.co/' + spec['repository'] + '/resolve/' + spec['revision'] + '/' + urllib.parse.quote(file, safe='/')
                path = download_model_ranges(url, destination, metadata.size, expected_sha)
            else:
                path = Path(hf_hub_download(repo_id=spec['repository'], filename=file, revision=spec['revision'], local_dir=folder))
            actual_sha = digest(path)
            valid = (metadata.size is None or path.stat().st_size == metadata.size) and (expected_sha is None or expected_sha == actual_sha)
            if not valid:
                path = Path(hf_hub_download(repo_id=spec['repository'], filename=file, revision=spec['revision'], local_dir=folder, force_download=True))
                actual_sha = digest(path)
                if (metadata.size is not None and path.stat().st_size != metadata.size) or (expected_sha and expected_sha != actual_sha):
                    raise ValueError('Model integrity verification failed: ' + model_id + '/' + file)
            files[file] = {'bytes': path.stat().st_size, 'sha256': actual_sha, 'upstream_sha256_checked': bool(expected_sha)}
        stamp = {'repository': spec['repository'], 'revision': spec['revision'], 'license': spec['license'], 'files': files, 'verified_at': utc_now(), 'gpu_test': 'not_run'}
        atomic_json(folder / '.sloi-model.json', stamp)
        report[model_id] = {'revision': spec['revision'], 'bytes': sum(f['bytes'] for f in files.values())}
    return report


def execute(command: list[str], root: Path) -> None:
    print('RUN', ' '.join(command), flush=True)
    process = subprocess.run(command, cwd=root)
    if process.returncode:
        raise RuntimeError('Dependency command failed with exit code ' + str(process.returncode))


def install_environments(root: Path, uv: Path) -> dict[str, str]:
    environments = {'core': str(Path(sys.executable).resolve().relative_to(root))}
    for name in ('transformers', 'onnx', 'whisper'):
        requirements = root / 'requirements' / (name + '.txt')
        source = requirements.read_bytes() + b'python3.13.5;torch2.10.0+cu128'
        fingerprint = hashlib.sha256(source).hexdigest()[:12]
        folder = root / 'runtime' / 'envs' / f'{name}-313-{fingerprint}'
        python = folder / 'Scripts' / 'python.exe'
        if not python.is_file():
            execute([str(uv), 'venv', '--python', '3.13.5', '--managed-python', str(folder)], root)
        if name == 'transformers':
            execute([str(uv), 'pip', 'install', '--python', str(python), '--only-binary', ':all:', '--index-url', 'https://download.pytorch.org/whl/cu128', 'torch==2.10.0'], root)
        execute([str(uv), 'pip', 'install', '--python', str(python), '--only-binary', ':all:', '-r', str(requirements)], root)
        execute([str(uv), 'pip', 'check', '--python', str(python)], root)
        probe_code = {'transformers': 'import torch; from transformers import AutoProcessor,Qwen3ASRForConditionalGeneration; print(torch.__version__, torch.version.cuda); assert torch.version.cuda is not None', 'onnx': 'import onnxruntime, onnx_asr; print(onnxruntime.__version__); assert "CUDAExecutionProvider" in onnxruntime.get_available_providers()', 'whisper': 'import ctranslate2, faster_whisper; print(ctranslate2.__version__)'}[name]
        execute([str(python), '-c', probe_code], root)
        freeze = subprocess.run([str(uv), 'pip', 'freeze', '--python', str(python)], capture_output=True, text=True, encoding='utf-8', check=True)
        atomic_text(root / 'data' / 'reports' / f'lock-{name}.txt', freeze.stdout)
        environments[name] = str(python.relative_to(root))
    freeze = subprocess.run([str(uv), 'pip', 'freeze', '--python', sys.executable], capture_output=True, text=True, encoding='utf-8', check=True)
    atomic_text(root / 'data' / 'reports' / 'lock-core.txt', freeze.stdout)
    return environments


def install(root: Path, uv: Path, skip_smoke: bool) -> int:
    if os.name != 'nt':
        raise RuntimeError('The deployment installer targets Windows x64; Linux is only used for cloud tests.')
    config = Config(root)
    report: dict[str, Any] = {'app_version': __version__, 'started_at': utc_now(), 'status': 'installing', 'python': sys.version, 'free_disk_before': shutil.disk_usage(root).free}
    report_path = root / 'data' / 'reports' / 'install.json'
    try:
        with InstanceLock(root):
            if shutil.disk_usage(root).free < 10 * 1024**3:
                raise RuntimeError('Less than 10 GiB free. Reserve about 25–30 GiB for a first installation and its caches.')
            print('[3/6] Isolated ASR environments. This step downloads CUDA/PyTorch once.', flush=True)
            environments = install_environments(root, uv)
            print('[4/6] FFmpeg, four ASR models and Silero VAD. Downloads are resumable.', flush=True)
            report['ffmpeg'] = install_ffmpeg(root)
            report['models'] = install_models(root)
            print('[5/6] Local Google Fonts; verifying Cyrillic glyphs.', flush=True)
            report['fonts'] = install_fonts(root)
            atomic_json(root / 'runtime' / 'active.json', {'schema': 1, 'app_version': __version__, 'python_version': sys.version.split()[0], 'environments': environments})
            print('[6/6] Real GPU smoke tests: load → speech → unload.', flush=True)
            if not skip_smoke:
                from .cli import diagnose
                diagnostics = diagnose(config, smoke=True)
                report['gpu_smoke'] = diagnostics['all_four_gpu_smoke_passed']
                report['status'] = 'installed_smoke_passed' if report['gpu_smoke'] else 'installed_gpu_validation_incomplete'
            else:
                report['status'] = 'installed_gpu_validation_skipped'
                report['gpu_smoke'] = False
            report['completed_at'] = utc_now()
            atomic_json(report_path, report)
            return 0 if report['gpu_smoke'] else 2
    except Exception as exc:
        report.update({'status': 'failed', 'error_type': type(exc).__name__, 'error': str(exc)[:4000], 'completed_at': utc_now()})
        atomic_json(report_path, report)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--uv', type=Path, required=True)
    parser.add_argument('--skip-smoke', action='store_true')
    args = parser.parse_args()
    return install(args.root.resolve(), args.uv.resolve(), args.skip_smoke)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
