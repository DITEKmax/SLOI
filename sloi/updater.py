from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from .instance import InstanceLock
from .native import windows_picker
from .results import atomic_json


ALLOWED_ROOTS = {'sloi', 'frontend', 'requirements', 'scripts', 'docs', 'tests', 'validation', 'samples'}
ALLOWED_TOP = {'install.bat', 'start.bat', 'diagnose.bat', 'benchmark.bat', 'update.bat', 'README_RU.md', 'DEPLOYMENT_RU.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'pytest.ini', 'package_manifest.json'}
ALLOWED_CONFIG = {'config/defaults.yaml', 'config/models.manifest.json', 'config/app.yaml'}


def allowed(name: str) -> bool:
    path = Path(name)
    return not path.is_absolute() and '..' not in path.parts and '\\' not in name and (name in ALLOWED_TOP or name in ALLOWED_CONFIG or path.parts[0] in ALLOWED_ROOTS)


def verify_bundle(archive: Path, stage: Path) -> list[str]:
    with zipfile.ZipFile(archive) as z:
        entries = z.infolist()
        if len(entries) > 20000 or sum(e.file_size for e in entries) > 512 * 1024**2 or any(e.file_size > 128 * 1024**2 for e in entries):
            raise ValueError('Update archive exceeds the source-package size limit.')
        names = [e.filename for e in entries if not e.is_dir()]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate archive paths are not allowed.')
        prefix = 'SLOI/' if names and all(n.startswith('SLOI/') for n in names) else ''
        manifest_name = prefix + 'package_manifest.json'
        if manifest_name not in names:
            raise ValueError('Not a SLOI update archive: package_manifest.json is missing.')
        manifest = json.loads(z.read(manifest_name))
        if manifest.get('app') != 'sloi' or manifest.get('schema') != 1:
            raise ValueError('Invalid update manifest.')
        expected = manifest['files']
        if set(names) != {prefix + n for n in expected} | {manifest_name}:
            raise ValueError('Archive and manifest file lists differ.')
        for entry in z.infolist():
            if entry.is_dir():
                continue
            name = entry.filename[len(prefix):]
            if not allowed(name) or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Forbidden update path: ' + name)
            data = z.read(entry)
            if name != 'package_manifest.json' and hashlib.sha256(data).hexdigest() != expected[name]:
                raise ValueError('Update checksum mismatch: ' + name)
            target = (stage / name).resolve()
            if not target.is_relative_to(stage.resolve()):
                raise ValueError('Unsafe update path.')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return list(expected) + ['package_manifest.json']


def backup_database(source: Path, target: Path) -> None:
    if source.is_file():
        with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
            src.backup(dst)


def update(root: Path, archive: Path) -> int:
    if os.name != 'nt':
        raise RuntimeError('Deployment updater targets Windows.')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = root / 'data' / 'backups' / ('update-' + stamp)
    backup.mkdir(parents=True)
    changed, created = [], []
    with tempfile.TemporaryDirectory(prefix='sloi-update-') as temp:
        stage = Path(temp)
        paths = verify_bundle(archive, stage)
        with InstanceLock(root):
            backup_database(root / 'data' / 'state.db', backup / 'state.db')
            for name in ('config/app.yaml', 'runtime/active.json'):
                source = root / name
                if source.is_file():
                    destination = backup / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
            try:
                for name in paths:
                    target = root / name
                    if name == 'config/app.yaml' and target.exists():
                        continue
                    if target.exists():
                        old = backup / 'code' / name
                        old.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, old)
                        changed.append(name)
                    else:
                        created.append(name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(stage / name, target)
                check = subprocess.run([sys.executable, '-c', 'from pathlib import Path; from sloi.config import Config; from sloi.app import create_app; Config(Path.cwd()); print("Configuration and imports: OK")'], cwd=root)
                if check.returncode:
                    raise RuntimeError('New application import check failed.')
            except Exception:
                restore(root, backup, changed, created)
                raise
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(root / 'scripts' / 'install.ps1')], cwd=root)
        if result.returncode not in (0, 2):
            with InstanceLock(root):
                restore(root, backup, changed, created)
            atomic_json(backup / 'result.json', {'status': 'rolled_back', 'installer_exit': result.returncode})
            raise RuntimeError('Update failed. Previous application/config/runtime pointer restored. Models and results were not deleted.')
        atomic_json(backup / 'result.json', {'status': 'updated', 'installer_exit': result.returncode, 'archive': archive.name})
        print('Updated. Existing results, queue, user config and models have been preserved.')
        return result.returncode


def restore(root: Path, backup: Path, changed: list[str], created: list[str]) -> None:
    for name in changed:
        shutil.copy2(backup / 'code' / name, root / name)
    for name in created:
        (root / name).unlink(missing_ok=True)
    for name in ('runtime/active.json', 'config/app.yaml'):
        if (backup / name).is_file():
            shutil.copy2(backup / name, root / name)
    if (backup / 'state.db').is_file():
        with sqlite3.connect(backup / 'state.db') as src, sqlite3.connect(root / 'data' / 'state.db') as dst:
            src.backup(dst)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('archive', type=Path, nargs='?')
    args = parser.parse_args()
    archive = args.archive
    if archive is None:
        if os.name != 'nt':
            raise RuntimeError('Pass a SLOI ZIP archive.')
        print('Choose the new SLOI ZIP archive. Select "All files" in the dialog.')
        selected = windows_picker()
        if not selected:
            return 0
        if len(selected) != 1:
            raise ValueError('Choose exactly one update archive.')
        archive = Path(selected[0])
    return update(args.root.resolve(), archive.resolve(strict=True))


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
