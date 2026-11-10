"""Ship project source and third-party provenance beside the executable."""
from pathlib import Path
import subprocess
import zipfile

root = Path(__file__).resolve().parents[2]
paths = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                                cwd=root).decode().split('\0')
target = root/'dist/DJI-Goggles-Streamer-0.2.0-Source.zip'
with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in sorted(set(paths)):
        if name and (root/name).is_file():
            archive.write(root/name, 'g2-bridge-desktop/'+name)
print(target)
