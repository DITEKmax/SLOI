from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path


DIRECTORIES = {'sloi', 'frontend', 'requirements', 'scripts', 'docs', 'tests', 'validation', 'config'}
TOP_FILES = {'install.bat', 'start.bat', 'diagnose.bat', 'benchmark.bat', 'update.bat', 'README_RU.md', 'DEPLOYMENT_RU.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'pytest.ini'}
SKIP_PARTS = {'__pycache__', '.pytest_cache', 'node_modules', '.git', 'fonts'}
SKIP_EXTENSIONS = {'.pyc', '.pyo', '.ttf', '.otf', '.woff', '.woff2', '.eot', '.wav', '.mp4', '.m4a', '.mp3', '.safetensors', '.onnx', '.exe', '.dll'}


def package(root: Path, destination: Path) -> dict:
    selected = []
    for file in sorted(root.rglob('*')):
        if not file.is_file() or file.is_symlink():
            continue
        relative = file.relative_to(root)
        if (relative.parts[0] not in DIRECTORIES and relative.as_posix() not in TOP_FILES) or any(part in SKIP_PARTS for part in relative.parts) or file.suffix.lower() in SKIP_EXTENSIONS:
            continue
        selected.append(file)
    version = re.search(r'__version__\s*=\s*["\']([^"\']+)', (root / 'sloi' / '__init__.py').read_text()).group(1)
    hashes = {file.relative_to(root).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest() for file in selected}
    manifest = {'schema': 1, 'app': 'sloi', 'version': version, 'files': hashes}
    manifest_path = root / 'package_manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in selected + [manifest_path]:
            archive.write(file, 'SLOI/' + file.relative_to(root).as_posix())
    with zipfile.ZipFile(destination) as archive:
        broken = archive.testzip()
        if broken:
            raise ValueError('ZIP CRC check failed: ' + broken)
        for name, expected in hashes.items():
            if hashlib.sha256(archive.read('SLOI/' + name)).hexdigest() != expected:
                raise ValueError('ZIP SHA-256 check failed: ' + name)
    return {'archive': destination.name, 'bytes': destination.stat().st_size, 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(), 'manifest_files': len(hashes), 'zip_files': len(hashes) + 1, 'crc': 'passed', 'all_manifest_sha256': 'passed', 'font_binaries_included': False, 'model_weights_included': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(package(args.root.resolve(), args.output.resolve()), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
