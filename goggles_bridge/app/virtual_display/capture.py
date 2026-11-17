"""Bind the stock WGC graph to the leased display without changing encoder policy."""
from dataclasses import replace
import re
import subprocess

from ...engine import BridgeEngine, check_encoder
from .display_session import lease
from .displays import select_source
from .system import Cancelled, run_cancellable


def command_for_target(command, *, target):
    result = list(command)
    index = result.index('-i') + 1
    graph = result[index]
    if not graph.startswith('gfxcapture=') or type(target.get('hmonitor')) is not int or target['hmonitor'] <= 0:
        raise ValueError('The virtual display requires Windows Graphics Capture and a valid monitor handle')
    graph, count = re.subn(r'monitor_idx=-?\d+', f"hmonitor={target['hmonitor']}", graph)
    if count != 1:
        raise ValueError('The capture command has no unique monitor selector')
    # Keep the engine's 1080p GPU scaling, including for a 720p desktop: the
    # goggles display a native 720p bitstream in only part of their panel.
    result[index] = graph + ':display_border=0'
    return result


def run(settings, options, log, stop, on_event, *, engine_factory=BridgeEngine, check=check_encoder,
        native_runtime=None):
    """A stopped or disconnected stream releases only its leased display."""
    if stop.is_set():
        return
    dimensions = (1280, 720) if options['virtual_resolution'] == '720p' else (1920, 1080)
    settings = replace(settings, capture='ddagrab' if native_runtime else 'gfxcapture',
                       capture_fps=settings.fps if native_runtime else 1000)
    cleanup_errors = []

    def display_event(event, **values):
        if event == 'display_cleanup_error':
            cleanup_errors.append(values.get('message') or 'The virtual display could not be released')
        on_event(dict(event=event, **values))

    try:
        with lease(*dimensions, settings.fps, display_event) as target:
            if stop.is_set():
                return
            if native_runtime is not None:
                current = select_source(*dimensions, settings.fps, expected=target)
                native_runtime.run(settings, current['device'], log, stop, on_event, reconnect=False)
                return
            def adapt(command):
                current = select_source(*dimensions, settings.fps, expected=target)
                return command_for_target(command, target=current)

            def preflight(command, **kwargs):
                # A newly attached HMONITOR can be visible to user32 before WGC
                # accepts it. Re-resolve ownership on each short, bounded retry.
                for attempt in range(4):
                    result = run_cancellable(adapt(command), stop, **kwargs)
                    if (result.returncode == 0 or attempt == 3 or
                            'Failed to setup graphics capture for monitor (0x80070057)' not in result.stderr):
                        return result
                    if stop.wait(.25):
                        raise Cancelled()

            error = check(settings, run=preflight)
            if error:
                raise RuntimeError(error)
            if stop.is_set():
                return

            def encode(command, **kwargs):
                return subprocess.Popen(adapt(command), **kwargs)

            # Upstream reconnect loops retain the session; virtual streams instead
            # end on link loss so that the independent desktop can be released.
            engine_factory(settings, log, stop_event=stop, on_event=on_event,
                           reconnect=False, process_factory=encode).run()
    except Exception as exc:
        if cleanup_errors:
            raise RuntimeError(f'{str(exc) or "Stream cancelled"}; virtual display cleanup failed: {cleanup_errors[-1]}') from exc
        if not isinstance(exc, Cancelled):
            raise
