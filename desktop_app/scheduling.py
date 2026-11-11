"""Per-encoder Windows QoS policy, without changing system power settings.

CPU priority is selected separately when creating FFmpeg. This module neither
changes CPU/GPU priority nor adds a timer request, and never targets the parent.
The owned FFmpeg process's lifetime bounds these settings.
"""
import ctypes as C
import sys


# High, not Realtime: the desktop compositor and virtual display also need GPU
# execution time. Paired 100 fps measurements found repeated 30-46 ms output
# gaps at Realtime, while High and Normal avoided those tails on the same host.
# This is a per-encoder request, never a global driver setting.
STREAM_GPU_PRIORITY_CLASS = 4


# Win32 ABI: ULONG is 32-bit on both 32-bit and 64-bit Windows.
class _PowerThrottlingState(C.Structure):
    _fields_ = [('Version', C.c_uint32), ('ControlMask', C.c_uint32),
                ('StateMask', C.c_uint32)]


_PROCESS_POWER_THROTTLING = 4
_CURRENT_VERSION = 1
_EXECUTION_SPEED = 0x1
_IGNORE_TIMER_RESOLUTION = 0x4


def _load_kernel32():
    return C.WinDLL('kernel32', use_last_error=True)


def _last_error():
    return C.get_last_error()


def configure_encoder_process(process):
    """Best-effort HighQoS/timer policy for an already-created Popen child.

    Returns diagnostic metadata even if the API or a flag is unsupported.
    Callers must not interpret a failed setting as an encoder failure.

    Microsoft's documented HighQoS policy uses EXECUTION_SPEED in ControlMask
    and zero in StateMask. Disabling IGNORE_TIMER_RESOLUTION honors the child's
    timer-resolution requests; it does not itself create a timer request or
    guarantee a deadline. ControlMask=0 would restore system-managed policy.
    https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setprocessinformation
    https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/ne-processthreadsapi-process_information_class
    """
    result = dict(status='not_windows', execution_speed_throttling_disabled=False,
                  timer_resolution_throttling_disabled=False, attempts=[])
    if sys.platform != 'win32':
        return result
    try:
        handle = getattr(process, '_handle', None)
        if handle is None:
            result['status'] = 'no_process_handle'
            return result
        if getattr(handle, 'closed', False):
            result['status'] = 'invalid_process_handle'
            return result
        handle = int(handle)
        # Reject NULL, closed and pseudo handles; never fall back to the caller
        # or a PID lookup that could race with process exit/PID reuse.
        if not 0 < handle < (1 << (C.sizeof(C.c_void_p)*8))-1:
            result['status'] = 'invalid_process_handle'
            return result
        kernel = _load_kernel32()
        setter = getattr(kernel, 'SetProcessInformation', None)
        if setter is None:
            result['status'] = 'api_unavailable'
            return result
        setter.argtypes = [C.c_void_p, C.c_int, C.c_void_p, C.c_uint32]
        setter.restype = C.c_int
        result['status'] = 'failed'
        # Older Windows can expose the API without supporting the newer timer
        # bit. Retry only EXECUTION_SPEED instead of discarding HighQoS as well.
        for mask in (_EXECUTION_SPEED | _IGNORE_TIMER_RESOLUTION, _EXECUTION_SPEED):
            state = _PowerThrottlingState(_CURRENT_VERSION, mask, 0)
            try:
                success = bool(setter(handle, _PROCESS_POWER_THROTTLING,
                                      C.byref(state), C.sizeof(state)))
                attempt = dict(control_mask=mask, success=success,
                               winerror=0 if success else _last_error())
            except Exception as exc:
                attempt = dict(control_mask=mask, success=False,
                               error_type=type(exc).__name__,
                               winerror=getattr(exc, 'winerror', None))
                success = False
            result['attempts'].append(attempt)
            if success:
                result['execution_speed_throttling_disabled'] = True
                result['timer_resolution_throttling_disabled'] = bool(mask & _IGNORE_TIMER_RESOLUTION)
                result['status'] = 'configured' if mask & _IGNORE_TIMER_RESOLUTION else 'execution_only'
                break
    except Exception as exc:
        # An unavailable Win32 entry point or a child that already exited must
        # not prevent streaming or hide the encoder's own diagnostic outcome.
        result.update(status='failed', error_type=type(exc).__name__,
                      winerror=getattr(exc, 'winerror', None))
    return result
