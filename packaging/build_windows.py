"""Build the upstream window and isolated Windows worker with pinned native inputs.

Requires requirements-app.txt, PyInstaller, Inno Setup and the native FFmpeg recipe.
Fork builds pass --repository owner/repo to keep updates on their own channel.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from goggles_bridge import __version__
from goggles_bridge.app.backend import APP_NAME

INPUTS = {
    'innoextract-1.9-windows.zip': (
        'https://constexpr.org/innoextract/files/innoextract-1.9-windows.zip',
        '6989342c9b026a00a72a38f23b62a8e6a22cc5de69805cf47d68ac2fec993065'),
    'vdd-25.7.23.zip': (
        'https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/download/25.7.23/VirtualDisplayDriver-x86.Driver.Only.zip',
        'e24210692b442b39af763536330ce78b423f19342b7a7792c26de3944e418b3a'),
}


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare():
    vendor, cache = ROOT/'vendor', ROOT/'packaging/cache'
    cache.mkdir(parents=True, exist_ok=True)
    for name, (url, digest) in INPUTS.items():
        archive = cache/name
        if not archive.is_file():
            partial = archive.with_suffix('.partial')
            urllib.request.urlretrieve(url, partial)
            partial.replace(archive)
        if sha256(archive) != digest:
            raise ValueError(f'Build input checksum mismatch: {name}')
        target = vendor/('vdd' if name.startswith('vdd') else 'innoextract')
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                if entry.is_dir():
                    continue
                basename = Path(entry.filename).name
                if name.startswith('vdd') and basename.lower() not in ('mttvdd.inf', 'mttvdd.dll', 'mttvdd.cat'):
                    continue
                dest = target/(basename if name.startswith('vdd') else entry.filename)
                if not dest.resolve().is_relative_to(target.resolve()):
                    raise ValueError('Archive path escape')
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(bundle.read(entry))
    shutil.copyfile(ROOT/'docs/licenses/VDD-LICENSE.txt', vendor/'vdd/LICENSE.txt')
    recipe = ROOT/'packaging/windows/ffmpeg'
    manifest = json.loads((recipe/'manifest.json').read_text(encoding='utf-8'))
    for name, entry in manifest['release_binaries'].items():
        path = vendor/'ffmpeg'/name
        if not path.is_file() or sha256(path) != entry['sha256'] or path.stat().st_size != entry['bytes']:
            raise ValueError(f'Build the pinned native {name}; see packaging/windows/ffmpeg/README.md')
    for entry in (manifest['patch'], manifest['upstream']['source_archive']):
        if sha256(ROOT/entry['path']) != entry['sha256']:
            raise ValueError(f"Source checksum mismatch: {entry['path']}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', default='Ammaar-Alam/goggles-bridge')
    parser.add_argument('--iscc', default=shutil.which('iscc') or r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
        parser.error('Expected a GitHub owner/repository')
    manifest = prepare()
    dist, build, vendor = ROOT/'dist', ROOT/'build', ROOT/'vendor'
    app = dist/APP_NAME
    common = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--hidden-import', 'usb.backend.libusb0', '--hidden-import', 'usb.backend.libusb1',
        '--distpath', str(dist), '--workpath', str(build), '--specpath', str(build)]
    subprocess.run([*common, '--console', '--name', 'GogglesBridgeWorker',
        '--add-data', f'{vendor/"vdd"};vendor/vdd', str(ROOT/'scripts/goggles_bridge_worker.py')], check=True, cwd=ROOT)
    subprocess.run([*common, '--windowed', '--name', APP_NAME,
        '--icon', str(ROOT/'packaging/goggles-bridge.ico'),
        '--add-data', f'{ROOT/"goggles_bridge/app/ui"};goggles_bridge/app/ui',
        '--add-data', f'{vendor/"vdd"};vendor/vdd',
        '--add-data', f'{vendor/"innoextract"};vendor/innoextract',
        str(ROOT/'scripts/goggles_bridge_app.py')], check=True, cwd=ROOT)
    worker = dist/'GogglesBridgeWorker'
    shutil.copyfile(worker/'GogglesBridgeWorker.exe', app/'GogglesBridgeWorker.exe')
    shutil.copytree(worker/'_internal', app/'_internal', dirs_exist_ok=True)
    channel = app/'_internal/goggles_bridge/app/release-channel.json'
    channel.parent.mkdir(parents=True, exist_ok=True)
    channel.write_text(json.dumps(dict(repository=args.repository)), encoding='utf-8')
    ffmpeg = app/'ffmpeg'
    ffmpeg.mkdir(exist_ok=True)
    for name in manifest['release_binaries']:
        shutil.copyfile(vendor/'ffmpeg'/name, ffmpeg/name)
    source = ffmpeg/'source'
    shutil.copytree(ROOT/'packaging/windows/ffmpeg', source, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    archive = ROOT/manifest['upstream']['source_archive']['path']
    shutil.copyfile(archive, source/archive.name)
    shutil.copyfile(ROOT/'packaging/windows/ffmpeg/licenses/FFmpeg-COPYING.LGPLv2.1', ffmpeg/'LICENSE.txt')
    shutil.copyfile(ROOT/'LICENSE', app/'LICENSE.txt')
    notices = app/'licenses'
    notices.mkdir(exist_ok=True)
    for name in ('pywebview', 'pythonnet', 'clr-loader', 'PyUSB', 'PyInstaller'):
        package = importlib.metadata.distribution(name)
        for item in package.files or []:
            if any(part.lower().startswith(('license', 'copying')) for part in item.parts):
                src = Path(package.locate_file(item))
                if src.is_file():
                    dest = notices/name/Path(*item.parts[1:])
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dest)
    shutil.copyfile(Path(sys.base_prefix)/'LICENSE.txt', notices/'Python-LICENSE.txt')
    (app/'NOTICES.txt').write_text(
        f'Goggles Bridge {__version__}, GPL-3.0-only. Source: https://github.com/{args.repository}\n'
        'Modified FFmpeg n9.0.2 (LGPL 2.1-or-later): complete sources, patches and build recipe in ffmpeg/source.\n'
        'Signed MTT VDD 25.7.23 (MIT), innoextract 1.9 (zlib): licenses in _internal/vendor.\n'
        'Python, PyUSB, pywebview and pythonnet notices: licenses. DJI drivers are not redistributed.\n', encoding='utf-8')
    if Path(args.iscc).is_file():
        subprocess.run([args.iscc, f'/DVersion={__version__}', f'/DRepository={args.repository}',
                        str(ROOT/'packaging/installer.iss')], check=True)
        installer = dist/f'GogglesBridge-{__version__}-Setup.exe'
        print(f'Built {installer}\nSHA-256: {sha256(installer)}')
    else:
        print(f'Built {app}. Install Inno Setup 6 to build the installer')


if __name__ == '__main__':
    main()
