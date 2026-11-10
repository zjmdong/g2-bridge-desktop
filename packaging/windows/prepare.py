"""Fetch only pinned, redistributable build inputs; DJI files are never bundled."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import shutil
import sys
import urllib.request
import zipfile
from ffmpeg_inputs import verify_ffmpeg_sources

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
INPUTS = {
    'innoextract-1.9-windows.zip': (
        'https://constexpr.org/innoextract/files/innoextract-1.9-windows.zip',
        '6989342c9b026a00a72a38f23b62a8e6a22cc5de69805cf47d68ac2fec993065'),
    'vdd-25.7.23.zip': (
        'https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/download/25.7.23/VirtualDisplayDriver-x86.Driver.Only.zip',
        'e24210692b442b39af763536330ce78b423f19342b7a7792c26de3944e418b3a'),
}


def prepare_ffmpeg():
    """Use only the locally reproducible, release-hashed capture build."""
    recipe = ROOT/'packaging/windows/ffmpeg'
    manifest = json.loads((recipe/'manifest.json').read_text(encoding='utf-8'))
    verify_ffmpeg_sources(ROOT, manifest)
    release = manifest.get('release_binaries', {})
    target = ROOT/'vendor/ffmpeg'
    if set(release) != {'ffmpeg.exe', 'ffprobe.exe'}:
        raise RuntimeError('Missing FFmpeg release hashes. Build the pinned sources; see packaging/windows/ffmpeg/README.md')
    for name, entry in release.items():
        path = target/name
        if (not path.is_file() or path.stat().st_size != entry['bytes'] or
                hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']):
            raise RuntimeError(f'FFmpeg release binary mismatch: {name}. Build and verify the pinned source recipe first.')
    # Ship complete source + local patches/build instructions with the program.
    # Do not silently restore the former stock FFmpeg and lose the native fixes.
    (target/'source').mkdir(parents=True, exist_ok=True)
    for path in recipe.iterdir():
        if path.is_file():
            shutil.copyfile(path, target/'source'/path.name)
    shutil.copytree(recipe/'licenses', target/'source/licenses', dirs_exist_ok=True)
    shutil.copyfile(recipe/'NOTICE.txt', target/'README.txt')
    shutil.copyfile(recipe/'licenses/FFmpeg-COPYING.LGPLv2.1', target/'LICENSE')


def main():
    prepare_ffmpeg()
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
        target = ROOT / 'vendor' / ('ffmpeg' if name.startswith('ffmpeg') else 'vdd' if name.startswith('vdd') else 'innoextract')
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
                elif name.startswith('vdd'):
                    if Path(member.filename).name.lower() not in ('mttvdd.inf','mttvdd.dll','mttvdd.cat'):
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
    shutil.copyfile(ROOT/'docs/desktop/VDD-LICENSE.txt', ROOT/'vendor/vdd/LICENSE.txt')
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
