"""Resolve bundled, development and per-user resources without changing the SDK."""
from pathlib import Path
import os
import sys


def resources():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))


def data_dir():
    root = os.environ.get('GOGGLES_STREAMER_DATA_DIR')
    path = Path(root) if root else Path(os.environ.get('LOCALAPPDATA', Path.home()), 'DJI Goggles Streamer')
    path.mkdir(parents=True, exist_ok=True)
    return path


def ffmpeg_path():
    # Only the explicitly bundled build is used; PATH does not silently select a different encoder.
    return resources() / 'vendor' / 'ffmpeg' / 'ffmpeg.exe'


def worker_command():
    if getattr(sys, 'frozen', False):
        return str(Path(sys.executable).parent / 'GogglesWorker.exe'), []
    return sys.executable, ['-m', 'desktop_app', '--worker']
