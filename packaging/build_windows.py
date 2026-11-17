"""Build the Windows app folder and installers in dist/.

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
VDD_URL = 'https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/download/25.7.23/VirtualDisplayDriver-x86.Driver.Only.zip'
VDD_SHA256 = 'e24210692b442b39af763536330ce78b423f19342b7a7792c26de3944e418b3a'
NOTICES = f'''{APP_NAME} is licensed under the GNU General Public License v3.0. See LICENSE.txt.
Source code: https://github.com/zjmdong/g2-bridge-desktop

This app includes:
- FFmpeg ({FFMPEG}), built by Gyan Doshi and licensed under the GPL v3.
  See ffmpeg/LICENSE.txt. Source: https://github.com/FFmpeg/FFmpeg/commit/0893feba65
- PyUSB, pywebview, pythonnet, and Python, under their own licenses.
- Virtual Display Driver 25.7.23 (MIT), signed by SignPath Foundation.
  See _internal/vendor/vdd/LICENSE.txt. Source: https://github.com/VirtualDrivers/Virtual-Display-Driver/tree/25.7.23
'''


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def prepare_vdd():
    """Extract only the pinned signed driver payload; do not modify the driver."""
    from goggles_bridge.app.virtual_display.virtual_driver import HASHES
    cache, target = ROOT/'packaging/cache', ROOT/'vendor/vdd'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache/'vdd-25.7.23.zip'
    if not archive.is_file():
        partial = archive.with_suffix('.partial')
        urllib.request.urlretrieve(VDD_URL, partial)
        if sha256(partial) != VDD_SHA256:
            raise ValueError('Virtual display driver archive checksum mismatch')
        partial.replace(archive)
    if sha256(archive) != VDD_SHA256:
        raise ValueError('Virtual display driver archive checksum mismatch')
    with zipfile.ZipFile(archive) as bundle:
        payload = {}
        for name in HASHES:
            members = [item for item in bundle.namelist() if Path(item).name.casefold() == name.casefold()]
            if len(members) != 1:
                raise ValueError(f'Expected exactly one driver file: {name}')
            content = bundle.read(members[0])
            if hashlib.sha256(content).hexdigest() != HASHES[name]:
                raise ValueError(f'Virtual display driver file checksum mismatch: {name}')
            payload[name] = content
    target.mkdir(parents=True, exist_ok=True)
    for name, content in payload.items():
        (target/name).write_bytes(content)
    shutil.copyfile(ROOT/'goggles_bridge/app/virtual_display/LICENSE.txt', target/'LICENSE.txt')
    return target


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
    try:
        from webview import create_window, start
        import usb.core
    except ImportError as exc:
        raise SystemExit('Missing app dependencies. Run this Python with -m pip install -r requirements-app.txt before building.') from exc
    if not callable(create_window) or not callable(start):
        raise SystemExit('The webview module is not pywebview. Repair the build environment before building.')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', action='store_true',
                        help='include the manifest-verified optional native DDA backend')
    args = parser.parse_args()
    if args.native:
        # Fail before any build work; the stock build never needs these inputs.
        from verify_native import verify_inputs
        verify_inputs()
    vdd = prepare_vdd()
    compiler = shutil.which('iscc') or r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
    if not Path(compiler).is_file():
        raise SystemExit('Install Inno Setup 6 and add ISCC.exe to PATH to build the driver component and app.')
    dist, cache = ROOT/'dist', ROOT/'packaging'/'cache'
    app = dist/APP_NAME
    archive = cache/f'{FFMPEG}.zip'
    if not archive.is_file():
        cache.mkdir(parents=True, exist_ok=True)
        print(f'Downloading {FFMPEG_URL}', flush=True)
        urllib.request.urlretrieve(FFMPEG_URL, archive)
    if sha256(archive) != FFMPEG_SHA256:
        raise SystemExit(f'{archive} does not match the pinned FFmpeg checksum. Delete it and build again')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--console',
                    '--name', 'GogglesBridgeDisplaySetup',
                    '--distpath', str(dist), '--workpath', str(ROOT/'build/display-setup'),
                    '--specpath', str(ROOT/'build'), str(ROOT/'scripts/goggles_bridge_display_setup.py')],
                   check=True, cwd=ROOT)
    subprocess.run([compiler, f'/DVersion={__version__}', str(ROOT/'packaging'/'display_installer.iss')], check=True)
    generated = ROOT/'build/app-constants'
    generated.mkdir(parents=True, exist_ok=True)
    (generated/'_goggles_driver_build.py').write_text(
        f'INSTALLER_SHA256 = {sha256(dist/"GogglesBridgeDisplay-Setup.exe")!r}\n', encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--name', APP_NAME,
                    '--icon', str(ROOT/'packaging'/'goggles-bridge.ico'),
                    '--add-data', f"{ROOT/'goggles_bridge'/'app'/'ui'};goggles_bridge/app/ui",
                    '--add-data', f'{vdd/"LICENSE.txt"};vendor/vdd',
                    '--paths', str(generated), '--hidden-import', '_goggles_driver_build',
                    # PyUSB loads its backends by name at run time
                    '--hidden-import', 'usb.backend.libusb0', '--hidden-import', 'usb.backend.libusb1',
                    '--distpath', str(dist), '--workpath', str(ROOT/'build'), '--specpath', str(ROOT/'build'),
                    str(ROOT/'scripts'/'goggles_bridge_app.py')], check=True, cwd=ROOT)
    shutil.copyfile(dist/'GogglesBridgeDisplay-Setup.exe', app/'GogglesBridgeDisplay-Setup.exe')
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
    subprocess.run([compiler, f'/DVersion={__version__}', str(ROOT/'packaging'/'installer.iss')], check=True)
    installer = dist/f'GogglesBridgePersonal-{__version__}-Setup.exe'
    print(f'Built {installer}\nSHA-256: {sha256(installer)}')


if __name__ == '__main__':
    main()
