import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from desktop_app.compatibility import assess
from desktop_app.controller import Controller
from desktop_app.ui import MainWindow

APP = QApplication.instance() or QApplication([])


class UiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'GOGGLES_STREAMER_DATA_DIR': self.folder.name})
        self.env.start()
        self.window = MainWindow(autostart_checks=False)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()
        self.env.stop()
        self.folder.cleanup()

    def test_connection_gate_and_unplug(self):
        self.assertFalse(self.window.ready())
        self.window.on_event(dict(event='environment', os='Windows', gpu=[], encoder_ok=True,
            supported_os=True, encoder_message='OK', driver=dict(status='verified', title='OK', message='OK')))
        self.window.on_event(dict(event='device', model='DJI Goggles 2', firmware='01.14.0000',
            compatibility=assess('DJI Goggles 2', '01.14.0000')))
        self.assertTrue(self.window.ready())
        self.assertEqual(self.window.start_button.text(), '开始串流')
        self.window.on_event(dict(event='problem', code='not_connected', message='Disconnected'))
        self.assertFalse(self.window.ready())
        self.assertIsNone(self.window.device)

    def test_frame_rate_changes_clamp_bitrate(self):
        self.window.quality.setCurrentIndex(self.window.quality.findData('quality'))
        self.window.fps.setCurrentIndex(self.window.fps.findData(60))
        self.assertEqual(self.window.settings.bitrate_mbps, 24)
        self.assertTrue(self.window.resolution.isEnabled())
        self.assertFalse(self.window.bitrate.model().item(self.window.bitrate.findData(40)).isEnabled())
        self.window.fps.setCurrentIndex(self.window.fps.findData(100))
        self.assertEqual(self.window.settings.bitrate_mbps, 40)

    def test_extended_source_requires_driver_and_display_before_streaming(self):
        self.window.environment = dict(driver=dict(status='verified'),encoder_ok=True,supported_os=True)
        self.window.device = dict(compatibility=assess('DJI Goggles 2','01.14.0000'))
        self.window.source.setCurrentIndex(self.window.source.findData('extended'))
        self.assertEqual(self.window.next_action(),('display_driver','安装扩展屏驱动'))
        self.assertFalse(self.window.ready())
        self.assertFalse(self.window.capture.isEnabled())
        with patch.object(self.window,'install_virtual_driver') as install:
            self.window.toggle_stream()
            install.assert_called_once()
        self.window.virtual_state = dict(installed=True,owned=True,displays=[])
        self.assertEqual(self.window.next_action()[0],'stream')

    def test_actual_virtual_refresh_is_shown_and_gated(self):
        self.window.environment = dict(driver=dict(status='verified'),encoder_ok=True,supported_os=True)
        self.window.device = dict(compatibility=assess('DJI Goggles 2','01.14.0000'))
        self.window.source.setCurrentIndex(1)
        screen=dict(active=True,primary=False,width=1920,height=1080,hz=120)
        self.window.virtual_state = dict(installed=True,owned=False,displays=[screen])
        self.window.refresh_controls()
        self.assertIn('120 Hz',self.window.display_status.text())
        self.assertEqual(self.window.next_action()[0],'display_driver')
        screen['hz']=60
        self.window.virtual_state['owned'] = True
        self.assertTrue(self.window.ready())

    def test_virtual_removal_success_has_correct_recovery(self):
        from unittest.mock import Mock
        self.window.virtual_installer=Mock()
        self.window.virtual_installer.poll.return_value=0
        self.window.virtual_removing=True
        with patch.object(self.window,'display_task'):
            self.window.poll_virtual_installer()
        self.assertIn('已移除',self.window.notice.text())
        self.assertNotIn('点击启用',self.window.notice.text())

    def test_live_stats_and_error_are_visible(self):
        before = len(self.window.history)
        with patch.object(self.window, 'refresh_controls') as refresh:
            self.window.on_event(dict(event='live_stats', fps=99.5, send_ms=.3, bandwidth_mbps=32.1))
            refresh.assert_not_called()
        self.assertEqual(len(self.window.history), before)
        self.assertIn('99.5', self.window.stat_values[0].text())
        self.window.on_event(dict(event='problem', code='capture', message='采集失败', details='test'))
        self.assertEqual(self.window.status_detail.text(), '采集失败')
        self.assertTrue(self.window.had_problem)

    def test_parameter_accessible_names(self):
        from PySide6.QtGui import QAccessible
        for widget, name in ((self.window.quality, '画质预设'), (self.window.fps, '目标帧率'),
                             (self.window.resolution, '发送分辨率'), (self.window.bitrate, '视频码率')):
            self.assertEqual(QAccessible.queryAccessibleInterface(widget).text(QAccessible.Text.Name), name)

    def test_stream_rejection_remains_visible_after_display_cleanup(self):
        self.window.on_event(dict(event='error', message='Goggles rejected 0b/1a: d6'))
        self.window.on_event(dict(event='releasing_display'))
        self.window.on_ended('stream', 0)
        self.assertIn('重新进入 DJI Virtual Flight', self.window.status_detail.text())
        self.assertIn('d6', self.window.status_detail.text())
        self.assertTrue(self.window.had_problem)

    def test_usb_hotplug_arms_once_and_manual_stop_waits_for_replug(self):
        self.window.environment = dict(driver=dict(status='verified'), encoder_ok=True, supported_os=True)
        device = dict(event='device', model='DJI Goggles 2', firmware='01.14.0000',
                      compatibility=assess('DJI Goggles 2', '01.14.0000'))
        with patch.object(self.window, 'auto_probe') as probe, \
             patch.object(self.window, 'begin_stream') as start:
            self.window.on_presence(dict(event='usb_presence', connected=True, token='a'))
            probe.assert_called_once()
            self.window.on_event(device)
            self.window.on_probe_ended('probe', 0)
            start.assert_called_once()
            self.window.on_presence(dict(event='usb_presence', connected=True, token='a'))
            self.window.on_probe_ended('probe', 0)
            start.assert_called_once()
            self.window.stop_stream()
            self.window.maybe_auto_start()
            start.assert_called_once()
            self.window.on_presence(dict(event='usb_presence', connected=False, token=''))
            self.assertFalse(self.window.ready())
            self.window.on_presence(dict(event='usb_presence', connected=True, token='a'))
            self.window.on_event(device)
            self.window.on_probe_ended('probe', 0)
            self.assertEqual(start.call_count, 2)

    def test_probe_is_background_and_releases_usb_before_stream_start(self):
        self.window.environment = dict(driver=dict(status='verified'), encoder_ok=True, supported_os=True)
        self.window.device = dict(compatibility=assess('DJI Goggles 2', '01.14.0000'))
        self.window.probe_controller.process = object()
        try:
            self.window.refresh_controls()
            self.assertTrue(self.window.start_button.isEnabled())
            self.assertTrue(self.window.reset_button.isEnabled())
            with patch.object(self.window.probe_controller, 'stop') as stop, \
                 patch.object(self.window.controller, 'start') as start:
                self.window.toggle_stream()
                stop.assert_called_once()
                start.assert_not_called()
                self.window.probe_controller.process = None
                self.window.on_probe_ended('probe', 0)
                self.assertEqual(start.call_args.args[0], 'stream')
        finally:
            self.window.probe_controller.process = None

    def test_unplug_cancels_stream_and_stale_probe_cannot_restore_device(self):
        self.window.usb_connected = True
        self.window.presence_token = 'a'
        self.window.controller.task = 'stream'
        try:
            with patch.object(self.window.controller, 'stop') as stop:
                self.window.on_presence(dict(event='usb_presence', connected=False, token=''))
                stop.assert_called_once()
            self.window.on_probe_event(dict(event='device', compatibility=dict(allowed=True)))
            self.assertIsNone(self.window.device)
            self.assertFalse(self.window.auto_armed)
        finally:
            self.window.controller.task = None

    def test_primary_action_resolves_driver_and_firmware_blockers(self):
        self.window.environment = dict(driver=dict(status='missing'), encoder_ok=True, supported_os=True)
        self.window.navigate(1)
        with patch.object(self.window, 'install_driver') as install:
            self.window.toggle_stream()
            install.assert_called_once()
        self.window.environment['driver']['status'] = 'verified'
        self.window.device = dict(compatibility=assess('DJI Goggles 2', '01.12.0000'))
        with patch.object(self.window, 'open_help') as help:
            self.window.toggle_stream()
            help.assert_called_once_with('firmware')

    def test_no_duplicate_worker_and_graceful_stop(self):
        import sys
        script = Path(self.folder.name)/'worker.py'
        script.write_text('import sys,json\njson.loads(sys.stdin.readline())\n'
                          'print(json.dumps({"event":"test_ready"}),flush=True)\n'
                          'sys.stdin.readline()\n', encoding='utf-8')
        controller = Controller()
        events, ended = [], []
        controller.event.connect(events.append)
        controller.ended.connect(lambda *args: ended.append(args))
        with patch('desktop_app.controller.worker_command', return_value=(sys.executable, [str(script)])):
            self.assertTrue(controller.start('test'))
            self.assertFalse(controller.start('test'))
            for _ in range(100):
                QTest.qWait(20)
                if events:
                    break
            self.assertEqual(events[0]['event'], 'test_ready')
            self.assertTrue(controller.job.handle)
            controller.stop()
            for _ in range(100):
                QTest.qWait(20)
                if ended:
                    break
            self.assertFalse(controller.busy)
            self.assertEqual(ended, [('test', 0)])


if __name__ == '__main__':
    unittest.main()
