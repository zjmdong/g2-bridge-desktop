"""Ship project source and third-party provenance beside the executable."""
from pathlib import Path
import subprocess
import zipfile
import json
from ffmpeg_inputs import verify_ffmpeg_sources

root = Path(__file__).resolve().parents[2]
paths = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                                cwd=root).decode().split('\0')
target = root/'dist/DJI-Goggles-Streamer-0.2.4-Source.zip'
native = json.loads((root/'packaging/windows/ffmpeg/manifest.json').read_text(encoding='utf-8'))
verify_ffmpeg_sources(root, native)
partial = target.with_suffix('.partial.zip')
with zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in sorted(set(paths)):
        if name and (root/name).is_file():
            archive.write(root/name, 'g2-bridge-desktop/'+name)
    # The modified FFmpeg's complete upstream source accompanies its patches
    # and reproducible recipe, including in offline distributions.
    source = native['upstream']['source_archive']
    path = root/source['path']
    archive.write(path, 'g2-bridge-desktop/'+source['path'])
partial.replace(target)
print(target)
