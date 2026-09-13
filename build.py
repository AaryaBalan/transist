#!/usr/bin/env python3
"""Create reproducible source and extension archives using the standard library."""
from pathlib import Path
import zipfile
import subprocess

ROOT = Path(__file__).resolve().parent
DIST = ROOT / 'dist'


def archive(destination, files):
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as out:
        for path, name in sorted(files, key=lambda item: item[1]):
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 12, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100644 << 16)
            out.writestr(info, path.read_bytes())
    print(destination)


def main():
    subprocess.run(['glib-compile-schemas', '--strict', str(ROOT / 'extension/schemas')], check=True)
    DIST.mkdir(exist_ok=True)
    sources = []
    for path in ROOT.rglob('*'):
        relative = path.relative_to(ROOT)
        if not path.is_file() or any(part in {'dist', '__pycache__', '.git', '.venv'} for part in relative.parts) or path.suffix == '.pyc':
            continue
        sources.append((path, 'transit/' + relative.as_posix()))
    archive(DIST / 'transit-v0.1.0.zip', sources)
    extension = [(path, path.relative_to(ROOT / 'extension').as_posix()) for path in (ROOT / 'extension').rglob('*') if path.is_file()]
    extension.append((ROOT / 'LICENSE', 'LICENSE'))
    archive(DIST / 'transit@aaryabalan.local.shell-extension.zip', extension)


if __name__ == '__main__':
    main()
