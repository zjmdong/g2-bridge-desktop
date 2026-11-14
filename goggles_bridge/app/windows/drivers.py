"""Acquire the pinned official installer; never redistribute DJI binaries."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import urllib.parse
import urllib.request

from .paths import data_dir, resources
from .system import Cancelled, powershell_json, sha256, run_cancellable

ASSISTANT_URL = ('https://dl.djicdn.com/downloads/dji_assistant/20260922/'
                 'DJI Assistant 2(Consumer Drones Series) 2.1.42.exe')
ASSISTANT_PAGE = 'https://www.dji.com/downloads/softwares/dji-assistant-2-consumer-drones-series'
ASSISTANT_SHA256 = '95766b985f38658b3aa8ed7c0b79bada38b9c9571111e55a2f1225349a8c5d33'
MAX_INSTALLER_BYTES = 1024*1024*1024
DRIVER_SUBDIR = r'app\Drivers\Drivers_Win10\BULK_DRIVER\bulk_amd64'
DRIVER_HASHES = {
    'DEVICE_BULK.inf': 'e94bb6f41554974786cf3872ee04155539448614a704763e017624dccd063cff',
    'device_bulk.cat': '440ba63407e6ee53c808c4fdc5fd5b90e537217a8ddad782ebf6e911f719ccca',
    'libusb0_device.dll': 'd2c16bd7c7fb2344408259fd083c8fdbeda3b096b8c9d07e48848e99fc2c3743',
    'libusb0_device.sys': '8a6b44936d10c207796e3d202b70fcaa94b82c21ba4f92da59832c551e56fc8c',
    'libusb0_x86_device.dll': 'f795dca1f9719a4ff828835f88ff463cc11aa274f9cc9651b17075653e361747',
}


def verify_driver(path):
    path = Path(path).resolve(strict=True)
    if path.name != 'DEVICE_BULK.inf':
        raise ValueError('驱动入口不匹配。')
    for name, digest in DRIVER_HASHES.items():
        if sha256(path.parent / name) != digest:
            raise ValueError('驱动文件校验失败，未启动安装。')
    return path


def prepare_driver(installer, stop, emit):
    verify_installer(installer)
    emit('driver_preparing')
    folder = data_dir() / 'drivers' / '5.0.0.7'
    folder.mkdir(parents=True, exist_ok=True)
    extractor = resources() / 'vendor/innoextract/innoextract.exe'
    command = [str(extractor), '--silent', '--include', DRIVER_SUBDIR,
               '--include', r'app\Drivers\Drivers_Win10\BULK_DRIVER\license',
               '--output-dir', str(folder), str(Path(installer).resolve())]
    result = run_cancellable(command, stop, timeout=240)
    if result.returncode:
        raise ValueError('无法提取已验证的 USB 驱动，请重新下载官方安装包。')
    inf = verify_driver(folder / DRIVER_SUBDIR / 'DEVICE_BULK.inf')
    if stop.is_set():
        raise Cancelled()
    return inf


def verify_installer(path):
    path = Path(path).resolve(strict=True)
    if sha256(path) != ASSISTANT_SHA256:
        raise ValueError('安装包校验失败，请重新下载官方 2.1.42 安装包。')
    literal = str(path).replace("'", "''")
    info = powershell_json(f"Get-AuthenticodeSignature -LiteralPath '{literal}' | "
                           "Select-Object @{n='Status';e={$_.Status.ToString()}},"
                           "@{n='Signer';e={$_.SignerCertificate.Subject}} | ConvertTo-Json -Compress")
    if not info or info.get('Status') != 'Valid':
        raise ValueError('Windows 无法验证安装包签名，未启动安装。请检查系统时间或使用官方安装流程。')
    return info


def download_assistant(stop, emit):
    folder = data_dir() / 'downloads'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'DJI-Assistant-2-Consumer-2.1.42.exe'
    if target.is_file() and sha256(target) == ASSISTANT_SHA256:
        verify_installer(target)
        return target
    partial = target.with_suffix('.partial')
    request = urllib.request.Request(urllib.parse.quote(ASSISTANT_URL, safe=':/'),
                                     headers={'User-Agent': 'Goggles-Bridge-Windows-Driver-Setup'})
    try:
        with urllib.request.urlopen(request, timeout=20) as response, partial.open('wb') as output:
            parsed = urllib.parse.urlparse(response.url)
            if parsed.scheme != 'https' or parsed.hostname != 'dl.djicdn.com':
                raise ValueError('官方下载被重定向到未验证来源。请使用官方下载安装包。')
            total = int(response.headers.get('Content-Length', '0'))
            received = 0
            last_percent = -1
            while True:
                if stop.is_set():
                    raise Cancelled()
                block = response.read(256*1024)
                if not block:
                    break
                received += len(block)
                if received > MAX_INSTALLER_BYTES:
                    raise ValueError('安装包超过预期大小，已停止下载。')
                output.write(block)
                percent = int(received*100/total) if total else 0
                if percent != last_percent:
                    emit('download_progress', received=received, total=total, percent=percent)
                    last_percent = percent
        if sha256(partial) != ASSISTANT_SHA256:
            raise ValueError('官方下载内容与已验证安装包不同，未执行。请使用官方页面或导入匹配的 2.1.42 安装包。')
        partial.replace(target)
        verify_installer(target)
        return target
    finally:
        partial.unlink(missing_ok=True)


class InstallerProcess:
    """Install the signed vendor INF with Windows PnPUtil and retain its handle."""
    def __init__(self, path):
        path = verify_driver(path)
        self._launch(str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/pnputil.exe'),
                     f'/add-driver "{path}" /install')

    def _launch(self, program, arguments):

        class SHELLEXECUTEINFO(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND),
                        ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR),
                        ('lpParameters', wintypes.LPCWSTR), ('lpDirectory', wintypes.LPCWSTR),
                        ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
                        ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR),
                        ('hkeyClass', wintypes.HKEY), ('dwHotKey', wintypes.DWORD),
                        ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]

        info = SHELLEXECUTEINFO()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = 0x40 | 0x400  # NOCLOSEPROCESS, FLAG_NO_UI
        info.lpVerb = 'runas'
        info.lpFile = program
        info.lpParameters = arguments
        info.nShow = 0
        execute = ctypes.WinDLL('shell32', use_last_error=True).ShellExecuteExW
        execute.argtypes = [ctypes.POINTER(SHELLEXECUTEINFO)]
        execute.restype = wintypes.BOOL
        if not execute(ctypes.byref(info)):
            code = ctypes.get_last_error()
            raise OSError(code, '已取消 Windows 授权。' if code == 1223 else '无法启动 Windows 驱动安装。')
        self.handle = info.hProcess

    def poll(self):
        if not self.handle:
            return 0
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        get_exit = kernel.GetExitCodeProcess
        get_exit.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        get_exit.restype = wintypes.BOOL
        code = wintypes.DWORD()
        if not get_exit(self.handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        if code.value == 259:
            return None
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close(self.handle)
        self.handle = None
        return code.value
