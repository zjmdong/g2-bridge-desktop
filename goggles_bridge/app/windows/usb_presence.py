"""Read PnP presence without claiming the USB interface or sending control traffic."""
import ctypes as C
from ctypes import wintypes as W
import hashlib

from goggles_bridge.usb_transport import INTERFACE, PRODUCT_ID, VENDOR_ID


class INFO(C.Structure):
    _fields_ = [('size', W.DWORD), ('guid', C.c_byte * 16), ('instance', W.DWORD), ('reserved', C.c_size_t)]


def present_interfaces():
    api = C.WinDLL('setupapi', use_last_error=True)
    api.SetupDiGetClassDevsW.argtypes = [C.c_void_p, W.LPCWSTR, W.HWND, W.DWORD]
    api.SetupDiGetClassDevsW.restype = W.HANDLE
    api.SetupDiEnumDeviceInfo.argtypes = [W.HANDLE, W.DWORD, C.POINTER(INFO)]
    api.SetupDiGetDeviceInstanceIdW.argtypes = [W.HANDLE, C.POINTER(INFO), W.LPWSTR, W.DWORD, C.c_void_p]
    api.SetupDiDestroyDeviceInfoList.argtypes = [W.HANDLE]
    handle = api.SetupDiGetClassDevsW(None, 'USB', None, 6)  # PRESENT | ALLCLASSES
    if handle == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    found = []
    try:
        for index in range(4096):
            item = INFO(size=C.sizeof(INFO))
            if not api.SetupDiEnumDeviceInfo(handle, index, C.byref(item)):
                error = C.get_last_error()
                if error == 259:
                    break
                raise C.WinError(error)
            value = C.create_unicode_buffer(1024)
            if api.SetupDiGetDeviceInstanceIdW(handle, C.byref(item), value, 1024, None):
                identity = value.value.upper()
                if (identity.startswith(f'USB\\VID_{VENDOR_ID:04X}&PID_{PRODUCT_ID:04X}')
                        and f'&MI_{INTERFACE:02X}\\' in identity):
                    found.append(identity)
    finally:
        api.SetupDiDestroyDeviceInfoList(handle)
    return tuple(sorted(found))


def watch(stop, emit):
    previous = None
    while not stop.is_set():
        current = present_interfaces()
        if current != previous:
            emit('usb_presence', connected=bool(current), count=len(current),
                 token=hashlib.sha256('\n'.join(current).encode()).hexdigest()[:12] if current else '')
            previous = current
        stop.wait(.25)
