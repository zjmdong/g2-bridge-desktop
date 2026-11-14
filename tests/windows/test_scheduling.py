"""Exercise Win32 policy arguments without touching any real process policy."""
import ctypes as C
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from goggles_bridge.app.windows import scheduling


class FakeSetter:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []

    def __call__(self, handle, information_class, pointer, size):
        state = C.cast(pointer, C.POINTER(scheduling._PowerThrottlingState)).contents
        self.calls.append((handle, information_class, size,
                           state.Version, state.ControlMask, state.StateMask))
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class EncoderSchedulingTests(unittest.TestCase):
    def configure(self, outcomes, *, errors=()):
        setter = FakeSetter(outcomes)
        kernel = SimpleNamespace(SetProcessInformation=setter)
        with patch.object(scheduling.sys, 'platform', 'win32'), \
             patch.object(scheduling, '_load_kernel32', return_value=kernel), \
             patch.object(scheduling, '_last_error', side_effect=errors):
            result = scheduling.configure_encoder_process(SimpleNamespace(_handle=1234))
        return result, setter.calls

    def test_disables_both_policies_for_the_owned_child_only(self):
        result, calls = self.configure([1])
        self.assertEqual(calls, [(1234, 4, 12, 1, 5, 0)])
        self.assertEqual(result['status'], 'configured')
        self.assertTrue(result['execution_speed_throttling_disabled'])
        self.assertTrue(result['timer_resolution_throttling_disabled'])
        self.assertEqual(result['attempts'], [dict(control_mask=5, success=True, winerror=0)])

    def test_unsupported_timer_flag_falls_back_to_execution_speed_only(self):
        result, calls = self.configure([0, 1], errors=[87])
        self.assertEqual(calls, [(1234, 4, 12, 1, 5, 0), (1234, 4, 12, 1, 1, 0)])
        self.assertEqual(result['status'], 'execution_only')
        self.assertTrue(result['execution_speed_throttling_disabled'])
        self.assertFalse(result['timer_resolution_throttling_disabled'])
        self.assertEqual([entry['winerror'] for entry in result['attempts']], [87, 0])

    def test_rejected_settings_return_diagnostics_without_claiming_success(self):
        result, calls = self.configure([0, 0], errors=[87, 5])
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['execution_speed_throttling_disabled'])
        self.assertFalse(result['timer_resolution_throttling_disabled'])
        self.assertEqual([entry['winerror'] for entry in result['attempts']], [87, 5])

    def test_native_call_exception_is_best_effort_and_can_fall_back(self):
        result, calls = self.configure([OSError('unsupported flags'), 1])
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['status'], 'execution_only')
        self.assertEqual(result['attempts'][0]['error_type'], 'OSError')

    def test_missing_api_or_library_does_not_raise(self):
        with patch.object(scheduling.sys, 'platform', 'win32'):
            with patch.object(scheduling, '_load_kernel32', return_value=SimpleNamespace()):
                result = scheduling.configure_encoder_process(SimpleNamespace(_handle=1234))
                self.assertEqual(result['status'], 'api_unavailable')
                self.assertEqual(result['attempts'], [])
            with patch.object(scheduling, '_load_kernel32', side_effect=OSError('unavailable')):
                result = scheduling.configure_encoder_process(SimpleNamespace(_handle=1234))
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['error_type'], 'OSError')

    def test_other_platforms_do_not_load_or_call_win32(self):
        for platform in ('linux', 'darwin'):
            with self.subTest(platform=platform), \
                 patch.object(scheduling.sys, 'platform', platform), \
                 patch.object(scheduling, '_load_kernel32') as load:
                result = scheduling.configure_encoder_process(SimpleNamespace(_handle=1234))
                self.assertEqual(result['status'], 'not_windows')
                self.assertEqual(result['attempts'], [])
                load.assert_not_called()

    def test_missing_or_pseudo_handles_never_target_the_parent(self):
        class ClosedHandle(int):
            closed = True
        for handle in (None, 0, -1, (1 << (C.sizeof(C.c_void_p)*8))-1, ClosedHandle(1234)):
            with self.subTest(handle=handle), \
                 patch.object(scheduling.sys, 'platform', 'win32'), \
                 patch.object(scheduling, '_load_kernel32') as load:
                result = scheduling.configure_encoder_process(SimpleNamespace(_handle=handle))
                self.assertIn(result['status'], ('no_process_handle', 'invalid_process_handle'))
                self.assertEqual(result['attempts'], [])
                load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
