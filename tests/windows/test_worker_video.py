"""The real worker/adapter boundary with fake capture, encoder and USB session."""
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
import subprocess
import io
import json
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from goggles_bridge.engine import BridgeSettings, encoder_command
from goggles_bridge.app.windows import display_session, dxgi, stream_engine, video, worker


class WorkerVideoTests(unittest.TestCase):
    def request(self, capture='gfxcapture'):
        bridge = BridgeSettings(Path('unused.dll'), Path('unused.exe'), fps=100,
                                bitrate_mbps=32, capture=capture)
        return dict(settings=asdict(bridge), options=dict(source='extended', resolution='720p'),
                    log='unused.jsonl')

    def test_actual_dxgi_target_and_conversion_are_shared_by_preflight_and_stream(self):
        released, commands, events = [], [], []
        output = dict(device='fixture-display', adapter=2, output=3, hmonitor=123,
                      vendor_id=0x10de, adapter_luid='fixture', gpu_name='NVIDIA fixture')
        @contextmanager
        def capture(settings, emit):
            self.assertEqual((settings.fps, settings.dimensions), (100, (1280, 720)))
            try:
                yield dict(device='fixture-display', hz=100, refresh_rate=100.001)
            finally:
                released.append(True)

        class Engine:
            def __init__(self, bridge, log, **kwargs):
                self.bridge, self.kwargs = bridge, kwargs
                self.log = log
            def run(self):
                self.kwargs['on_event'](dict(event='starting'))
                commands.append(encoder_command(self.bridge))
                self.kwargs['process_factory'](commands[-1])

        with patch.object(display_session, 'capture_target', side_effect=capture), \
             patch.object(dxgi, 'select_output', return_value=output), \
             patch.object(stream_engine, 'DesktopBridgeEngine', Engine), \
             patch.object(video, 'run_cancellable', return_value=subprocess.CompletedProcess([], 0, '', '')) as check, \
             patch.object(video.subprocess, 'Popen', return_value=SimpleNamespace()) as start, \
             patch.object(video, 'configure_encoder_process', return_value={}):
            worker.stream(self.request(), threading.Event(), lambda event, **row: events.append(dict(event=event, **row)))
        self.assertEqual(released, [True])
        preflight, live = check.call_args.args[0], start.call_args.args[0]
        for command in (preflight, live):
            graph = command[command.index('-filter_complex')+1]
            self.assertIn('ddagrab=output_idx=3:framerate=100:', graph)
            self.assertIn('width=1280:height=720', graph)
            self.assertIn('d3d11va=cap:2', command)
            self.assertEqual(command.count('-force_key_frames'), 1)
            self.assertEqual(command[command.index('-force_key_frames')+1], '0,1,2')
            self.assertEqual(command[command.index('-c:v')+1], 'h264_nvenc')
        self.assertEqual(preflight[preflight.index('-filter_complex')+1], live[live.index('-filter_complex')+1])
        self.assertNotIn('-latest_frame', preflight)
        self.assertIn('-latest_frame', live)
        self.assertEqual([row for row in events if row['event']=='display_path'][0]['effective_hz'], 100.001)
        self.assertEqual([row for row in events if row['event']=='starting'][0]['capture_adapter_luid'], 'fixture')

    def test_capture_failure_releases_display_without_starting_engine(self):
        released = []
        @contextmanager
        def capture(*args):
            try:
                yield dict(device='fixture', hz=100)
            finally:
                released.append(True)
        with patch.object(display_session, 'capture_target', side_effect=capture), \
             patch.object(dxgi, 'select_output', return_value=dict(adapter=0, output=0)), \
             patch.object(worker, 'check_encoder', return_value='capture failure'), \
             patch.object(stream_engine, 'DesktopBridgeEngine') as engine:
            with self.assertRaisesRegex(RuntimeError, 'capture failure'):
                worker.stream(self.request(), threading.Event(), Mock())
        self.assertEqual(released, [True])
        engine.assert_not_called()

    def test_cancellation_before_start_never_creates_a_display(self):
        stop = threading.Event()
        stop.set()
        with patch.object(display_session, 'capture_target') as capture:
            worker.stream(self.request(), stop, Mock())
        capture.assert_not_called()

    def test_physical_sources_honour_advanced_values_in_preflight_and_live_encode(self):
        for method in ('ddagrab', 'gfxcapture'):
            commands = []
            bridge = BridgeSettings(None, Path('encoder.exe'), capture=method, fps=100,
                h264_profile='baseline', adaptive_quant=True, low_latency=False,
                keyframe_seconds=1, usb_write_size=2048)
            request = dict(settings=asdict(bridge), options=dict(source='display', resolution='720p',
                keyframe_seconds=1), log='unused.jsonl')
            @contextmanager
            def capture(*args):
                yield dict(device='physical', hmonitor=987, hz=100)

            class Engine:
                def __init__(self, settings, log, **kwargs):
                    self.settings, self.kwargs = settings, kwargs
                def run(self):
                    self.kwargs['on_event'](dict(event='starting'))
                    self.kwargs['process_factory'](encoder_command(self.settings))
                    commands.append(self.settings)

            with patch.object(display_session, 'capture_target', capture), \
                 patch.object(dxgi, 'select_output', return_value=dict(adapter=1, output=2, vendor_id=0x10de)), \
                 patch.object(stream_engine, 'DesktopBridgeEngine', Engine), \
                 patch.object(video, 'run_cancellable', return_value=subprocess.CompletedProcess([], 0, '', '')) as check, \
                 patch.object(video.subprocess, 'Popen', return_value=SimpleNamespace()) as start, \
                 patch.object(video, 'configure_encoder_process', return_value={}):
                worker.stream(request, threading.Event(), Mock())
            self.assertEqual(commands[0].capture, method)
            self.assertFalse(commands[0].low_latency)
            self.assertEqual(commands[0].usb_write_size, 2048)
            for command in (check.call_args.args[0], start.call_args.args[0]):
                self.assertEqual(command[command.index('-profile:v')+1], 'baseline')
                self.assertEqual(command[command.index('-spatial-aq')+1], '1')
                self.assertEqual(command[command.index('-g')+1], '100')
                self.assertNotEqual(command[command.index('-force_key_frames')+1], '0,1,2')
                if method == 'gfxcapture':
                    self.assertIn('hmonitor=987', command[command.index('-i')+1])
                    self.assertNotIn('-async_encode', command)
                else:
                    self.assertEqual(command[command.index('-coder')+1], 'cavlc')

    def test_stop_does_not_hide_real_worker_or_cleanup_failures(self):
        from goggles_bridge.app.windows import events
        from goggles_bridge.app.windows.system import Cancelled

        class Pipe(io.StringIO):
            def reconfigure(self, **kwargs):
                pass

        for kind, expected in (('cancelled', 0), ('error_after_stop', 1), ('cleanup_after_cancel', 1)):
            emitted = []
            journal = SimpleNamespace(emit=lambda event, **row: emitted.append(dict(event=event, **row)), close=lambda: None)
            def run(request, stop, emit):
                stop.set()
                if kind == 'cleanup_after_cancel':
                    emit('display_cleanup_error', message='cleanup failed')
                raise RuntimeError('encoder failed') if kind == 'error_after_stop' else Cancelled()
            with patch.object(worker.sys, 'argv', ['worker']), \
                 patch.object(worker.sys, 'stdin', Pipe(json.dumps({})+'\n')), \
                 patch.object(worker.sys, 'stdout', Pipe()), \
                 patch.object(events, 'EventWriter', return_value=journal), \
                 patch.object(worker, 'stream', side_effect=run):
                self.assertEqual(worker.main(), expected)
            if expected:
                self.assertTrue(any(row['event'] == 'error' for row in emitted))
            if kind == 'cleanup_after_cancel':
                self.assertEqual(emitted[-1]['message'], 'cleanup failed')


if __name__ == '__main__':
    unittest.main()
