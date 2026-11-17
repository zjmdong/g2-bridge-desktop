"""Best-effort HighQoS for the owned encoder, without system-wide changes."""
import ctypes as C


class PowerThrottlingState(C.Structure):
    _fields_ = [('Version', C.c_uint32), ('ControlMask', C.c_uint32), ('StateMask', C.c_uint32)]


def configure_encoder_process(process):
    try:
        setter = C.WinDLL('kernel32').SetProcessInformation
        setter.argtypes = [C.c_void_p, C.c_int, C.c_void_p, C.c_uint32]
        setter.restype = C.c_int
        # Disable execution-speed and timer-resolution throttling. Older Windows
        # versions may only accept the execution-speed flag.
        for mask in (5, 1):
            state = PowerThrottlingState(1, mask, 0)
            if setter(int(process._handle), 4, C.byref(state), C.sizeof(state)):
                break
    except (OSError, AttributeError):
        pass
