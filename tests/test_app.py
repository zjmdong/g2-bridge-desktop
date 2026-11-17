import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

from goggles_bridge.app import backend, updates
from goggles_bridge.app.backend import Desktop, describe, problem_code
from goggles_bridge.session import SIMULATOR_SILENT

READY = dict(driver=dict(needed=True, ok=True), screen=dict(needed=False, ok=True), ffmpeg=dict(needed=True, ok=True),
             attached=True)


class FakeEngine:
    """Replay engine events, then hold the stream open until the app stops it."""
    events = ()

    def __init__(self, settings, log, *, on_event, stop_event):
        self.settings, self.on_event, self.stop_event = settings, on_event, stop_event

    def run(self):
        for event in self.events:
            self.on_event(dict(event))
        self.stop_event.wait(5)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.settings_path = Path(self.folder.name)/'settings.json'
        # two displays on every test host, so a saved second display stays valid
        two = [dict(index=i, name=f'Display {i+1}', x=1920*i, y=0, width=1920, height=1080, hz=60, primary=not i) for i in range(2)]
        for name, value in (('data_dir', lambda: Path(self.folder.name)), ('goggles_attached', lambda: True),
                            ('list_displays', lambda: two), ('screen_access', lambda request=False: True)):
            patcher = mock.patch.object(backend, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def app(self, events=(), check=lambda settings: None, checks=READY):
        engine = type('Engine', (FakeEngine,), dict(events=events))
        app = Desktop(settings_path=self.settings_path, engine_factory=engine, check=check, identify=lambda: None)
        app._preflight = lambda: checks
        self.addCleanup(lambda: (app.stop(), app._thread and app._thread.join(5)))
        return app

    def wait_for(self, app, phase):
        for _ in range(200):
            if app.snapshot()['phase'] == phase:
                return app.snapshot()
            threading.Event().wait(.01)
        self.fail(f"phase stayed {app.snapshot()['phase']}, expected {phase}")

    def test_stream_events_become_window_state(self):
        events = (dict(event='connected', attempt=1),
                  dict(event='ready', model='DJI Goggles 2', identity='E3T ZV900 AC Dec 24 2024|12:34:04'),
                  dict(event='streaming', encoder_pid=1, gpu_realtime=True),
                  dict(event='stats', seconds=1.0, frames=100, bytes=1, queued_frames=0, fps=99.5, queue_ms_p95=.05,
                       send_ms_p95=.7, frame_bytes_max=43000, oversize_frames=0),
                  dict(event='oversize_frame', bytes=60000, limit=56000))
        app = self.app(events)
        self.assertEqual(app.snapshot()['phase'], 'idle')
        app.start()
        state = self.wait_for(app, 'streaming')
        self.assertEqual(state['device'], describe('DJI Goggles 2', 'E3T ZV900 AC Dec 24 2024|12:34:04'))
        self.assertEqual(state['stats'], dict(fps=99.5, send_ms_p95=.7, frame_bytes_max=43000))
        self.assertEqual(state['oversize'], 1)
        json.dumps(state)
        app.stop()
        self.assertIsNone(self.wait_for(app, 'idle')['stats'])

    def test_goggles_are_identified_and_untested_firmware_is_flagged(self):
        tested = describe('DJI Goggles 2', 'E3T ZV900 AC Aug 11 2026|07:21:27')
        self.assertEqual((tested['build'], tested['version'], tested['tested']), ('Aug 11 2026', '01.14.00.00', True))
        self.assertEqual(describe('DJI Goggles 2', 'E3T ZV900 AC Feb 26 2025|12:39:57')['version'], '01.12.00.00')
        other = describe('DJI Goggles 2', 'E3T ZV900 AC Jun 2 2026|09:00:00')
        self.assertEqual((other['version'], other['tested'], other['tested_versions']),
                         (None, False, ['01.11.00.00', '01.12.00.00', '01.14.00.00']))
        # no Integra build date is recorded, so its firmware is not judged
        self.assertIsNone(describe('DJI Goggles Integra', 'E3T ZV901 AC Jan 5 2025|10:00:00')['tested'])
        app = self.app()
        self.assertIsNone(app.snapshot()['device'])
        app._identify = lambda: ('DJI Goggles 2', 'E3T ZV900 AC Dec 24 2024|12:34:04')
        app._look()
        self.assertEqual(app.snapshot()['device']['version'], '01.11.00.00')
        app._identify = lambda: None
        app._look()
        self.assertIsNone(app.snapshot()['device'])

    def test_reconnected_goggles_replace_the_streamed_identity(self):
        present = Path(self.folder.name)/'present'
        present.touch()
        plugged, found = [True], [('DJI Goggles 2', 'E3T ZV900 AC Jun 2 2026|09:00:00')]
        for name, value in (('find_dll', lambda path=None: present), ('goggles_attached', lambda: plugged[0])):
            patcher = mock.patch.object(backend, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        ready = dict(event='ready', model='DJI Goggles 2', identity='E3T ZV900 AC Dec 24 2024|12:34:04')
        engine = type('Engine', (FakeEngine,), dict(events=(ready, dict(event='streaming', encoder_pid=1, gpu_realtime=True))))
        app = Desktop(settings_path=self.settings_path, engine_factory=engine, check=lambda settings: None,
                      identify=lambda: found[0])
        app._ffmpeg = present
        self.addCleanup(lambda: (app.stop(), app._thread and app._thread.join(5)))
        app.start()
        self.assertEqual(self.wait_for(app, 'streaming')['device']['version'], '01.11.00.00')
        app.stop()
        self.wait_for(app, 'idle')
        app._thread.join(5)
        plugged[0], app._checks = False, (0, None)
        self.assertIsNone(app.snapshot()['device'])
        plugged[0], app._checks = True, (0, None)
        app.snapshot()
        app._probe.join(5)
        device = app.snapshot()['device']
        self.assertEqual((device['build'], device['tested']), ('Jun 2 2026', False))

    @unittest.skipUnless(sys.platform == 'win32', 'the WebView2 Runtime is a Windows component')
    def test_missing_webview2_is_detected(self):
        import winreg
        with mock.patch.object(winreg, 'OpenKey', side_effect=OSError):
            self.assertFalse(backend.has_webview2())
        self.assertTrue(backend.has_webview2())

    def test_problems_name_their_recovery(self):
        app = self.app((dict(event='waiting', message=SIMULATOR_SILENT),))
        app.start()
        self.assertEqual(self.wait_for(app, 'waiting')['problem']['code'], 'virtual_flight')
        for message, code in (('Waiting for powered goggles in Virtual Flight mode', 'unplugged'),
                              ('Goggles rejected 0b/1a: d6', 'rejected'), ('USB link is full-speed (12 Mbps)', 'slow_link'),
                              ('Encoded frames repeatedly exceed the size limit. Lower the bitrate', 'oversize'),
                              ('something new', 'other')):
            self.assertEqual(problem_code(message), code)

    def test_failed_capture_check_and_missing_tools_stop_before_usb(self):
        app = self.app(check=lambda settings: 'FFmpeg test encode failed.\n  detail')
        app.start()
        state = self.wait_for(app, 'error')
        self.assertEqual(state['problem'], dict(code='encoder', message='FFmpeg test encode failed.\n  detail'))
        for name in ('driver', 'screen'):
            app = self.app(checks=dict(READY, **{name: dict(needed=True, ok=False)}))
            self.assertEqual(app.start(), dict(ok=False))
            self.assertEqual(app.snapshot()['problem']['code'], name)
            self.assertIsNone(app._thread)

    def test_options_follow_the_engine_rules_and_persist(self):
        app = self.app()
        # Windows capture, so the bitrate rules are the same on every test host
        self.assertEqual(app.set_options(dict(capture='gfxcapture')), dict(ok=True))
        self.assertIn('at most 24 Mbps', app.set_options(dict(fps=60, bitrate_mbps=40))['error'])
        self.assertEqual(app.snapshot()['options']['fps'], 100)
        self.assertEqual(app.set_options(dict(fps=60, bitrate_mbps=None, display_index=1, unknown=5)), dict(ok=True))
        rates = app.snapshot()['choices']['bitrates']
        self.assertEqual(rates['60'], dict(allowed=[8, 10, 12, 16, 20, 24], auto=24))
        self.assertEqual(rates['100']['auto'], 32)
        self.assertFalse(app.snapshot()['onboarded'])
        app.finish_setup()
        again = self.app()
        self.assertEqual((again._options['fps'], again._options['display_index']), (60, 1))
        self.assertTrue(again.snapshot()['onboarded'])
        self.assertNotIn('unknown', again._options)
        one = [dict(index=0, name='Display 1', x=0, y=0, width=1920, height=1080, hz=60, primary=True)]
        with mock.patch.object(backend, 'list_displays', lambda: one):
            self.assertEqual(again.snapshot()['options']['display_index'], 0)
        self.settings_path.write_text('{"fps": 61}', encoding='utf-8')
        self.assertEqual(self.app()._options['fps'], 100)

    @unittest.skipIf(sys.platform == 'darwin', 'Windows encoders')
    def test_amd_machines_default_to_amf(self):
        for detected, capture in (('amf', 'ddagrab'), ('nvenc', 'gfxcapture')):
            with mock.patch('goggles_bridge.engine.default_windows_encoder', return_value=detected):
                options = backend.default_options()
                # the saved option stays automatic, and the engine resolves it on every start
                self.assertEqual((options['encoder'], options['capture']), (None, capture))
                self.settings_path.unlink(missing_ok=True)
                app = self.app()
                self.assertEqual(app._settings({}).encoder, detected)

    def test_update_runs_the_verified_installer_and_closes_the_app(self):
        installer = b'installer'
        url = updates.DOWNLOADS+f'0.2.0/GogglesBridgePersonal-0.2.0{updates.ASSET}'
        asset = dict(name=f'GogglesBridgePersonal-0.2.0{updates.ASSET}', browser_download_url=url,
                     digest='sha256:'+hashlib.sha256(installer).hexdigest())

        def site(release):
            return lambda request, timeout: io.BytesIO(
                installer if request == url else json.dumps(release).encode())

        release = dict(tag_name='0.2.0', assets=[asset])
        self.assertTrue(updates.newer('0.10.0', '0.9.0'))
        # current copies, installers without a published hash, and other download sites are not updates
        for current, changed in (('0.2.0', {}), ('0.1.0', dict(digest=None)),
                                 ('0.1.0', dict(browser_download_url='https://example.com/Setup.exe'))):
            with mock.patch.object(updates.urllib.request, 'urlopen', site(dict(release, assets=[{**asset, **changed}]))):
                self.assertIsNone(updates.find(current))

        app, started, closed = self.app(), [], []
        app._quit = lambda: closed.append(True)
        # the release is newer whatever version the code has
        with mock.patch.object(updates.urllib.request, 'urlopen', site(release)), \
                mock.patch.object(backend, '__version__', '0.1.0'), \
                mock.patch.object(backend.subprocess, 'Popen', lambda command, **_: started.append(command)):
            self.assertEqual(app.check_update(), dict(version='0.2.0'))
            download = updates.download

            def while_downloading(update, folder):
                # the app is about to close, so a stream can't start
                self.assertEqual(app.start(), dict(ok=False))
                return download(update, folder)
            with mock.patch.object(updates, 'download', while_downloading):
                self.assertEqual(app.install_update(), dict(ok=True))
            path = Path(self.folder.name)/'updates'/f'GogglesBridgePersonal{updates.ASSET}'
            if backend.MAC:
                self.assertEqual(started[0][4], str(path))
            else:
                self.assertEqual(started, [[str(path), '/SILENT', '/SUPPRESSMSGBOXES']])
            self.assertEqual((path.read_bytes(), closed), (installer, [True]))
            # a download that differs from the published hash is deleted and never run
            app._update = dict(app._update, sha256='0'*64)
            self.assertEqual(app.install_update(), dict(error="Couldn't install the update"))
            self.assertEqual((path.exists(), len(started), closed), (False, 1, [True]))
            self.assertEqual(app.start(), dict(ok=True))


if __name__ == '__main__':
    unittest.main()
