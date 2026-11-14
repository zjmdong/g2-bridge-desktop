"""Package reviewable app sources and the exact corresponding native FFmpeg source."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from goggles_bridge import __version__


def main():
    manifest = json.loads((ROOT/'packaging/windows/ffmpeg/manifest.json').read_text(encoding='utf-8'))
    source = manifest['upstream']['source_archive']
    path = ROOT/source['path']
    if hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
        raise ValueError('Native source archive checksum mismatch')
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    target = ROOT/f'dist/GogglesBridge-{__version__}-Source.zip'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for name in sorted(tracked):
            if name and (ROOT/name).is_file():
                bundle.write(ROOT/name, 'goggles-bridge/'+name)
        bundle.write(path, 'goggles-bridge/'+source['path'])
    print(target)


if __name__ == '__main__':
    main()
