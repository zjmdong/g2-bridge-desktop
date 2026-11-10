"""Fetch only pinned, redistributable build inputs; DJI files are never bundled."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import shutil
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
INPUTS = {
    'ffmpeg-9.0.2.zip': (
        'https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip',
        '60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba'),
    'innoextract-1.9-windows.zip': (
        'https://constexpr.org/innoextract/files/innoextract-1.9-windows.zip',
        '6989342c9b026a00a72a38f23b62a8e6a22cc5de69805cf47d68ac2fec993065'),
}


def main():
    downloads = ROOT / 'work/downloads'
    downloads.mkdir(parents=True, exist_ok=True)
    for name, (url, checksum) in INPUTS.items():
        archive = downloads / name
        if not archive.exists():
            partial = archive.with_suffix('.partial')
            print(f'Downloading {name}', flush=True)
            with urllib.request.urlopen(url, timeout=60) as response, partial.open('wb') as output:
                shutil.copyfileobj(response, output)
            partial.replace(archive)
        with archive.open('rb') as handle:
            if hashlib.file_digest(handle, 'sha256').hexdigest() != checksum:
                raise ValueError(f'Checksum mismatch: {name}')
        target = ROOT / 'vendor' / ('ffmpeg' if name.startswith('ffmpeg') else 'innoextract')
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                if member.is_dir():
                    continue
                if name.startswith('ffmpeg'):
                    if not (member.filename.endswith('/bin/ffmpeg.exe') or
                            Path(member.filename).name.lower() in ('license', 'readme.txt')):
                        continue
                    dest = target / Path(member.filename).name
                else:
                    dest = target / member.filename
                if not dest.resolve().is_relative_to(target.resolve()):
                    raise ValueError('Archive path escape')
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(bundle.read(member))

    # Preserve the wheel distributors' notices, including Qt/Python binding licenses.
    notices = ROOT / 'vendor/licenses'
    notices.mkdir(exist_ok=True)
    for name in ('PySide6', 'PySide6_Essentials', 'shiboken6', 'PyUSB', 'PyInstaller'):
        dist = importlib.metadata.distribution(name)
        for item in dist.files or []:
            if any(part.lower().startswith(('license', 'copying')) for part in item.parts):
                src = Path(dist.locate_file(item))
                if src.is_file():
                    dest = notices / name / Path(*item.parts[1:])
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dest)
    shutil.copyfile(Path(sys.base_prefix) / 'LICENSE.txt', notices / 'Python-LICENSE.txt')
    shutil.copyfile(ROOT/'LICENSE', notices/'GPL-3.0.txt')
    (notices / 'build-inputs.json').write_text(json.dumps(INPUTS, indent=2)+'\n', encoding='utf-8')

    from PySide6.QtWidgets import QApplication
    from desktop_app.ui import app_icon
    app = QApplication([])
    icon_path = ROOT / 'build/app.ico'
    icon_path.parent.mkdir(exist_ok=True)
    if not app_icon().pixmap(128, 128).save(str(icon_path), 'ICO'):
        raise RuntimeError('Unable to create app icon')
    print('Pinned dependencies, notices and application icon ready.')


if __name__ == '__main__':
    main()
