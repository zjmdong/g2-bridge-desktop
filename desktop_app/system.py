"""Windows inventory and process helpers. No SDK implementation is patched."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time

from goggles_bridge.usb_transport import find_dll, VERIFIED_DLL_SHA256
from .paths import ffmpeg_path

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class Cancelled(Exception):
    pass


def run_cancellable(command, stop, timeout=30, **kwargs):
    # Adapter for SDK check_encoder's subprocess.run injection point.
    kwargs.pop('capture_output', None)
    kwargs.pop('text', None)
    kwargs.pop('errors', None)
    kwargs.setdefault('creationflags', NO_WINDOW)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    deadline = time.monotonic()+timeout
    try:
        while True:
            if stop.is_set():
                raise Cancelled()
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                out, err = process.communicate(timeout=.1)
                return subprocess.CompletedProcess(command, process.returncode,
                    out.decode('utf-8', errors='replace'), err.decode('utf-8', errors='replace'))
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def powershell_json(script, timeout=15):
    executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    env = os.environ.copy()
    # A terminal using PowerShell 7 may pass its incompatible modules to the
    # system Windows PowerShell 5.1 child. Only load that child's own modules.
    env['PSModulePath'] = str(executable.parent / 'Modules')
    result = subprocess.run([str(executable), '-NoProfile', '-NonInteractive', '-Command',
        '[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); '+script],
        capture_output=True, timeout=timeout, creationflags=NO_WINDOW, env=env)
    if result.returncode:
        raise RuntimeError('Windows 系统信息查询失败')
    return json.loads(result.stdout.decode('utf-8-sig').strip() or 'null')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def driver_status():
    dll = find_dll()
    if not dll.is_file():
        return dict(status='missing', title='需要 DJI USB 驱动', version=None,
                    message='安装经过 SDK 验证的 5.0.0.7 驱动，然后连接眼镜。')
    try:
        valid = sha256(dll) == VERIFIED_DLL_SHA256
    except OSError:
        valid = False
    return dict(status='verified' if valid else 'unsupported',
                title='DJI USB 组件已验证' if valid else 'DJI USB 组件不匹配',
                version='5.0.0.7' if valid else None,
                message='已通过 SDK 的 DLL 校验；连接时继续检查设备接口与驱动绑定。' if valid else
                        '当前 DLL 与 SDK 验证版本不同。请通过驱动设置修复，不能直接绕过校验。')


def environment(stop):
    driver = driver_status()
    encoder = ffmpeg_path()
    result = dict(os=f'Windows {platform.release()} ({platform.machine()})',
                  driver=driver, ffmpeg=encoder.is_file(), gpu=[], encoder_ok=False,
                  encoder_message='', supported_os=os.name == 'nt' and ctypes.sizeof(ctypes.c_void_p) == 8
                  and os.environ.get('PROCESSOR_ARCHITEW6432', platform.machine()).upper() in ('AMD64', 'X86_64'))
    try:
        gpu = powershell_json('Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion | ConvertTo-Json -Compress')
        result['gpu'] = gpu if isinstance(gpu, list) else [gpu] if gpu else []
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        result['gpu'] = []
    if not result['supported_os']:
        result['encoder_message'] = '0.1.0 仅支持 Windows x64。'
    elif not encoder.is_file():
        result['encoder_message'] = '内置 FFmpeg 缺失，请重新安装客户端。'
    else:
        command = [str(encoder), '-hide_banner', '-nostdin', '-v', 'error', '-f', 'lavfi',
                   '-i', 'color=size=1920x1080:rate=100', '-frames:v', '2', '-an',
                   '-c:v', 'h264_nvenc', '-preset', 'p1', '-f', 'null', '-']
        try:
            check = run_cancellable(command, stop, timeout=20)
            result['encoder_ok'] = check.returncode == 0
            result['encoder_message'] = 'NVIDIA NVENC 编码测试通过' if result['encoder_ok'] else 'NVIDIA 编码不可用，请检查显卡与 NVIDIA 驱动。'
            result['encoder_details'] = check.stderr[-1500:]
        except (OSError, subprocess.TimeoutExpired) as exc:
            result['encoder_message'] = '硬件编码测试未完成，请重新检测。'
            result['encoder_details'] = str(exc)
    return result
