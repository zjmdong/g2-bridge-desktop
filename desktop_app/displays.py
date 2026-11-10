"""Windows display inventory and targeted layout changes, independent of the SDK."""
import ctypes as C
from ctypes import wintypes as W
import time


class DisplayError(RuntimeError):
    pass


class DISPLAY_DEVICE(C.Structure):
    _fields_ = [('cb', W.DWORD), ('DeviceName', W.WCHAR*32), ('DeviceString', W.WCHAR*128),
                ('StateFlags', W.DWORD), ('DeviceID', W.WCHAR*128), ('DeviceKey', W.WCHAR*128)]


class DEVMODE(C.Structure):
    _fields_ = [('dmDeviceName', W.WCHAR*32), ('dmSpecVersion', W.WORD), ('dmDriverVersion', W.WORD),
                ('dmSize', W.WORD), ('dmDriverExtra', W.WORD), ('dmFields', W.DWORD),
                ('x', W.LONG), ('y', W.LONG), ('orientation', W.DWORD), ('fixedOutput', W.DWORD),
                ('dmColor', W.SHORT), ('dmDuplex', W.SHORT), ('dmYResolution', W.SHORT),
                ('dmTTOption', W.SHORT), ('dmCollate', W.SHORT), ('dmFormName', W.WCHAR*32),
                ('dmLogPixels', W.WORD), ('dmBitsPerPel', W.DWORD), ('dmPelsWidth', W.DWORD),
                ('dmPelsHeight', W.DWORD), ('dmDisplayFlags', W.DWORD), ('dmDisplayFrequency', W.DWORD),
                ('dmICMMethod', W.DWORD), ('dmICMIntent', W.DWORD), ('dmMediaType', W.DWORD),
                ('dmDitherType', W.DWORD), ('dmReserved1', W.DWORD), ('dmReserved2', W.DWORD),
                ('dmPanningWidth', W.DWORD), ('dmPanningHeight', W.DWORD)]


class MONITORINFO(C.Structure):
    _fields_ = [('cbSize', W.DWORD), ('rcMonitor', W.RECT), ('rcWork', W.RECT),
                ('dwFlags', W.DWORD), ('szDevice', W.WCHAR*32)]


def api():
    user = C.WinDLL('user32', use_last_error=True)
    user.EnumDisplayDevicesW.argtypes = [W.LPCWSTR, W.DWORD, C.POINTER(DISPLAY_DEVICE), W.DWORD]
    user.EnumDisplaySettingsExW.argtypes = [W.LPCWSTR, W.DWORD, C.POINTER(DEVMODE), W.DWORD]
    user.ChangeDisplaySettingsExW.argtypes = [W.LPCWSTR, C.POINTER(DEVMODE), W.HWND, W.DWORD, C.c_void_p]
    user.GetMonitorInfoW.argtypes = [W.HMONITOR, C.POINTER(MONITORINFO)]
    return user


def mode(device, number=0xFFFFFFFF):
    value = DEVMODE(dmSize=C.sizeof(DEVMODE))
    return value if api().EnumDisplaySettingsExW(device, number, C.byref(value), 0) else None


def inventory():
    user = api()
    handles = {}
    callback = C.WINFUNCTYPE(W.BOOL, W.HMONITOR, W.HDC, C.POINTER(W.RECT), W.LPARAM)

    @callback
    def monitor(handle, _dc, _rect, _data):
        info = MONITORINFO(cbSize=C.sizeof(MONITORINFO))
        if user.GetMonitorInfoW(handle, C.byref(info)):
            handles[info.szDevice] = int(handle)
        return True

    user.EnumDisplayMonitors.argtypes = [W.HDC, C.c_void_p, callback, W.LPARAM]
    user.EnumDisplayMonitors(None, None, monitor, 0)
    result = []
    index = 0
    while True:
        device = DISPLAY_DEVICE(cb=C.sizeof(DISPLAY_DEVICE))
        if not user.EnumDisplayDevicesW(None, index, C.byref(device), 0):
            break
        index += 1
        if device.StateFlags & 8:  # Legacy mirroring drivers are not displays.
            continue
        current = mode(device.DeviceName)
        monitor_device = DISPLAY_DEVICE(cb=C.sizeof(DISPLAY_DEVICE))
        user.EnumDisplayDevicesW(device.DeviceName, 0, C.byref(monitor_device), 0)
        result.append(dict(device=device.DeviceName, adapter=device.DeviceString,
            hardware_id=device.DeviceID, monitor=monitor_device.DeviceString,
            monitor_id=monitor_device.DeviceID, active=bool(device.StateFlags & 1),
            primary=bool(device.StateFlags & 4), hmonitor=handles.get(device.DeviceName),
            width=current.dmPelsWidth if current else 0, height=current.dmPelsHeight if current else 0,
            x=current.x if current else 0, y=current.y if current else 0,
            hz=current.dmDisplayFrequency if current else 0))
    return result


