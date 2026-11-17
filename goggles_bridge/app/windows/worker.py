"""Native DDA preflight and USB sending, isolated from the WebView process."""
from dataclasses import replace
from functools import partial
import json
from pathlib import Path
import sys
import threading
import time

from ...engine import BridgeEngine, BridgeSettings, check_encoder
from .dxgi import select_output
from .system import Cancelled
from .video import start_encoder, check_capture


class NativeBridgeEngine(BridgeEngine):
    def emit(self, event, **fields):
        if event in ('control_send', 'control_receive'):
            return
        if event == 'starting':
            fields.update(intra_refresh=False, native_backend=True)
        # EventWriter handles both sinks off the USB thread.
        self.on_event(dict(seconds=round(time.perf_counter()-self.log.started, 6), event=event, **fields))


def stream(request, stop, emit):
    values = dict(request['settings'])
    for key in ('dll', 'ffmpeg'):
        values[key] = Path(values[key]) if values[key] else None
    settings = BridgeSettings(**values)
    if settings.capture != 'ddagrab' or settings.encoder != 'nvenc':
        raise ValueError('Native capture requires Desktop Duplication and NVIDIA NVENC')
    if stop.is_set():
        return
    output = select_output(request['display_device'])
    settings = replace(settings, display_index=output['output'], capture_fps=settings.fps)
    capture = dict(output=output)
    error = check_encoder(settings, run=partial(check_capture, stop=stop, **capture))
    if error:
        raise RuntimeError(error)
    if stop.is_set():
        raise Cancelled()
    engine = NativeBridgeEngine(settings, Path(request['log']), stop_event=stop,
        gpu_priority_class=4, on_event=lambda row: emit(**row),
        process_factory=partial(start_encoder, **capture))
    engine.run()


def main():
    from .events import EventWriter
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    sys.stdin.reconfigure(encoding='utf-8')
    writer = None
    stop = threading.Event()

    def commands():
        for line in sys.stdin:
            try:
                if json.loads(line).get('command') == 'stop':
                    stop.set()
            except (ValueError, AttributeError):
                pass
        stop.set()

    try:
        request = json.loads(sys.stdin.readline())
        writer = EventWriter(sys.stdout, Path(request['log']))
        threading.Thread(target=commands, daemon=True).start()
        stream(request, stop, writer.emit)
        return 0
    except Cancelled:
        return 0
    except Exception as exc:
        if writer is not None:
            writer.emit('error', message=str(exc))
        else:
            print(json.dumps(dict(event='error', message=str(exc))), flush=True)
        return 1
    finally:
        if writer is not None:
            writer.close()
