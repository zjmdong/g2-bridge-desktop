"""GPU scheduling policy with synthetic processes; no GPU or USB access."""
from dataclasses import replace
import ctypes
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from goggles_bridge.control import V1Stream
from goggles_bridge.engine import BridgeEngine, BridgeSettings, prioritize_gpu
from goggles_bridge.app.windows.stream_engine import DesktopBridgeEngine



class GpuPolicyTests(unittest.TestCase):
    def settings(self):
        return BridgeSettings(Path('unused.dll'), Path('unused.exe'))

    def test_default_and_explicit_classes_use_system32_handle_and_ntstatus(self):
        for requested in range(6):
            with self.subTest(requested=requested):
                setter = Mock(return_value=0)
                dll = Mock(return_value=SimpleNamespace(D3DKMTSetProcessSchedulingPriorityClass=setter))
                with patch('goggles_bridge.engine.sys.platform', 'win32'), patch.object(ctypes, 'WinDLL', dll, create=True):
                    self.assertTrue(prioritize_gpu(SimpleNamespace(_handle=1234), requested))
                dll.assert_called_once_with('gdi32.dll', winmode=0x00000800)
                setter.assert_called_once_with(1234, requested)
                self.assertEqual(setter.argtypes, [ctypes.c_void_p, ctypes.c_int32])
                self.assertIs(setter.restype, ctypes.c_int32)
        with patch('goggles_bridge.engine.sys.platform', 'win32'), patch.object(ctypes, 'WinDLL', dll, create=True):
            setter.reset_mock()
            self.assertTrue(prioritize_gpu(SimpleNamespace(_handle=1234)))
            setter.assert_called_once_with(1234, 5)

    def test_none_unsupported_and_invalid_handles_never_load_dll(self):
        class ClosedHandle:
            closed = True
            def __int__(self):
                raise AssertionError('Closed handle must not be converted')
        invalid = [None, False, True, 0, -1, -2, -6, (1 << (ctypes.sizeof(ctypes.c_void_p)*8))-1,
                   (1 << (ctypes.sizeof(ctypes.c_void_p)*8))-2, ClosedHandle(), 'not a handle']
        with patch('goggles_bridge.engine.sys.platform', 'win32'), patch.object(ctypes, 'WinDLL', create=True) as dll:
            self.assertFalse(prioritize_gpu(SimpleNamespace(_handle=1234), None))
            for handle in invalid:
                self.assertFalse(prioritize_gpu(SimpleNamespace(_handle=handle)))
            self.assertFalse(prioritize_gpu(SimpleNamespace()))
            dll.assert_not_called()
        with patch('goggles_bridge.engine.sys.platform', 'linux'), patch.object(ctypes, 'WinDLL', create=True) as dll:
            self.assertFalse(prioritize_gpu(SimpleNamespace(_handle=1234)))
            dll.assert_not_called()

    def test_rejected_or_unavailable_api_is_nonfatal(self):
        for status in (-1073741811, 1):
            setter = Mock(return_value=status)
            with patch('goggles_bridge.engine.sys.platform', 'win32'), patch.object(ctypes, 'WinDLL',
                    return_value=SimpleNamespace(D3DKMTSetProcessSchedulingPriorityClass=setter), create=True):
                self.assertFalse(prioritize_gpu(SimpleNamespace(_handle=1234)))
        for error in (OSError('missing DLL'), AttributeError('missing API'), TypeError('unsupported loader')):
            with patch('goggles_bridge.engine.sys.platform', 'win32'), patch.object(ctypes, 'WinDLL',
                    side_effect=error, create=True):
                self.assertFalse(prioritize_gpu(SimpleNamespace(_handle=1234)))

    def test_invalid_policy_rejected_before_side_effects(self):
        for value in (True, False, -1, 6, 2.0, '2', [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                prioritize_gpu(SimpleNamespace(), value)
            with self.subTest(engine=value), self.assertRaises(ValueError):
                BridgeEngine(self.settings(), 'unused.jsonl', gpu_priority_class=value)
        self.assertEqual(BridgeEngine(self.settings(), 'unused.jsonl').gpu_priority_class, 5)
        self.assertIsNone(BridgeEngine(self.settings(), 'unused.jsonl', gpu_priority_class=None).gpu_priority_class)

    def test_desktop_high_policy_does_not_change_sdk_default_or_explicit_override(self):
        self.assertEqual(BridgeEngine(self.settings(), 'unused.jsonl').gpu_priority_class, 5)
        self.assertEqual(DesktopBridgeEngine(self.settings(), 'unused.jsonl').gpu_priority_class, 4)
        self.assertIsNone(DesktopBridgeEngine(self.settings(), 'unused.jsonl',
                                             gpu_priority_class=None).gpu_priority_class)

    def test_first_frame_policy_runs_once_and_logs_requested_class(self):
        # Synthetic Annex-B source and V1 control peer exercise the real session.
        # Its encoder/transport have no native handles and never access hardware.
        for requested, applied in ((None, False), (2, True), (4, True), (5, True), (5, False)):
            with self.subTest(requested=requested, applied=applied):
                stop = threading.Event()
                encoder_stopped = threading.Event()
                incoming = queue.Queue()
                decoder = V1Stream()
                video_count = [0]
                events = []

                class Output:
                    first = True
                    def read(self, _size):
                        if self.first:
                            self.first = False
                            return (b'\0\0\0\1\x09\xf0\0\0\0\1\x65picture') * 5
                        encoder_stopped.wait(1)
                        return b''
                    def close(self):
                        pass

                encoder = SimpleNamespace(pid=123, stdout=Output(),
                    poll=lambda: 0 if encoder_stopped.is_set() else None,
                    terminate=encoder_stopped.set, wait=lambda timeout: 0)

                class Usb:
                    def write(self, data):
                        for request in decoder.feed(data):
                            if request.command == (11, 83):
                                video_count[0] += 1
                                if video_count[0] >= 3:
                                    stop.set()
                                continue
                            payload = b'\0E3T ZV900 AC' if request.command == (0, 255) else b'\0'
                            incoming.put(replace(request, sender_type=request.receiver_type,
                                sender_id=request.receiver_id, receiver_type=request.sender_type,
                                receiver_id=request.sender_id, is_response=1, ack=2, payload=payload).serialize())
                    def read(self, timeout_ms):
                        try:
                            return incoming.get(timeout=timeout_ms/1000)
                        except queue.Empty:
                            return b''
                    def __enter__(self):
                        return self
                    def __exit__(self, *_args):
                        pass

                with tempfile.TemporaryDirectory() as temporary, patch(
                        'goggles_bridge.engine.prioritize_gpu', return_value=applied) as prioritize:
                    engine = BridgeEngine(replace(self.settings(), low_latency=False), Path(temporary)/'log.jsonl',
                        stop_event=stop, duration=2, reconnect=False, gpu_priority_class=requested,
                        transport_factory=lambda _dll: Usb(), process_factory=lambda *_a, **_k: encoder,
                        on_event=events.append)
                    engine.run()
                self.assertEqual(video_count[0], 3)
                prioritize.assert_called_once_with(encoder, requested)
                row, = [event for event in events if event['event'] == 'streaming']
                self.assertEqual(row['gpu_priority_class'], requested)
                self.assertEqual(row['gpu_priority_applied'], applied)
                self.assertEqual(row['gpu_realtime'], applied and requested == 5)
                self.assertTrue(encoder_stopped.is_set())
