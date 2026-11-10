from pathlib import Path
import os
import sys

root = Path(SPECPATH).parents[1]
# Never collect unrelated tools' DLLs from the developer's PATH (notably ICU).
windows = Path(os.environ['SystemRoot'])
os.environ['PATH'] = os.pathsep.join([sys.base_prefix, str(windows/'System32'), str(windows)])
assets = [(str(root / 'desktop_app/assets'), 'desktop_app/assets'),
          (str(root / 'vendor'), 'vendor'),
          (str(root / 'LICENSE'), '.'),
          (str(root / 'docs/desktop/THIRD_PARTY.md'), '.'),
          (str(root / 'docs/desktop/USER_GUIDE.md'), '.')]

gui = Analysis([str(root / 'packaging/windows/gui_entry.py')], pathex=[str(root)],
    datas=assets, hiddenimports=[], excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
    'PySide6.QtQml', 'PySide6.QtQuick', 'tkinter', 'unittest'])
worker = Analysis([str(root / 'packaging/windows/worker_entry.py')], pathex=[str(root)],
    hiddenimports=['usb.backend.libusb0'], excludes=['PySide6', 'tkinter', 'unittest'])
# Supported Windows versions already supply their own system/API-set DLLs.
for analysis in (gui, worker):
    analysis.binaries = [entry for entry in analysis.binaries
                         if not Path(entry[1]).resolve().is_relative_to(windows.resolve())]
gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True,
    name='DJI Goggles Streamer', console=False, icon=str(root/'build/app.ico'),
    version=str(root/'packaging/windows/version.txt'), uac_admin=False, upx=False)
worker_exe = EXE(PYZ(worker.pure), worker.scripts, [], exclude_binaries=True,
    name='GogglesWorker', console=True, icon=str(root/'build/app.ico'),
    version=str(root/'packaging/windows/version.txt'), upx=False)
COLLECT(gui_exe, worker_exe, gui.binaries, gui.datas, worker.binaries, worker.datas,
    name='DJI Goggles Streamer', upx=False)
