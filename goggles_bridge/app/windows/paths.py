"""Paths shared by the window and its isolated Windows worker."""
import os
from pathlib import Path
import sys


def resources():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[3]))


def data_dir():
    return Path(os.environ.get('GOGGLES_BRIDGE_DATA_DIR') or
                Path(os.environ.get('LOCALAPPDATA', Path.home()), 'Goggles Bridge'))


def ffmpeg_path():
    bundled = Path(sys.executable).parent/'ffmpeg'/'ffmpeg.exe'
    return bundled if bundled.is_file() else Path(os.environ.get('GOGGLES_FFMPEG') or
                                                  resources()/'vendor'/'ffmpeg'/'ffmpeg.exe')


def stock_ffmpeg_path():
    """The upstream-tested build provides WGC; the native DDA build stays separate."""
    bundled = Path(sys.executable).parent/'ffmpeg-stock'/'ffmpeg.exe'
    return bundled if bundled.is_file() else Path(os.environ.get('GOGGLES_STOCK_FFMPEG') or
                                                  resources()/'vendor'/'ffmpeg-stock'/'ffmpeg.exe')


def worker_command():
    if getattr(sys, 'frozen', False):
        return str(Path(sys.executable).parent/'GogglesBridgeWorker.exe'), ['--windows-maintenance']
    return sys.executable, [str(resources()/'scripts'/'goggles_bridge_worker.py'), '--windows-maintenance']
