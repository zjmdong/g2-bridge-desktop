"""List attached displays in the order the screen capture numbers them."""
import ctypes as C
import sys


def list_displays():
    """Return dicts of index, name, x, y, width, height, hz, and primary, in physical pixels."""
    if sys.platform == 'darwin':
        return _mac_displays()
    if sys.platform != 'win32':
        return [dict(index=0, name='Display 1', x=0, y=0, width=1920, height=1080, hz=0, primary=True)]
    from ctypes import wintypes as W

    class MonitorInfo(C.Structure):
        _fields_ = [('cbSize', W.DWORD), ('rcMonitor', W.RECT), ('rcWork', W.RECT),
                    ('dwFlags', W.DWORD), ('szDevice', W.WCHAR*32)]

    class DevMode(C.Structure):
        # DEVMODEW with the display branch of its union
        _fields_ = [('dmDeviceName', W.WCHAR*32), ('dmSpecVersion', W.WORD), ('dmDriverVersion', W.WORD),
                    ('dmSize', W.WORD), ('dmDriverExtra', W.WORD), ('dmFields', W.DWORD),
                    ('dmPositionX', W.LONG), ('dmPositionY', W.LONG), ('dmDisplayOrientation', W.DWORD),
                    ('dmDisplayFixedOutput', W.DWORD), ('dmColor', W.SHORT), ('dmDuplex', W.SHORT),
                    ('dmYResolution', W.SHORT), ('dmTTOption', W.SHORT), ('dmCollate', W.SHORT),
                    ('dmFormName', W.WCHAR*32), ('dmLogPixels', W.WORD), ('dmBitsPerPel', W.DWORD),
                    ('dmPelsWidth', W.DWORD), ('dmPelsHeight', W.DWORD), ('dmDisplayFlags', W.DWORD),
                    ('dmDisplayFrequency', W.DWORD), ('dmICMMethod', W.DWORD), ('dmICMIntent', W.DWORD),
                    ('dmMediaType', W.DWORD), ('dmDitherType', W.DWORD), ('dmReserved1', W.DWORD),
                    ('dmReserved2', W.DWORD), ('dmPanningWidth', W.DWORD), ('dmPanningHeight', W.DWORD)]

    user32 = C.WinDLL('user32')
    callback = C.WINFUNCTYPE(W.BOOL, W.HMONITOR, W.HDC, C.POINTER(W.RECT), W.LPARAM)
    user32.EnumDisplayMonitors.argtypes = [W.HDC, C.POINTER(W.RECT), callback, W.LPARAM]
    user32.GetMonitorInfoW.argtypes = [W.HMONITOR, C.POINTER(MonitorInfo)]
    user32.EnumDisplaySettingsW.argtypes = [W.LPCWSTR, W.DWORD, C.POINTER(DevMode)]
    displays = []

    def visit(monitor, _dc, _rect, _param):
        info = MonitorInfo(cbSize=C.sizeof(MonitorInfo))
        mode = DevMode(dmSize=C.sizeof(DevMode))
        if user32.GetMonitorInfoW(monitor, C.byref(info)) and user32.EnumDisplaySettingsW(
                info.szDevice, 0xFFFFFFFF, C.byref(mode)):  # ENUM_CURRENT_SETTINGS
            displays.append(dict(index=len(displays), name=f'Display {len(displays)+1}',
                                 device=info.szDevice, hmonitor=monitor,
                                 x=mode.dmPositionX, y=mode.dmPositionY,
                                 width=mode.dmPelsWidth, height=mode.dmPelsHeight,
                                 hz=mode.dmDisplayFrequency, primary=bool(info.dwFlags & 1)))
        else:
            # keep the capture numbering even when a display cannot be measured
            displays.append(dict(index=len(displays), name=f'Display {len(displays)+1}',
                                 x=0, y=0, width=1920, height=1080, hz=0, primary=False))
        return True

    user32.EnumDisplayMonitors(None, None, callback(visit), 0)
    # Identify only this app's owned virtual output, not every software monitor.
    try:
        from .windows.displays import inventory
        from .windows.virtual_driver import status
        virtual = {r['device'] for r in inventory() if r['hardware_id'].lower() in ('root\\mttvdd', 'mttvdd')}
        if len(virtual) != 1 or not status().get('owned'):
            virtual = set()
        for display in displays:
            display['virtual'] = display.get('device') in virtual
    except (OSError, RuntimeError, KeyError):
        pass
    return displays


def _mac_displays():
    """CGGetActiveDisplayList order, main display first, which the capture helper's --display follows."""
    class Rect(C.Structure):
        _fields_ = [('x', C.c_double), ('y', C.c_double), ('width', C.c_double), ('height', C.c_double)]

    cg = C.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    cg.CGDisplayBounds.restype = Rect
    cg.CGDisplayCopyDisplayMode.restype = C.c_void_p
    cg.CGDisplayModeGetPixelWidth.argtypes = cg.CGDisplayModeGetPixelHeight.argtypes = [C.c_void_p]
    cg.CGDisplayModeGetPixelWidth.restype = cg.CGDisplayModeGetPixelHeight.restype = C.c_size_t
    cg.CGDisplayModeGetRefreshRate.argtypes, cg.CGDisplayModeGetRefreshRate.restype = [C.c_void_p], C.c_double
    cg.CGDisplayModeRelease.argtypes = [C.c_void_p]
    ids, count = (C.c_uint32*16)(), C.c_uint32()
    if cg.CGGetActiveDisplayList(16, ids, C.byref(count)):
        return []
    displays = []
    for index, display in enumerate(ids[:count.value]):
        bounds, mode = cg.CGDisplayBounds(display), cg.CGDisplayCopyDisplayMode(display)
        width, height, hz = 1920, 1080, 0
        if mode:
            width, height = cg.CGDisplayModeGetPixelWidth(mode), cg.CGDisplayModeGetPixelHeight(mode)
            hz = round(cg.CGDisplayModeGetRefreshRate(mode))
            cg.CGDisplayModeRelease(mode)
        displays.append(dict(index=index, name=f'Display {index+1}', x=int(bounds.x), y=int(bounds.y),
                             width=width, height=height, hz=hz, primary=bool(cg.CGDisplayIsMain(display))))
    return displays
