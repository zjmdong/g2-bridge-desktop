"""Regressions at the boundary between the full virtual display and native capture."""
from contextlib import contextmanager
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from goggles_bridge.app import backend, updates
from goggles_bridge.app.virtual_display import capture
from goggles_bridge.app.windows import worker, video, paths
from goggles_bridge.engine import BridgeSettings, encoder_command


class IntegrationTests(unittest.TestCase):
    def test_native_virtual_stream_holds_lease_and_releases_on_every_exit(self):
        for resolution, dimensions in [('720p', (1280, 720)), ('1080p', (1920, 1080))]:
            for failure in (None, RuntimeError('USB disconnected')):
                with self.subTest(resolution=resolution, failure=failure):
                    order = []
                    target = dict(device=r'\\.\DISPLAY7', hmonitor=77)
                    @contextmanager
                    def lease(width, height, fps, emit):
                        self.assertEqual((width, height), dimensions)
                        order.append('attached')
                        try:
                            yield target
                        finally:
                            order.append('released')
                    def run(settings, device, log, stop, emit, *, reconnect):
                        self.assertEqual(order, ['attached'])
                        self.assertEqual(device, target['device'])
                        self.assertEqual((settings.capture, settings.capture_fps), ('ddagrab', 100))
                        self.assertFalse(reconnect)
                        order.append('streamed')
                        if failure:
                            raise failure
                    runtime = Mock(run=run)
                    settings = BridgeSettings(None, Path('native.exe'), encoder='nvenc', capture='gfxcapture')
                    with patch.object(capture, 'lease', lease), \
                         patch.object(capture, 'select_source', return_value=target) as select:
                        args = (settings, dict(virtual_resolution=resolution), Path('unused'),
                                threading.Event(), Mock())
                        if failure:
                            with self.assertRaisesRegex(RuntimeError, 'USB disconnected'):
                                capture.run(*args, native_runtime=runtime)
                        else:
                            capture.run(*args, native_runtime=runtime)
                        select.assert_called_once_with(*dimensions, 100, expected=target)
                    self.assertEqual(order, ['attached', 'streamed', 'released'])

    def test_backend_selects_native_for_virtual_without_losing_physical_preferences(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(backend, 'WINDOWS', True), \
             patch.object(paths, 'native_ffmpeg_path', return_value=Path('native.exe')), \
             patch.object(backend, 'default_windows_encoder', return_value='nvenc'):
            app = backend.Desktop(settings_path=Path(folder)/'settings.json')
            self.assertEqual(app._options['capture'], 'ddagrab')
            app._settings(dict(capture='gfxcapture', encoder='nvenc', source='virtual'))
            settings = app._settings({})
            self.assertEqual(settings.ffmpeg, Path('native.exe'))
            with patch.object(capture, 'run') as run:
                app._run(settings, Path(folder)/'stream.jsonl')
                self.assertIs(run.call_args.kwargs['native_runtime'], app._native_runtime)
            app._settings(dict(source='display'))
            self.assertEqual(app._options['capture'], 'gfxcapture')
            self.assertEqual(app._selected_ffmpeg(), app._ffmpeg)
            app._settings(dict(source='virtual', encoder='amf'))
            self.assertEqual(app._selected_ffmpeg(), app._ffmpeg)

    def test_worker_propagates_disconnect_policy_to_engine(self):
        for reconnect in (False, True):
            request = dict(settings=dict(dll=None, ffmpeg='native.exe', capture='ddagrab', encoder='nvenc'),
                           display_device=r'\\.\DISPLAY7', log='unused', reconnect=reconnect)
            with patch.object(worker, 'select_output', return_value=dict(output=3)), \
                 patch.object(worker, 'check_encoder', return_value=None), \
                 patch.object(worker, 'NativeBridgeEngine') as engine:
                worker.stream(request, threading.Event(), Mock())
                self.assertEqual(engine.call_args.kwargs['reconnect'], reconnect)
                self.assertEqual(engine.call_args.args[0].display_index, 3)

    def test_native_command_preserves_quality_and_uses_bounded_delivery(self):
        for fps, vendor, delay in [(100, 0x10de, 6000), (90, 0x10de, 8000), (100, 0x8086, 8000)]:
            with self.subTest(fps=fps, vendor=vendor):
                settings = BridgeSettings(None, Path('native.exe'), capture='ddagrab', encoder='nvenc', fps=fps)
                output = dict(output=2, adapter=1, vendor_id=vendor, width=1280, height=720)
                command = video.compatible_command(encoder_command(settings), output=output)
                graph = command[command.index('-filter_complex')+1]
                self.assertIn('output_idx=2', graph)
                self.assertIn(f'delivery_delay_us={delay}', graph)
                self.assertIn('fresh_wait_us=2000', graph)
                self.assertEqual(command[command.index('-latest_frame')+1], '1')
                self.assertEqual(command[command.index('-qp_cb_offset')+1], '-4')
                if vendor == 0x10de:
                    self.assertIn('format=bgra:desktop_sdr=1,scale_d3d11', graph)
                else:
                    self.assertIn('hwdownload,format=bgra', graph)
                preflight = video.compatible_command(encoder_command(settings, frames=1), output=output)
                self.assertNotIn('-latest_frame', preflight)

    def test_personal_updates_reject_upstream_and_legacy_assets(self):
        self.assertIn('/zjmdong/g2-bridge-desktop/', updates.LATEST)
        for name, url in [
            ('GogglesBridge-9.0.0-Setup.exe', updates.DOWNLOADS+'9.0.0/GogglesBridge-9.0.0-Setup.exe'),
            ('GogglesBridgePersonal-9.0.0-Setup.exe',
             'https://github.com/Ammaar-Alam/goggles-bridge/releases/download/9.0.0/GogglesBridgePersonal-9.0.0-Setup.exe'),
        ]:
            release = dict(tag_name='9.0.0', assets=[dict(name=name, browser_download_url=url, digest='sha256:'+'a'*64)])
            with patch.object(updates.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(release).encode())):
                self.assertIsNone(updates.find('0.0.1'))
