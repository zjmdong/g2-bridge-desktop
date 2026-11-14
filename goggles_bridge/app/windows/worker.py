"""Bounded lifecycle for capture, NVENC and the unchanged goggles session protocol."""
from functools import partial
from dataclasses import replace
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

from ...engine import BridgeSettings, check_encoder


def stream(request, stop, emit):
    from .display_session import capture_target
    from .displays import capture_diagnostics
    from .dxgi import select_output
    from .stream_engine import DesktopBridgeEngine
    from .system import Cancelled
    from .video import start_encoder, check_capture, FRESH_WAIT_US, DELIVERY_DELAY_US
    settings = dict(request['settings'])
    for key in ('dll', 'ffmpeg'):
        settings[key] = Path(settings[key]) if settings[key] else None
    bridge = BridgeSettings(**settings)
    if not bridge.nvenc:
        raise ValueError('The Windows desktop requires NVIDIA NVENC encoding')
    app = request['options']
    virtual = app['source'] in ('virtual', 'extended')
    if virtual:
        bridge = replace(bridge, capture='ddagrab', capture_fps=bridge.fps, h264_profile='high',
                         adaptive_quant=False, low_latency=True)
    startup_only = virtual or app.get('keyframe_seconds', bridge.keyframe_seconds) == 0
    dimensions = (1280, 720) if app['resolution'] == '720p' else (1920, 1080)
    target_settings = SimpleNamespace(source=app['source'], display_device=app.get('display_device', ''),
                                     dimensions=dimensions, fps=bridge.fps)
    if stop.is_set():
        return
    with capture_target(target_settings, emit) as target:
        if stop.is_set():
            return
        native = bridge.capture == 'ddagrab'
        if native:
            output = select_output(target['device'])
            bridge = replace(bridge, capture_fps=bridge.fps, display_index=output['output'])
            capture = dict(output=output, dimensions=dimensions, startup_only=startup_only)
        else:
            # WGC addresses the selected HMONITOR directly, so an unavailable
            # DXGI mapping is diagnostic information, not a reason to capture another screen.
            try:
                output = select_output(target['device'])
            except RuntimeError:
                output = dict(device=target['device'])
            capture = dict(hmonitor=target.get('hmonitor'), dimensions=dimensions, startup_only=startup_only)
        route = capture_diagnostics(target, output)
        if not native:
            route.update(capture_gpu_path='windows_graphics_capture_nvenc', cross_adapter_transfer=None)
        refresh = target.get('refresh_rate')
        effective_hz = refresh.get('hz') if isinstance(refresh, dict) else refresh
        emit('display_path', **output, **route, source=app['source'], resolution=app['resolution'],
             effective_refresh=refresh, effective_hz=effective_hz or route['source_hz'],
             gpu_resident=output.get('vendor_id') == 0x10DE if native else None, encoder='h264_nvenc',
             capture=bridge.capture, fresh_wait_us=FRESH_WAIT_US if native else None,
             delivery_delay_us=DELIVERY_DELAY_US if native else None)
        emit('checking_capture')
        error = check_encoder(bridge, run=partial(check_capture, stop=stop, **capture))
        if error:
            raise RuntimeError(error)
        if stop.is_set():
            raise Cancelled()

        def encoder(command, **kwargs):
            return start_encoder(command, **capture, **kwargs)

        def on_event(row):
            if row['event'] == 'starting':
                row.update(adapter='windows-native-latest-v6' if native else 'windows-upstream-wgc', encoder='h264_nvenc',
                    resolution=f'{dimensions[0]}x{dimensions[1]}', capture_gpu=output.get('gpu_name'),
                    capture_adapter_luid=output.get('adapter_luid'), nvenc_async=native,
                    intra_refresh=not native and not startup_only,
                    bootstrap_idr_seconds=[0, 1, 2] if startup_only else None, periodic_idr=not startup_only,
                    raw_frame_queue='latest single slot' if native else 'upstream',
                    input_graph='direct' if native else 'upstream',
                    capture_fresh_wait_us=FRESH_WAIT_US if native else None,
                    delivery_delay_us=DELIVERY_DELAY_US if native else None,
                    native_delivery_pacing='capture_deadline' if native else None,
                    sdk_sender_mode='immediate' if bridge.low_latency else 'buffered')
            emit(**row)

        engine = DesktopBridgeEngine(bridge, Path(request['log']), stop_event=stop,
            on_event=on_event, process_factory=encoder)
        engine.run()


def main():
    if '--windows-maintenance' in sys.argv:
        from .virtual_driver import maintenance_main
        return maintenance_main(sys.argv[sys.argv.index('--windows-maintenance')+1:])
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    sys.stdin.reconfigure(encoding='utf-8')
    stop = threading.Event()
    from .events import EventWriter
    writer = EventWriter(sys.stdout)
    cleanup_errors = []

    def emit(event, **values):
        if event == 'display_cleanup_error':
            cleanup_errors.append(values.get('message') or 'The virtual display could not be released')
        writer.emit(event, **values)

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
        threading.Thread(target=commands, daemon=True).start()
        stream(request, stop, emit)
        return 0
    except Exception as exc:
        from .system import Cancelled
        if isinstance(exc, Cancelled) and not cleanup_errors:
            return 0
        emit('error', message=cleanup_errors[-1] if cleanup_errors else str(exc))
        return 1
    finally:
        writer.close()
