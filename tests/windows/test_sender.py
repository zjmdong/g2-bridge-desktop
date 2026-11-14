"""Transport and sampling checks with a fake USB endpoint and clock."""
import unittest
from unittest.mock import Mock, patch

from goggles_bridge.app.windows.device import MeasuredTransport
from goggles_bridge.app.windows.telemetry import SenderTelemetry


VIDEO = b'\0'*9 + b'\x0b\x53' + b'picture'


class SenderTests(unittest.TestCase):
    def test_transport_open_does_not_probe_or_restrict_firmware(self):
        usb = Mock()
        factory = Mock(return_value=usb)
        with MeasuredTransport('driver', write_size=2048, factory=factory) as transport:
            factory.assert_called_once_with('driver', write_size=2048)
            usb.read.assert_not_called()
            usb.write.assert_not_called()
            transport.read(timeout_ms=500)
            usb.read.assert_called_once_with(timeout_ms=500)
        usb.close.assert_called_once_with()

    def test_disabled_statistics_have_no_clock_calls_or_waits(self):
        usb = Mock()
        transport = MeasuredTransport(None, factory=Mock(return_value=usb))
        with patch('time.sleep', side_effect=AssertionError('sender must not sleep')), \
             patch('time.perf_counter_ns', side_effect=AssertionError('sampling disabled')):
            for index in range(1000):
                transport.write(VIDEO + index.to_bytes(4, 'little'))
        self.assertEqual([int.from_bytes(c.args[0][-4:], 'little') for c in usb.write.call_args_list],
                         list(range(1000)))

    def test_only_successful_writes_count_without_inline_callbacks(self):
        counter = SenderTelemetry(Mock())
        usb = Mock()
        transport = MeasuredTransport(None, telemetry=counter, factory=Mock(return_value=usb))
        transport.write(VIDEO)
        transport.write(b'control')
        self.assertEqual(counter.snapshot[:2], (len(VIDEO)+7, 1))
        usb.write.side_effect = OSError('disconnected')
        with self.assertRaises(OSError):
            transport.write(VIDEO)
        self.assertEqual(counter.snapshot[:2], (len(VIDEO)+7, 1))
        counter.emit.assert_not_called()

    def test_sampler_units_and_stale_send_time_expiry(self):
        now, rows = [10_000_000_000], []
        counter = SenderTelemetry(lambda event, **row: rows.append(row), clock=lambda: now[0])
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
        self.assertEqual((rows[0]['bandwidth_mbps'], rows[0]['fps'], rows[0]['send_ms']), (8, 10, .5))
        self.assertEqual(rows[-1]['bandwidth_mbps'], 0)
        self.assertIsNone(rows[-1]['send_ms'])


if __name__ == '__main__':
    unittest.main()
