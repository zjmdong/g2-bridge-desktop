import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from desktop_app.compatibility import assess, normalize_firmware
from desktop_app.device import inspect_transport, VerifiedTransport, CompatibilityError
from desktop_app.drivers import verify_driver, verify_installer, DRIVER_HASHES
from desktop_app.settings import Settings, bitrates, preset_values
from desktop_app.system import Cancelled, run_cancellable
from goggles_bridge.control import V1Packet, HEARTBEAT, DEVICE_INFO, SIM_MODE


class SettingsTests(unittest.TestCase):
    def test_roundtrip_and_corrupt_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'settings.json'
            settings = Settings(fps=60, bitrate_mbps=24, show_cursor=False)
            settings.save(path)
            self.assertEqual(Settings.load(path), (settings, None))
            path.write_text('{bad', encoding='utf-8')
            loaded, warning = Settings.load(path)
            self.assertEqual(loaded, Settings())
            self.assertTrue(warning)

    def test_invalid_settings_never_reach_sdk(self):
        for data in ({'fps': True}, {'fps': 144}, {'fps': 60, 'bitrate_mbps': 40},
                     {'capture': 'shell'}, {'show_cursor': 'false'}, {'schema': 2}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                Settings.from_dict(data).bridge()

    def test_all_presets_stay_in_sdk_budget(self):
        for fps in (60, 75, 90, 100):
            for quality in ('balanced', 'quality', 'efficient'):
                bitrate, preset = preset_values(quality, fps)
                self.assertIn(bitrate, bitrates(fps))
                settings = Settings(fps=fps, bitrate_mbps=bitrate, preset=preset)
                bridge = settings.bridge()
                self.assertEqual(bridge.display_index, 0)
                self.assertLessEqual(bitrate*1_000_000/(8*fps), 50_000)


class CompatibilityTests(unittest.TestCase):
    def test_only_evidenced_combinations_allowed(self):
        self.assertTrue(assess('DJI Goggles 2', 'v01.14.00.00')['allowed'])
        self.assertTrue(assess('DJI Goggles 2', '01.11.0000')['allowed'])
        self.assertTrue(assess('DJI Goggles Integra', '01.09.0000')['allowed'])
        for model, firmware in (('DJI Goggles 2', '01.12.0000'), ('DJI Goggles 2', None),
                                ('DJI Goggles 2', '01.15.0000'), ('DJI Goggles 3', '01.14.0000'),
                                ('DJI Goggles Integra', '01.14.0000')):
            self.assertFalse(assess(model, firmware)['allowed'])

    def test_malformed_version_not_substring_matched(self):
        self.assertIsNone(normalize_firmware('abc01.14.0000'))
        self.assertIsNone(normalize_firmware('01.14.0000 extra'))


class FakeGoggles:
    def __init__(self, *args, firmware='01.14.0000', **kwargs):
        self.closed = False
        self.requests = []
        self.incoming = []
        self.firmware = firmware

    def write(self, data):
        packet = V1Packet.parse(data)
        self.requests.append(packet)
        if packet.command == DEVICE_INFO:
            payload = b'\0E3T ZV900 TEST\0'
        elif packet.command == (0, 0x4f):
            xml = f'<device id="test"><firmware formal="{self.firmware}"/></device>'.encode()
            container = b'IM*H'+bytes(224+384-4)+xml
            payload = b'\0'+struct.pack('<II', len(container), 0)+container
            # A matching sequence from a different route must be ignored.
            spoof = V1Packet(*packet.command, packet.receiver_type, 4,
                packet.sender_type, packet.sender_id, 1, 0, packet.sequence, b'\x01')
            self.incoming.append(spoof.serialize())
        else:
            payload = b'\0'
        reply = V1Packet(*packet.command, packet.receiver_type, packet.receiver_id,
            packet.sender_type, packet.sender_id, 1, 0, packet.sequence, payload)
        self.incoming.append(reply.serialize())

    def read(self, **kwargs):
        return self.incoming.pop(0) if self.incoming else b''

    def close(self):
        self.closed = True


class DeviceTests(unittest.TestCase):
    def test_readonly_probe_reads_firmware_and_checks_route(self):
        usb = FakeGoggles()
        events = []
        device = inspect_transport(usb, threading.Event(), lambda event, **fields: events.append(event))
        self.assertEqual(device['firmware'], '01.14.0000')
        self.assertTrue(device['compatibility']['allowed'])
        self.assertNotIn(SIM_MODE, [p.command for p in usb.requests])
        self.assertEqual(events, ['device'])

    def test_unknown_firmware_closes_handle_before_sdk_stream(self):
        usb = FakeGoggles(firmware='01.15.0000')
        with self.assertRaises(CompatibilityError):
            VerifiedTransport(None, stop=threading.Event(), emit=lambda *a, **k: None,
                              factory=lambda *a, **k: usb)
        self.assertTrue(usb.closed)
        self.assertNotIn(SIM_MODE, [p.command for p in usb.requests])

    def test_cancelled_probe_releases_transport(self):
        usb = FakeGoggles()
        stop = threading.Event()
        stop.set()
        with self.assertRaises(Cancelled):
            VerifiedTransport(None, stop=stop, emit=lambda *a, **k: None, factory=lambda *a, **k: usb)
        self.assertTrue(usb.closed)

    def test_each_connection_verifies_the_open_handle(self):
        opened = []
        def factory(*args, **kwargs):
            usb = FakeGoggles()
            opened.append(usb)
            return usb
        for _ in range(2):
            with VerifiedTransport(None, stop=threading.Event(), emit=lambda *a, **k: None, factory=factory):
                pass
        self.assertEqual(len(opened), 2)
        self.assertTrue(all(u.closed and any(p.command == (0, 0x4f) for p in u.requests) for u in opened))


class ProcessAndDriverTests(unittest.TestCase):
    def test_cancellation_kills_encoder_check(self):
        import sys
        stop = threading.Event()
        timer = threading.Timer(.2, stop.set)
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaises(Cancelled):
                run_cancellable([sys.executable, '-c', 'import time; time.sleep(30)'], stop)
        finally:
            timer.join()
        self.assertLess(time.monotonic()-started, 3)

    def test_wrong_installer_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'fake.exe'
            path.write_bytes(b'not an installer')
            with patch('desktop_app.drivers.powershell_json') as signature:
                with self.assertRaises(ValueError):
                    verify_installer(path)
                signature.assert_not_called()

    def test_tampered_driver_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in DRIVER_HASHES:
                (Path(folder)/name).write_bytes(b'invalid')
            with self.assertRaises(ValueError):
                verify_driver(Path(folder)/'DEVICE_BULK.inf')


if __name__ == '__main__':
    unittest.main()
