"""Offline Windows app lifecycle checks; no USB, driver, GPU or display APIs run."""
from contextlib import contextmanager, nullcontext
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

from goggles_bridge.app import backend
from goggles_bridge.app.windows import display_session, dxgi, runtime, virtual_driver, worker
from goggles_bridge.app.windows import stream_engine
from goggles_bridge.engine import BridgeSettings


DISPLAYS = [dict(index=i, device=f'DISPLAY{i+1}', name=f'Display {i+1}', x=1920*i, y=0,
                 width=1920, height=1080, hz=100, primary=i == 0, virtual=False) for i in range(2)]
VIRTUAL = dict(owned=True, installed=True, config_current=True, needs_update=False, displays=[], supported=True)
IDENTITY = dict(event='ready', model='DJI Goggles 2', identity='E3T ZV900 AC Aug 11 2026|07:21:27')


class FakeRuntime:
    def __init__(self, failure=None):
        self.failure = failure
        self.entered = threading.Event()
        self.released = threading.Event()
        self.calls = []

    def run(self, settings, options, log, stop, on_event):
        self.calls.append((settings, options))
        try:
            if self.failure:
                raise self.failure
            on_event(IDENTITY)
            on_event(dict(event='streaming'))
            self.entered.set()
            stop.wait(3)
        finally:
            if options['source'] == 'virtual':
                on_event(dict(event='releasing_display'))
            self.released.set()


class WindowsAppTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.present = self.folder/'tool.exe'
        self.present.touch()
        self.settings = self.folder/'Goggles Bridge'/'settings.json'
        self.runtime = FakeRuntime()
        for name, value in dict(WINDOWS=True, MAC=False, data_dir=lambda: self.settings.parent,
                                find_ffmpeg=lambda: self.present, find_dll=lambda: self.present,
                                goggles_attached=lambda: False, list_displays=lambda: [dict(d) for d in DISPLAYS],
                                screen_access=lambda request=False: True).items():
            patcher = mock.patch.object(backend, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(virtual_driver, 'status', return_value=dict(VIRTUAL))
        self.virtual_status = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('goggles_bridge.app.windows.paths.stock_ffmpeg_path', return_value=self.present)
        patcher.start()
        self.addCleanup(patcher.stop)

    def app(self, *, default_path=False, runtime_adapter=None):
        app = backend.Desktop(settings_path=None if default_path else self.settings,
                              runtime=runtime_adapter or self.runtime, identify=lambda: None)
        self.addCleanup(app.close)
        return app

    def test_windows_options_are_separate_from_sdk_and_fixed_controls_match_capabilities(self):
        app = self.app()
        self.assertEqual(app.set_options(dict(source='virtual', resolution='720p', auto_start=False,
                                             display_device='DISPLAY2', fps=100, bitrate_mbps=32,
                                             capture='gfxcapture', low_latency=False, h264_profile='baseline',
                                             adaptive_quant=True)), dict(ok=True))
        settings = app._settings({})
        self.assertEqual((settings.capture, settings.capture_fps, settings.low_latency, settings.h264_profile,
                          settings.adaptive_quant), ('ddagrab', 100, True, 'high', False))
        self.assertTrue(set(backend.APP_OPTIONS).isdisjoint(asdict(settings)))
        snapshot = app.snapshot()
        self.assertEqual(snapshot['options']['resolution'], '720p')
        self.assertTrue(snapshot['capabilities']['fixed_encoder_options'])
        self.assertEqual(snapshot['capabilities']['captures'], ['ddagrab'])
        self.assertEqual(snapshot['choices']['bitrates']['100']['auto'], 32)
        self.assertEqual(snapshot['options']['capture'], 'gfxcapture')
        self.assertEqual(snapshot['options']['h264_profile'], 'baseline')
        self.assertTrue(snapshot['options']['adaptive_quant'])
        app.set_options(dict(source='display'))
        desktop = app._settings({})
        self.assertEqual((desktop.capture, desktop.capture_fps, desktop.h264_profile,
                          desktop.adaptive_quant, desktop.low_latency),
                         ('gfxcapture', 1000, 'baseline', True, False))
        self.assertFalse(app.snapshot()['capabilities']['fixed_encoder_options'])
        self.assertEqual(app.snapshot()['capabilities']['captures'], ['gfxcapture', 'ddagrab'])
        self.assertEqual(app.snapshot()['choices']['keyframe_seconds'], (0, 1, 3))
        for invalid in ({'source': 'window'}, {'resolution': '4k'}, {'auto_start': 'yes'},
                        {'display_device': 'x'*257}):
            before = dict(app._options)
            self.assertIn('error', app.set_options(invalid))
            self.assertEqual(app._options, before)

    def test_startup_policy_is_app_only_and_sdk_preferences_are_validated(self):
        app = self.app()
        self.assertEqual(app._options['capture'], 'gfxcapture')
        self.assertEqual(app.set_options(dict(capture='ddagrab', keyframe_seconds=0,
            h264_profile='baseline', low_latency=False, adaptive_quant=True, usb_write_size=2048)), dict(ok=True))
        effective = app._settings({})
        self.assertEqual(effective.keyframe_seconds, 3)
        self.assertEqual(app._options['keyframe_seconds'], 0)
        self.assertEqual(effective.usb_write_size, 2048)
        app.set_options(dict(source='virtual'))
        before = dict(app._options)
        for invalid in (dict(capture='screencapturekit'), dict(keyframe_seconds=False),
                        dict(keyframe_seconds=2), dict(h264_profile='invalid')):
            self.assertIn('error', app.set_options(invalid))
            self.assertEqual(app._options, before)
        app.set_options(dict(source='display'))
        self.assertEqual(app._options['keyframe_seconds'], 0)
        self.assertEqual(app._options['h264_profile'], 'baseline')

    def test_030_migration_preserves_actual_startup_policy_but_upstream_is_unchanged(self):
        self.settings.parent.mkdir()
        for saved, expected in ((dict(capture='ddagrab', source='display', keyframe_seconds=3), 0),
                                (dict(capture='gfxcapture', keyframe_seconds=1), 1),
                                (dict(capture='ddagrab', source='display', keyframe_seconds=3,
                                      windows_options_version=1), 3)):
            self.settings.write_text(json.dumps(saved), encoding='utf-8')
            app = self.app()
            self.assertEqual(app._options['keyframe_seconds'], expected)
            app.set_options(dict(show_cursor=False))
            persisted = json.loads(self.settings.read_text(encoding='utf-8'))
            self.assertEqual(persisted['windows_options_version'], 1)
            self.assertEqual(self.app()._options['keyframe_seconds'], expected)

    def test_active_stream_and_setup_reject_option_changes_without_saving(self):
        app = self.app()
        app.set_options(dict(fps=100, bitrate_mbps=32))
        original = self.settings.read_bytes()
        app.start()
        self.assertTrue(self.runtime.entered.wait(1))
        for phase in ('ready', 'streaming', 'stopping'):
            with self.subTest(phase=phase):
                app._state['phase'] = phase
                self.assertIn('error', app.set_options(dict(fps=60)))
                self.assertEqual(self.settings.read_bytes(), original)
        app.stop()
        app._thread.join(1)
        for setting in ('_installing', '_updating'):
            setattr(app, setting, 'driver' if setting == '_installing' else True)
            self.assertIn('error', app.set_options(dict(fps=60)))
            setattr(app, setting, None if setting == '_installing' else False)
        self.assertEqual(app._options['fps'], 100)

    def test_hotplug_attempts_once_and_manual_stop_requires_a_new_connection(self):
        app = self.app()
        app.set_options(dict(auto_start=True))
        app.finish_setup()
        with mock.patch.object(app, 'start', return_value=dict(ok=True)) as start:
            for presence in (None, False, True, True, None, True):
                app._hotplug_tick(presence)
            self.assertEqual(start.call_count, 1)
            app.stop()
            app._hotplug_tick(True)
            self.assertEqual(start.call_count, 1)
            app._hotplug_tick(False)
            app._hotplug_tick(True)
            self.assertEqual(start.call_count, 2)

    def test_auto_start_waits_for_onboarding_setup_and_preference(self):
        app = self.app()
        app.set_options(dict(auto_start=True))
        with mock.patch.object(app, 'start') as start:
            app._hotplug_tick(True)
            start.assert_not_called()
            app._onboarded = True
            app._options['auto_start'] = False
            app._hotplug_tick(True)
            start.assert_not_called()
            app._options['auto_start'] = True
            app._installing = 'virtual_display'
            app._hotplug_tick(True)
            start.assert_not_called()
            app._installing = None
            app._updating = True
            app._hotplug_tick(True)
            start.assert_not_called()
            app._updating = False
            app._hotplug_tick(True)
            start.assert_called_once()

    def test_auto_start_failure_does_not_retry_forever_or_query_active_stream(self):
        app = self.app()
        app.set_options(dict(auto_start=True))
        app.finish_setup()
        self.present.unlink()
        with mock.patch.object(app, 'start', wraps=app.start) as start:
            app._hotplug_tick(True)
            app._hotplug_tick(True)
            app._hotplug_tick(None)
            app._hotplug_tick(True)
            self.assertEqual(start.call_count, 1)
            self.assertEqual(app.snapshot()['phase'], 'error')
            self.assertEqual(self.runtime.calls, [])

    def test_auto_start_is_opt_in_even_after_setup_and_usb_reconnection(self):
        app = self.app()
        self.assertFalse(app._options['auto_start'])
        app.finish_setup()
        with mock.patch.object(app, 'start') as start:
            for presence in (True, False, True):
                app._hotplug_tick(presence)
            start.assert_not_called()
        self.assertFalse(self.app()._options['auto_start'])

    def test_saved_auto_start_opt_in_survives_upgrade(self):
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text(json.dumps(dict(auto_start=True, onboarded=True)), encoding='utf-8')
        app = self.app()
        self.assertTrue(app._options['auto_start'])
        with mock.patch.object(app, 'start') as start:
            app._hotplug_tick(True)
            start.assert_called_once()

    def test_disconnect_stops_and_cleans_virtual_session_without_gui_polling(self):
        app = self.app()
        app.set_options(dict(source='virtual'))
        app.start()
        self.assertTrue(self.runtime.entered.wait(1))
        app._hotplug_tick(False)
        app._thread.join(1)
        self.assertFalse(app._thread.is_alive())
        self.assertTrue(self.runtime.released.is_set())
        self.assertEqual(app.snapshot()['phase'], 'idle')
        self.assertFalse(app._connection_attempted)

    def test_runtime_exception_remains_an_error_after_cleanup(self):
        app = self.app(runtime_adapter=FakeRuntime(RuntimeError('capture failure')))
        app.set_options(dict(source='virtual'))
        app.start()
        app._thread.join(1)
        state = app.snapshot()
        self.assertEqual(state['phase'], 'error')
        self.assertIn('capture failure', state['problem']['message'])
        self.assertFalse(app._running())

    def test_cleanup_notifications_do_not_erase_actionable_errors(self):
        app = self.app()
        app._event(dict(event='error', message='capture failed'))
        app._event(dict(event='releasing_display'))
        app._event(dict(event='display_status', owned=True))
        self.assertEqual(app.snapshot()['phase'], 'error')
        self.assertEqual(app.snapshot()['problem']['message'], 'capture failed')
        app._event(dict(event='display_cleanup_error', message='The display could not be removed'))
        self.assertEqual(app.snapshot()['problem']['code'], 'virtual_display')

    def test_close_waits_for_worker_cleanup_and_disables_auto_restart(self):
        app = self.app()
        app.set_options(dict(source='virtual'))
        app.start()
        self.assertTrue(self.runtime.entered.wait(1))
        app.close()
        self.assertTrue(self.runtime.released.is_set())
        self.assertTrue(app._watch_stop.is_set())
        self.assertFalse(app._running())

    def test_timed_out_live_worker_keeps_ui_and_reconnect_locked_until_exit(self):
        adapter = runtime.WindowsRuntime()
        process = mock.Mock()
        process.poll.return_value = None
        adapter._process = process
        app = self.app(runtime_adapter=adapter)
        app._options['auto_start'] = True
        app._onboarded = True
        app._state.update(phase='error', problem=dict(code='other', message='cleanup timed out'))
        self.assertTrue(app._running())
        self.assertEqual(app.snapshot()['phase'], 'stopping')
        self.assertIn('error', app.set_options(dict(fps=60)))
        with mock.patch.object(adapter, 'run') as run:
            app.start()
            app._hotplug_tick(False)
            app._hotplug_tick(True)
            run.assert_not_called()
            self.assertIsNone(app._thread)
        process.poll.return_value = 0
        self.assertFalse(app._running())
        self.assertEqual(app.snapshot()['phase'], 'error')
        self.assertEqual(app.set_options(dict(fps=60, bitrate_mbps=None)), dict(ok=True))

    def test_unchanged_stream_state_never_rechecks_driver_or_display_inventory(self):
        app = self.app()
        app.snapshot()
        app.start()
        self.assertTrue(self.runtime.entered.wait(1))
        with mock.patch.object(backend, 'list_displays', side_effect=AssertionError('hot path inventory')), \
             mock.patch.object(backend, 'goggles_attached', side_effect=AssertionError('hot path PnP')):
            for _ in range(3):
                app._event(IDENTITY)
                self.assertEqual(app.snapshot()['phase'], 'ready')
                app._event(dict(event='streaming'))
                self.assertEqual(app.snapshot()['phase'], 'streaming')
                self.assertIn('error', app.set_options(dict(fps=60)))

    def test_virtual_driver_is_required_only_for_virtual_source(self):
        self.virtual_status.return_value = dict(VIRTUAL, owned=False, installed=False)
        app = self.app()
        self.assertTrue(app.start()['ok'])
        self.assertTrue(self.runtime.entered.wait(1))
        app.stop()
        app._thread.join(1)
        app.set_options(dict(source='virtual'))
        self.assertFalse(app.start()['ok'])
        self.assertEqual(app.snapshot()['problem']['code'], 'virtual_display')
        self.assertEqual(len(self.runtime.calls), 1)

    def test_failed_driver_installation_exposes_error_and_unlocks_retry(self):
        app = self.app()
        operation = mock.Mock()
        operation.poll.return_value = 5
        with mock.patch.object(virtual_driver, 'VirtualInstaller', return_value=operation):
            app.install_virtual_driver()
            app._install_thread.join(1)
        check = app.snapshot()['checks']['virtual_display']
        self.assertFalse(check['installing'])
        self.assertIn('(5)', check['problem'])
        self.assertIsNone(app._installing)
        self.assertEqual(app.set_options(dict(source='display')), dict(ok=True))

    def test_stable_device_survives_display_reordering(self):
        app = self.app()
        app.set_options(dict(display_index=1, display_device='DISPLAY2'))
        reordered = [dict(DISPLAYS[1], index=0), dict(DISPLAYS[0], index=1)]
        with mock.patch.object(backend, 'list_displays', return_value=reordered):
            options = app.snapshot()['options']
        self.assertEqual((options['display_device'], options['display_index']), ('DISPLAY2', 0))

    def test_legacy_migration_preserves_old_file_and_never_overwrites_upstream(self):
        legacy = self.folder/'DJI Goggles Streamer'/'settings.json'
        legacy.parent.mkdir()
        saved = dict(source='extended', resolution='720p', auto_start=True, fps=100, bitrate_mbps=32,
                     preset='p4', display_device='DISPLAY2', quality='quality', schema=1)
        legacy.write_text(json.dumps(saved), encoding='utf-8')
        old_bytes = legacy.read_bytes()
        with mock.patch.dict(os.environ, LOCALAPPDATA=str(self.folder)):
            app = self.app(default_path=True)
            self.assertEqual((app._options['source'], app._options['resolution']), ('virtual', '720p'))
            self.assertTrue(app._onboarded)
            self.assertTrue(app._options['auto_start'])
            self.assertEqual(legacy.read_bytes(), old_bytes)
            self.assertNotIn('quality', app._options)
            app.set_options(dict(source='display', fps=60, bitrate_mbps=None))
            upstream_bytes = self.settings.read_bytes()
            again = self.app(default_path=True)
        self.assertEqual((again._options['source'], again._options['fps']), ('display', 60))
        self.assertEqual(self.settings.read_bytes(), upstream_bytes)
        self.assertEqual(legacy.read_bytes(), old_bytes)

    def test_mac_keeps_sdk_path_and_ignores_windows_only_preferences(self):
        with mock.patch.multiple(backend, WINDOWS=False, MAC=True, CAPTURES=('screencapturekit',)), \
             mock.patch.object(backend.Desktop, '_migrate_legacy', side_effect=AssertionError('mac migration')):
            engine = mock.Mock()
            check = mock.Mock(return_value=None)
            app = backend.Desktop(settings_path=self.settings, engine_factory=engine, check=check, identify=lambda: None)
            self.addCleanup(app.close)
            app.set_options(dict(source='virtual', resolution='720p', auto_start=True, display_device='DISPLAY2'))
            self.assertIsNone(app._runtime)
            self.assertTrue(set(backend.APP_OPTIONS).isdisjoint(app._options))
            self.assertEqual(app._options['capture'], 'screencapturekit')
            self.assertFalse(app.snapshot()['capabilities']['virtual_display'])
            app.start()
            app._thread.join(1)
            check.assert_called_once()
            engine.assert_called_once()
            self.assertEqual(engine.call_args.args[0].capture, 'screencapturekit')
            app.start_monitor()
            self.assertIsNone(app._watcher)


class WorkerLifecycleTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.log = Path(folder.name)/'stream.jsonl'
        settings = asdict(BridgeSettings(None, None, fps=100, capture='ddagrab', bitrate_mbps=32))
        self.request = dict(settings=settings, options=dict(source='virtual', resolution='720p', display_device='DISPLAY2'),
                            log=str(self.log))

    def test_worker_releases_capture_on_precheck_engine_and_callback_failures(self):
        for failure in ('precheck', 'engine', 'event'):
            with self.subTest(failure=failure):
                cleanup = []
                @contextmanager
                def target(settings, emit):
                    self.assertEqual(settings.dimensions, (1280, 720))
                    self.assertEqual(settings.fps, 100)
                    try:
                        yield dict(device='DISPLAY2', refresh_rate=100)
                    finally:
                        cleanup.append('released')
                emit = mock.Mock(side_effect=RuntimeError('event failed') if failure == 'event' else None)
                engine = mock.Mock()
                if failure == 'engine':
                    engine.return_value.run.side_effect = RuntimeError('engine failed')
                with mock.patch.object(display_session, 'capture_target', target), \
                     mock.patch.object(dxgi, 'select_output', return_value=dict(output=1, vendor_id=0x10DE)), \
                     mock.patch.object(worker, 'check_encoder', return_value='precheck failed' if failure == 'precheck' else None), \
                     mock.patch.object(stream_engine, 'DesktopBridgeEngine', engine):
                    with self.assertRaisesRegex(RuntimeError, f'{failure} failed'):
                        worker.stream(self.request, threading.Event(), emit)
                self.assertEqual(cleanup, ['released'])

    def test_stop_before_capture_never_creates_a_display(self):
        stop = threading.Event()
        stop.set()
        with mock.patch.object(display_session, 'capture_target') as capture:
            worker.stream(self.request, stop, mock.Mock())
            capture.assert_not_called()

    def test_display_lease_releases_real_ownership_when_observer_or_capture_fails(self):
        target = dict(device='DISPLAY2', monitor_id='owned')
        with mock.patch.object(display_session, '_process_lease', return_value=nullcontext()), \
             mock.patch.object(virtual_driver, 'status', return_value=dict(VIRTUAL)), \
             mock.patch.object(display_session.displays, 'enable_extended', return_value=target), \
             mock.patch.object(display_session.displays, 'select_source', return_value=target), \
             mock.patch.object(display_session, 'active_refresh', return_value=100), \
             mock.patch.object(display_session.displays, 'disable_extended') as release:
            def emit(event, **fields):
                if event in ('display_status', 'releasing_display'):
                    raise RuntimeError('observer failed')
            with self.assertRaisesRegex(RuntimeError, 'observer failed'):
                with display_session.lease('virtual', 1280, 720, 100, emit):
                    self.fail('observer failure must abort entry')
            release.assert_called_once_with(expected=target)
            self.assertTrue(display_session._virtual_lease.acquire(blocking=False))
            display_session._virtual_lease.release()

    def test_physical_display_never_changes_virtual_device_ownership(self):
        target = dict(device='DISPLAY1', monitor_id='physical')
        with mock.patch.object(display_session.displays, 'select_source', return_value=target), \
             mock.patch.object(display_session, 'active_refresh', return_value=100), \
             mock.patch.object(display_session.displays, 'enable_extended') as enable, \
             mock.patch.object(display_session.displays, 'disable_extended') as disable, \
             mock.patch.object(display_session, '_process_lease') as mutex:
            with display_session.lease('display', display_device='DISPLAY1') as selected:
                self.assertEqual(selected['device'], 'DISPLAY1')
            enable.assert_not_called()
            disable.assert_not_called()
            mutex.assert_not_called()


class WorkerProcessTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.log = Path(folder.name)/'stream.jsonl'
        self.settings = BridgeSettings(None, None, fps=100, capture='ddagrab', bitrate_mbps=32)

    def run_worker(self, process, emit=lambda row: None):
        with mock.patch.object(runtime, 'worker_command', return_value=('worker.exe', [])), \
             mock.patch.object(runtime.subprocess, 'Popen', return_value=process):
            runtime.WindowsRuntime().run(self.settings, dict(source='virtual'), self.log, threading.Event(), emit)

    def fake_process(self, rows=(), code=0):
        process = mock.Mock()
        process.stdin = io.StringIO()
        process.stdout = io.StringIO(''.join(json.dumps(row)+'\n' for row in rows))
        process.wait.return_value = code
        process.poll.return_value = code
        return process

    def test_parent_drains_worker_events_and_closes_pipes_on_callback_failure(self):
        process = self.fake_process([dict(event='display_path', adapter_luid='0:1')])
        with self.assertRaisesRegex(RuntimeError, 'callback failed'):
            self.run_worker(process, emit=mock.Mock(side_effect=RuntimeError('callback failed')))
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)

    def test_nonzero_exit_is_reported_after_worker_releases_display(self):
        rows = [dict(event='releasing_display'), dict(event='error', message='capture failed')]
        process = self.fake_process(rows, code=1)
        seen = []
        with self.assertRaisesRegex(RuntimeError, 'capture failed'):
            self.run_worker(process, emit=seen.append)
        self.assertEqual(seen, rows)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)

    def test_first_request_write_failure_still_closes_pipes_and_reaps_worker(self):
        process = self.fake_process()
        process.stdin = mock.Mock()
        process.stdin.write.side_effect = BrokenPipeError('worker exited before setup')
        with self.assertRaises(BrokenPipeError):
            self.run_worker(process)
        process.stdin.close.assert_called_once()
        self.assertTrue(process.stdout.closed)
        process.wait.assert_called()

    def test_broken_stdin_close_cannot_skip_stdout_cleanup(self):
        process = self.fake_process()
        process.stdin = mock.Mock()
        process.stdin.close.side_effect = BrokenPipeError('worker closed input')
        try:
            self.run_worker(process)
        except BrokenPipeError:
            pass
        self.assertTrue(process.stdout.closed)

    def test_wait_timeout_retains_process_ownership_and_blocks_second_worker(self):
        adapter = runtime.WindowsRuntime()
        process = self.fake_process()
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired('worker.exe', 20)
        with mock.patch.object(runtime, 'worker_command', return_value=('worker.exe', [])), \
             mock.patch.object(runtime.subprocess, 'Popen', return_value=process) as spawn:
            with self.assertRaises(subprocess.TimeoutExpired):
                adapter.run(self.settings, dict(source='virtual'), self.log, threading.Event(), lambda row: None)
            self.assertTrue(adapter.busy())
            with self.assertRaisesRegex(RuntimeError, 'previous worker'):
                adapter.run(self.settings, dict(source='virtual'), self.log, threading.Event(), lambda row: None)
            spawn.assert_called_once()
            self.assertTrue(process.stdin.closed)
            self.assertTrue(process.stdout.closed)
            process.poll.return_value = 0
            self.assertFalse(adapter.busy())


if __name__ == '__main__':
    unittest.main()
