"""Verify the local native executable and its corresponding build inputs."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify_inputs():
    manifest = json.loads((ROOT/'packaging/windows/ffmpeg/manifest.json').read_text(encoding='utf-8'))
    records = [manifest['upstream']['source_archive'], manifest['patch'],
               manifest['recipe'], dict(path='vendor/ffmpeg/ffmpeg.exe', **manifest['binary'])]
    for record in records:
        path = ROOT/record['path']
        if (path.stat().st_size != record['bytes']
                or hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']):
            raise ValueError(f'Native input mismatch: {record["path"]}; rebuild with the pinned recipe')
    return manifest


if __name__ == '__main__':
    verify_inputs()
    print('Native executable and source inputs verified')
