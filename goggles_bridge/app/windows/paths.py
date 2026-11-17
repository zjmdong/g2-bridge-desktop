"""Explicit opt-in paths for the native desktop backend."""
import os
import json
from pathlib import Path
import sys


def native_ffmpeg_path():
    """Return an explicitly configured/bundled native build, never the stock one."""
    override = os.environ.get('GOGGLES_NATIVE_FFMPEG')
    if override:
        return Path(override)
    if getattr(sys, 'frozen', False):
        root = Path(sys.executable).parent
        try:
            mode = json.loads((root/'native-backend.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        # The installer always overwrites this marker, including stock builds.
        # Stale optional payloads from an older install must not enable capture.
        if isinstance(mode, dict) and mode.get('schema') == 1 and mode.get('enabled') is True:
            return root/'ffmpeg-native'/'ffmpeg.exe'
    return None


def worker_command():
    if getattr(sys, 'frozen', False):
        return str(Path(sys.executable).parent/'GogglesBridgeWorker.exe'), []
    root = Path(__file__).resolve().parents[3]
    return sys.executable, [str(root/'scripts'/'goggles_bridge_worker.py')]
