import io
import threading
import time
import unittest
from unittest.mock import patch, Mock

from desktop_app.telemetry import SenderTelemetry
from desktop_app.events import EventWriter
from desktop_app.settings import Settings
from desktop_app.display_session import capture_target
from desktop_app.pacing import FramePacer


class PacingTests(unittest.TestCase):
    def test_startup_lead_and_regular_cadence_use_sleep_without_dropping(self):
        now, sleeps = [10.0], []
        def sleep(delay):
            sleeps.append(delay)
            now[0] += delay
        pacer = FramePacer(100, clock=lambda: now[0], sleep=sleep)
        stamps = []
        for _ in range(6):
            pacer.wait()
            stamps.append(now[0])
        self.assertAlmostEqual(sleeps[0], .02)
        for a,b in zip(stamps,stamps[1:]):
            self.assertAlmostEqual(b-a, .01)
        self.assertEqual(len(sleeps), 6)

    def test_late_capture_does_not_cause_unbounded_catchup_burst(self):
        now = [10.0]
        pacer = FramePacer(60, clock=lambda: now[0], sleep=lambda d: now.__setitem__(0, now[0]+d))
        pacer.wait()
        now[0] += .5
        pacer.wait()
        late = now[0]
        pacer.wait()
        self.assertGreaterEqual(now[0]-late, 1/120-1e-9)


class TelemetryTests(unittest.TestCase):
    def test_failed_usb_writes_do_not_count_and_control_is_not_a_video_frame(self):
        from desktop_app.device import VerifiedTransport
        counter = SenderTelemetry(Mock())
        transport = VerifiedTransport.__new__(VerifiedTransport)
        transport.pacer = None
        transport.telemetry, transport.usb = counter, Mock()
        video = b'\0'*9 + b'\x0b\x53' + b'\0'*100
        transport.write(video)
        transport.write(b'control')
        self.assertEqual(counter.snapshot[:2], (len(video)+7, 1))
        transport.usb.write.side_effect = OSError('Disconnected')
        with self.assertRaises(OSError):
            transport.write(video)
        self.assertEqual(counter.snapshot[:2], (len(video)+7, 1))
        counter.emit.assert_not_called()

    def test_samples_have_correct_units_and_expire_stale_latency(self):
        now, rows = [10_000_000_000], []
        counter = SenderTelemetry(lambda *a, **k: rows.append(k), clock=lambda: now[0])
        count = [0]

        def tick(_):
            count[0] += 1
            if count[0] == 13:
                return True
            now[0] += 100_000_000
            if count[0] == 1:
                counter.record(100_000, True, now[0]-500_000, now[0])
            return False

        counter.stop = Mock()
        counter.stop.wait.side_effect = tick
        counter.run()
        self.assertEqual((rows[0]['bandwidth_mbps'], rows[0]['fps'], rows[0]['send_ms']), (8,10,.5))
        self.assertEqual(rows[-1]['bandwidth_mbps'], 0)
        self.assertIsNone(rows[-1]['send_ms'])

    def test_stalled_gui_never_blocks_sender_and_queue_stays_bounded(self):
        entered, release = threading.Event(), threading.Event()
        class SlowOutput(io.StringIO):
            def write(self, value):
                entered.set()
                release.wait(3)
                return super().write(value)
        writer = EventWriter(SlowOutput())
        writer.emit('ready')
        self.assertTrue(entered.wait(1))
        started = time.perf_counter()
        try:
            for n in range(10_000):
                writer.emit('live_stats', frames=n)
                writer.emit('control', n=n)
            self.assertLess(time.perf_counter()-started, 1)
            self.assertLessEqual(writer.events.qsize(), 128)
            self.assertEqual(writer.latest_stats['frames'], 9999)
        finally:
            release.set()
            writer.close()


class DisplayLifetimeTests(unittest.TestCase):
    def test_every_requested_mode_is_created_and_released_on_failure(self):
        for resolution in ('720p','1080p'):
            for fps in (60,75,90,100):
                settings = Settings(source='extended', resolution=resolution, fps=fps)
                with patch('desktop_app.display_session.virtual_driver.status', return_value=dict(owned=True)), \
                     patch('desktop_app.display_session.displays.enable_extended') as enable, \
                     patch('desktop_app.display_session.displays.disable_extended') as disable, \
                     patch('desktop_app.display_session.displays.select_source', return_value={'device':'virtual'}):
                    with self.assertRaisesRegex(RuntimeError, 'encoder failed'):
                        with capture_target(settings, Mock()) as target:
                            self.assertEqual(target['device'], 'virtual')
                            raise RuntimeError('encoder failed')
                    enable.assert_called_once_with(*settings.dimensions, fps)
                    disable.assert_called_once()

    def test_primary_never_changes_virtual_display(self):
        with patch('desktop_app.display_session.displays.enable_extended') as enable, \
             patch('desktop_app.display_session.displays.disable_extended') as disable, \
             patch('desktop_app.display_session.displays.select_source'):
            with capture_target(Settings(), Mock()):
                pass
            enable.assert_not_called()
            disable.assert_not_called()

    def test_unowned_driver_is_not_modified(self):
        with patch('desktop_app.display_session.virtual_driver.status', return_value=dict(owned=False)), \
             patch('desktop_app.display_session.displays.enable_extended') as enable, \
             patch('desktop_app.display_session.displays.disable_extended') as disable:
            with self.assertRaises(RuntimeError):
                with capture_target(Settings(source='extended'), Mock()):
                    pass
            enable.assert_not_called()
            disable.assert_not_called()