def virtual_display(rows=None):
    candidates = [r for r in (inventory() if rows is None else rows)
                  if r['hardware_id'].lower() in ('root\\mttvdd','mttvdd') and r['monitor_id']]
    if len(candidates) != 1:
        raise DisplayError('未找到唯一的虚拟显示器。请安装扩展屏驱动；已有多个同类显示器时请先在 Windows 中确认配置。')
    return candidates[0]


def select_source(source):
    rows = inventory()
    if source == 'extended':
        target = virtual_display(rows)
        if not target['active'] or not target['hmonitor']:
            raise DisplayError('独立扩展屏尚未启用，请点击「启用 1080p 扩展屏」。')
        if (target['width'], target['height'], target['hz']) != (1920, 1080, 60) or target['primary']:
            raise DisplayError('扩展屏应为非主屏的 1920 × 1080 / 60 Hz 显示器，请重新启用扩展屏。')
    else:
        target = next((r for r in rows if r['primary'] and r['hmonitor']), None)
        if target is None:
            raise DisplayError('未找到活动主显示器。请保持桌面解锁。')
    return target


def enable_extended():
    before = inventory()
    target = virtual_display(before)
    if target['primary']:
        raise DisplayError('虚拟显示器目前被设为主屏，请先在 Windows 显示设置中恢复实体主屏。')
    active = [r for r in before if r['active'] and r['device'] != target['device']]
    original_modes = {r['device']: mode(r['device']) for r in before if r['active']}
    if not active:
        raise DisplayError('需要保留至少一个活动的实体显示器。')
    desired = None
    for index in range(1000):
        candidate = mode(target['device'], index)
        if candidate is None:
            break
        if (candidate.dmPelsWidth, candidate.dmPelsHeight, candidate.dmDisplayFrequency) == (1920,1080,60):
            desired = candidate
            break
    if desired is None:
        raise DisplayError('虚拟驱动没有提供 1920 × 1080 / 60 Hz 模式。')
    desired.x = max(r['x']+r['width'] for r in active)
    desired.y = next(r['y'] for r in active if r['primary'])
    desired.dmFields |= 0x20 | 0x80000 | 0x100000 | 0x400000  # position, width, height, frequency
    rollback = None
    legacy_changed = False
    try:
        if target['active']:
            status = api().ChangeDisplaySettingsExW(target['device'], C.byref(desired), None, 3, None)
            if status != 0:
                raise DisplayError(f'Windows 拒绝扩展屏模式（{status}）。')
            legacy_changed = True
            status = api().ChangeDisplaySettingsExW(target['device'], C.byref(desired), None, 1, None)
            if status != 0:
                raise DisplayError(f'Windows 无法启用扩展屏（{status}）。')
        else:
            from .display_config import attach
            rollback = attach(target['device'], 1920, 1080, 60, desired.x, desired.y)
        deadline = time.monotonic()+8
        while time.monotonic() < deadline:
            after = inventory()
            for original in active:
                now = next((r for r in after if r['device'] == original['device']), {})
                if any(now.get(k) != original[k] for k in ('width','height','hz','x','y','primary','active')):
                    raise DisplayError('Windows 改变了原有显示布局，已尝试恢复；请在显示设置中检查。')
            current = next((r for r in after if r['device'] == target['device']), {})
            if not current.get('active') or not current.get('hmonitor'):
                time.sleep(.2)
                continue
            result = select_source('extended')
            return result
        raise DisplayError('扩展屏未能按预期启用，请打开 Windows 显示设置检查。')
    except Exception:
        if rollback is not None:
            rollback()
            raise
        if not legacy_changed:
            raise
        # Stage a rollback of the exact pre-change modes, then apply together.
        for device, original in original_modes.items():
            if original:
                api().ChangeDisplaySettingsExW(device, C.byref(original), None, 0x10000001, None)
        if target['device'] not in original_modes:
            detached = DEVMODE(dmSize=C.sizeof(DEVMODE),dmFields=0x20 | 0x80000 | 0x100000)
            api().ChangeDisplaySettingsExW(target['device'],C.byref(detached),None,0x10000001,None)
        api().ChangeDisplaySettingsExW(None,None,None,0,None)
        raise


def disable_extended():
    target = virtual_display()
    if target['primary'] or not any(r['active'] and r['device'] != target['device'] for r in inventory()):
        raise DisplayError('无法断开主屏或唯一的活动显示器。')
    if not target['active']:
        return
    value = DEVMODE(dmSize=C.sizeof(DEVMODE), dmFields=0x20 | 0x80000 | 0x100000)
    status = api().ChangeDisplaySettingsExW(target['device'], C.byref(value), None, 1, None)
    if status != 0:
        raise DisplayError(f'Windows 无法断开扩展屏（{status}）。')
