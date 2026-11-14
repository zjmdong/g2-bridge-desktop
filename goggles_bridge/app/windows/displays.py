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
        result.append(dict(device=device.DeviceName, id=device.DeviceName,
            name=monitor_device.DeviceString or device.DeviceString, adapter=device.DeviceString,
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


def select_source(source, width=1920, height=1080, hz=60, *, device=None):
    rows = inventory()
    if source in ('extended', 'virtual'):
        target = virtual_display(rows)
        if not target['active'] or not target['hmonitor']:
            raise DisplayError('独立扩展屏未能创建，请停止串流后重试，或检查扩展屏驱动。')
        if (target['width'], target['height'], target['hz']) != (width, height, hz) or target['primary']:
            raise DisplayError(f'扩展屏应为非主屏的 {width} × {height} / {hz} Hz 显示器。')
    elif source in ('primary', 'display'):
        target = next((r for r in rows if r['active'] and r['hmonitor'] and
                       (r['device'] == device if device else r['primary'])), None)
        if target is None:
            raise DisplayError('选择的显示器已断开。请重新选择画面来源。' if device else
                               '未找到活动主显示器。请保持桌面解锁。')
    else:
        raise DisplayError('Unsupported display source')
    return target


def capture_diagnostics(target, output):
    """Describe the known capture path without guessing the game's render GPU.

    This pure helper is safe for startup logging; never use CIM or GPU tests in
    the streaming loop. A capture LUID is not proof of the game's render LUID.
    """
    vendor = output.get('vendor_id')
    direct = vendor == 0x10de
    known = vendor is not None
    return dict(capture_gpu=output.get('gpu_name'), capture_adapter_luid=output.get('adapter_luid'),
                capture_gpu_path='d3d11_nvenc' if direct else 'cpu_transfer_to_nvenc' if known else 'unknown',
                cross_adapter_transfer=not direct if known else None,
                source_hz=target.get('hz'), source_refresh=target.get('refresh_rate'),
                render_gpu_verified=False,
                warning=('采集显示器位于其他 GPU，需要经系统内存传到 NVIDIA，可能增加延迟。'
                         if known and not direct else ''))


def _require_owned_driver():
    from .virtual_driver import status
    if not status().get('owned'):
        raise DisplayError('未找到由本客户端管理的扩展屏配置；不会更改其他软件的虚拟显示器。')


def enable_extended(width=1920, height=1080, hz=60):
    if (width, height) not in ((1280, 720), (1920, 1080)) or hz not in (60, 75, 90, 100):
        raise DisplayError('Unsupported virtual display mode')
    _require_owned_driver()
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
        if (candidate.dmPelsWidth, candidate.dmPelsHeight, candidate.dmDisplayFrequency) == (width,height,hz):
            desired = candidate
            break
    if desired is None:
        raise DisplayError(f'虚拟驱动没有提供 {width} × {height} / {hz} Hz 模式，请更新扩展屏驱动配置。')
    desired.x = max(r['x']+r['width'] for r in active)
    primary = next((r for r in active if r['primary']), None)
    if primary is None:
        raise DisplayError('没有可保留的实体主显示器，未改变显示布局。')
    desired.y = primary['y']
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
            rollback = attach(target['device'], width, height, hz, desired.x, desired.y)
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
            result = select_source('extended', width, height, hz)
            return result
        raise DisplayError('扩展屏未能按预期启用，请打开 Windows 显示设置检查。')
    except Exception as exc:
        if rollback is not None:
            try:
                rollback()
            except Exception as rollback_error:
                if hasattr(exc, 'add_note'):
                    exc.add_note(f'原显示布局回滚未完成：{rollback_error}')
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


def disable_extended(*, expected=None):
    rows = inventory()
    if expected and not any(r['hardware_id'].lower() in ('root\\mttvdd', 'mttvdd')
                            and r['monitor_id'] for r in rows):
        return  # The leased monitor was already removed; there is nothing to detach.
    _require_owned_driver()
    target = virtual_display(rows)
    if expected and any(target.get(key) != expected.get(key)
                        for key in ('device', 'hardware_id', 'monitor_id')):
        raise DisplayError('扩展屏设备身份已改变，未断开新的显示器。')
    if target['primary'] or not any(r['active'] and r['device'] != target['device'] for r in rows):
        raise DisplayError('无法断开主屏或唯一的活动显示器。')
    if not target['active']:
        return
    value = DEVMODE(dmSize=C.sizeof(DEVMODE), dmFields=0x20 | 0x80000 | 0x100000)
    status = api().ChangeDisplaySettingsExW(target['device'], C.byref(value), None, 1, None)
    if status != 0:
        raise DisplayError(f'Windows 无法断开扩展屏（{status}）。')
