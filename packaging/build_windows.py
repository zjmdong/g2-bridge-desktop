"""Build the Windows app folder in dist/ and, when Inno Setup is installed, the installer.

Needs the packages in requirements-app.txt plus PyInstaller. Run from any folder.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from goggles_bridge import __version__
from goggles_bridge.app.backend import APP_NAME

# the build the bridge is tested with; its gfxcapture repeats frames on a still screen, release 9.0 does not
FFMPEG = 'ffmpeg-2026-11-05-git-0893feba65-essentials_build'
FFMPEG_URL = f'https://github.com/GyanD/codexffmpeg/releases/download/2026-11-05-git-0893feba65/{FFMPEG}.zip'
FFMPEG_SHA256 = '763ca14d6896b4d8aabde8ff90be4f1428f8a21bd43e438a371be6d7ebf891a6'
NOTICES = f'''{APP_NAME} is licensed under the GNU General Public License v3.0. See LICENSE.txt.
Source code: https://github.com/Ammaar-Alam/goggles-bridge

This app includes:
- FFmpeg ({FFMPEG}), built by Gyan Doshi and licensed under the GPL v3.
  See ffmpeg/LICENSE.txt. Source: https://github.com/FFmpeg/FFmpeg/commit/0893feba65
- PyUSB, pywebview, pythonnet, and Python, under their own licenses.
'''


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def prepare_native(app):
    """Include an optional verified build, worker, and complete corresponding sources."""
    from verify_native import verify_inputs
    manifest = verify_inputs()
    native = app/'ffmpeg-native'
    native.mkdir(exist_ok=True)
    shutil.copyfile(ROOT/'vendor/ffmpeg/ffmpeg.exe', native/'ffmpeg.exe')
    source_root = native/'source'
    shutil.copytree(ROOT/'packaging/windows/ffmpeg', source_root/'packaging/windows/ffmpeg', dirs_exist_ok=True)
    archive = ROOT/manifest['upstream']['source_archive']['path']
    target = source_root/manifest['upstream']['source_archive']['path']
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(archive, target)
    shutil.copyfile(ROOT/'packaging/windows/ffmpeg/licenses/FFmpeg-COPYING.LGPLv2.1', native/'LICENSE.txt')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--console',
                    '--onefile', '--name', 'GogglesBridgeWorker',
                    '--hidden-import', 'usb.backend.libusb0', '--hidden-import', 'usb.backend.libusb1',
                    '--distpath', str(app), '--workpath', str(ROOT/'build/native-worker'),
                    '--specpath', str(ROOT/'build/native-worker'),
                    str(ROOT/'scripts/goggles_bridge_worker.py')], check=True, cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', action='store_true',
                        help='include the manifest-verified optional native DDA backend')
    args = parser.parse_args()
    if args.native:
        # Fail before any build work; the stock build never needs these inputs.
        from verify_native import verify_inputs
        verify_inputs()
    dist, cache = ROOT/'dist', ROOT/'packaging'/'cache'
    app = dist/APP_NAME
    archive = cache/f'{FFMPEG}.zip'
    if not archive.is_file():
        cache.mkdir(parents=True, exist_ok=True)
        print(f'Downloading {FFMPEG_URL}', flush=True)
        urllib.request.urlretrieve(FFMPEG_URL, archive)
    if sha256(archive) != FFMPEG_SHA256:
        raise SystemExit(f'{archive} does not match the pinned FFmpeg checksum. Delete it and build again')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--name', APP_NAME,
                    '--icon', str(ROOT/'packaging'/'goggles-bridge.ico'),
                    '--add-data', f"{ROOT/'goggles_bridge'/'app'/'ui'};goggles_bridge/app/ui",
                    # PyUSB loads its backends by name at run time
                    '--hidden-import', 'usb.backend.libusb0', '--hidden-import', 'usb.backend.libusb1',
                    '--distpath', str(dist), '--workpath', str(ROOT/'build'), '--specpath', str(ROOT/'build'),
                    str(ROOT/'scripts'/'goggles_bridge_app.py')], check=True, cwd=ROOT)
    (app/'ffmpeg').mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for member, target in ((f'{FFMPEG}/bin/ffmpeg.exe', 'ffmpeg.exe'), (f'{FFMPEG}/LICENSE', 'LICENSE.txt')):
            (app/'ffmpeg'/target).write_bytes(bundle.read(member))
    shutil.copyfile(ROOT/'LICENSE', app/'LICENSE.txt')
    (app/'NOTICES.txt').write_text(NOTICES, encoding='utf-8')
    if args.native:
        prepare_native(app)
        with (app/'NOTICES.txt').open('a', encoding='utf-8') as notices:
            notices.write('\nOptional native FFmpeg n9.0.2 (LGPL 2.1-or-later): ffmpeg-native/LICENSE.txt.\n'
                          'Complete corresponding source, patch, and pinned recipe: ffmpeg-native/source.\n')
    # Always ship the mode, so installing stock over a native build disables
    # stale native files that Inno Setup intentionally leaves in place.
    (app/'native-backend.json').write_text(json.dumps(dict(schema=1, enabled=args.native)), encoding='utf-8')
    compiler = shutil.which('iscc') or r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
    if not Path(compiler).is_file():
        print(f'Built {app}. Install Inno Setup 6 to build the installer')
        return
    subprocess.run([compiler, f'/DVersion={__version__}', str(ROOT/'packaging'/'installer.iss')], check=True)
    installer = dist/f'GogglesBridge-{__version__}-Setup.exe'
    print(f'Built {installer}\nSHA-256: {sha256(installer)}')


if __name__ == '__main__':
    main()
