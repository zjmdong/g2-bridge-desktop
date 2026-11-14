"""Resolve a Windows display to its DXGI adapter/output for borderless capture."""
import ctypes as C
from ctypes import wintypes as W
import uuid


class LUID(C.Structure):
    _fields_ = [('low', W.DWORD), ('high', W.LONG)]


class ADAPTER_DESC1(C.Structure):
    # SIZE_T fields require native pointer alignment (312 bytes on Windows x64).
    _fields_ = [('name', W.WCHAR * 128), ('vendor', W.UINT), ('device', W.UINT),
                ('subsystem', W.UINT), ('revision', W.UINT),
                ('dedicated_video', C.c_size_t), ('dedicated_system', C.c_size_t),
                ('shared_system', C.c_size_t), ('luid', LUID), ('flags', W.UINT)]


class OUTPUT_DESC(C.Structure):
    _fields_ = [('name', W.WCHAR * 32), ('rect', W.RECT), ('attached', W.BOOL),
                ('rotation', W.UINT), ('monitor', W.HMONITOR)]


def method(pointer, index, result, *arguments):
    table = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p))).contents
    return C.WINFUNCTYPE(result, C.c_void_p, *arguments)(table[index])


def outputs():
    factory = C.c_void_p()
    iid = (C.c_byte * 16).from_buffer_copy(uuid.UUID('770aae78-f26f-4dba-a829-253c83d1b387').bytes_le)
    create = C.WinDLL('dxgi').CreateDXGIFactory1
    create.argtypes = [C.c_void_p, C.POINTER(C.c_void_p)]
    create.restype = W.LONG
    code = create(iid, C.byref(factory))
    if code:
        raise RuntimeError(f'无法读取显卡输出（DXGI {code:#x}）。')
    rows = []
    try:
        for adapter_index in range(32):
            adapter = C.c_void_p()
            code = method(factory, 12, W.LONG, W.UINT, C.POINTER(C.c_void_p))(
                factory, adapter_index, C.byref(adapter))
            if code == -2005270526:  # DXGI_ERROR_NOT_FOUND
                break
            if code:
                raise RuntimeError(f'无法枚举显卡（DXGI {code:#x}）。')
            try:
                description = ADAPTER_DESC1()
                code = method(adapter, 10, W.LONG, C.POINTER(ADAPTER_DESC1))(
                    adapter, C.byref(description))  # IDXGIAdapter1::GetDesc1
                if code:
                    raise RuntimeError(f'无法读取采集显卡信息（DXGI {code:#x}）。')
                # LUID identifies this DXGI adapter, not a CUDA/NVENC device index.
                # Metadata is sampled at session setup, never in the video loop.
                metadata = dict(gpu_name=description.name, vendor_id=int(description.vendor),
                    adapter_luid=f'{description.luid.high & 0xffffffff:08x}:{description.luid.low:08x}')
                for output_index in range(32):
                    output = C.c_void_p()
                    code = method(adapter, 7, W.LONG, W.UINT, C.POINTER(C.c_void_p))(
                        adapter, output_index, C.byref(output))
                    if code == -2005270526:
                        break
                    if code:
                        raise RuntimeError(f'无法枚举显示输出（DXGI {code:#x}）。')
                    try:
                        value = OUTPUT_DESC()
                        code = method(output, 7, W.LONG, C.POINTER(OUTPUT_DESC))(output, C.byref(value))
                        if code:
                            raise RuntimeError(f'无法读取显示输出（DXGI {code:#x}）。')
                        if value.attached:
                            rows.append(dict(device=value.name, adapter=adapter_index,
                                             output=output_index, hmonitor=value.monitor,
                                             width=value.rect.right-value.rect.left,
                                             height=value.rect.bottom-value.rect.top, **metadata))
                    finally:
                        method(output, 2, W.ULONG)(output)
            finally:
                method(adapter, 2, W.ULONG)(adapter)
    finally:
        method(factory, 2, W.ULONG)(factory)
    return rows


def select_output(device):
    matches = [r for r in outputs() if r['device'] == device]
    if len(matches) != 1:
        raise RuntimeError('无法唯一定位无边框采集的显示输出，请检查显示驱动。')
    return matches[0]
