"""Install the unmodified, pinned MIT-licensed VDD with normal Windows elevation.

No certificate stores, test-signing settings, or driver signature policies are
changed. Existing VDD installations are deliberately left under their owner's
control. Runtime layout uses user32, never the driver's unsafe reload pipe.
"""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import shutil
import subprocess
import winreg

from .paths import resources, worker_command
from .system import powershell_json, sha256, NO_WINDOW
from .drivers import InstallerProcess

REGISTRY = r'SOFTWARE\MikeTheTech\VirtualDisplayDriver'
OWNER = r'SOFTWARE\G2Bridge\DJIGogglesStreamerDisplay'
HASHES = {
    'mttvdd.cat': '08a0093fc9b2e32b287a6f8a77ca4de0a31830d29fc33d2b13a918dc859468f6',
    'MttVDD.dll': 'c9ca837f57a98fbd43bc416a7f535a95843626e7759eaf85cf0cd7ce334dbb05',
    'MttVDD.inf': '550d211fe481e74dfe3f9d724ed78be48b3a9113405965d683d9373e8d672f5d',
}
CONFIG = '''<?xml version="1.0" encoding="utf-8"?>
<vdd_settings><monitors><count>1</count></monitors>
<gpu><friendlyname>default</friendlyname></gpu>
<resolutions><resolution><width>1920</width><height>1080</height>
<refresh_rate>60</refresh_rate></resolution></resolutions>
<logging><logging>false</logging><debuglogging>false</debuglogging></logging>
<colour><SDR10bit>false</SDR10bit><HDRPlus>false</HDRPlus><ColourFormat>RGB</ColourFormat></colour>
<cursor><HardwareCursor>false</HardwareCursor></cursor>
<edid><CustomEdid>false</CustomEdid></edid></vdd_settings>
'''


def owned_instance():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, OWNER) as key:
            return winreg.QueryValueEx(key, 'DeviceInstanceId')[0]
    except FileNotFoundError:
        return None


def status():
    from .displays import inventory
    instance = owned_instance()
    adapters = [r for r in inventory() if r['hardware_id'].lower() in ('root\\mttvdd','mttvdd')]
    screens = [r for r in adapters if r['monitor_id']]
    return dict(owned=bool(instance), installed=bool(instance or adapters), displays=screens)


def verify_package(folder=None):
    folder = Path(folder) if folder else resources()/'vendor/vdd'
    for name, digest in HASHES.items():
        if sha256(folder/name) != digest:
            raise ValueError('扩展屏驱动校验失败，请重新安装客户端。')
    literal = str(folder/'mttvdd.cat').replace("'", "''")
    signature = powershell_json(f"Get-AuthenticodeSignature -LiteralPath '{literal}' | "
        "Select-Object @{n='Status';e={$_.Status.ToString()}},"
        "@{n='Signer';e={$_.SignerCertificate.Subject}} | ConvertTo-Json -Compress")
    if not signature or signature['Status'] != 'Valid' or 'CN=SignPath Foundation,' not in signature['Signer']:
        raise ValueError('Windows 无法验证扩展屏驱动签名。')
    return folder


class VirtualInstaller(InstallerProcess):
    def __init__(self, remove=False):
        if not remove:
            verify_package()
        program, arguments = worker_command()
        self._launch(program, subprocess.list2cmdline([*arguments,
                      '--remove-display-driver' if remove else '--install-display-driver']))


class GUID(C.Structure):
    _fields_ = [('Data1', W.DWORD), ('Data2', W.WORD), ('Data3', W.WORD), ('Data4', W.BYTE*8)]


class DEVINFO(C.Structure):
    _fields_ = [('cbSize', W.DWORD), ('ClassGuid', GUID), ('DevInst', W.DWORD), ('Reserved', C.c_size_t)]


def _create_device(inf):
    setup = C.WinDLL('setupapi', use_last_error=True)
    setup.SetupDiCreateDeviceInfoList.argtypes = [C.POINTER(GUID), W.HWND]
    setup.SetupDiCreateDeviceInfoList.restype = W.HANDLE
    setup.SetupDiCreateDeviceInfoW.argtypes = [W.HANDLE,W.LPCWSTR,C.POINTER(GUID),W.LPCWSTR,W.HWND,W.DWORD,C.POINTER(DEVINFO)]
    setup.SetupDiSetDeviceRegistryPropertyW.argtypes = [W.HANDLE,C.POINTER(DEVINFO),W.DWORD,C.c_void_p,W.DWORD]
    setup.SetupDiCallClassInstaller.argtypes = [W.DWORD,W.HANDLE,C.POINTER(DEVINFO)]
    setup.SetupDiGetDeviceInstanceIdW.argtypes = [W.HANDLE,C.POINTER(DEVINFO),W.LPWSTR,W.DWORD,C.POINTER(W.DWORD)]
    setup.SetupDiRemoveDevice.argtypes = [W.HANDLE,C.POINTER(DEVINFO)]
    setup.SetupDiDestroyDeviceInfoList.argtypes = [W.HANDLE]
    guid = GUID(0x4d36e968,0xe325,0x11ce,(W.BYTE*8)(0xbf,0xc1,0x08,0x00,0x2b,0xe1,0x03,0x18))
    handle = setup.SetupDiCreateDeviceInfoList(C.byref(guid),None)
    if handle in (None,C.c_void_p(-1).value):
        raise C.WinError(C.get_last_error())
    info = DEVINFO(cbSize=C.sizeof(DEVINFO))
    registered = False
    try:
        if not setup.SetupDiCreateDeviceInfoW(handle,'Display',C.byref(guid),
                'DJI Goggles Streamer Virtual Display',None,1,C.byref(info)):
            raise C.WinError(C.get_last_error())
        hardware = C.create_unicode_buffer('Root\\MttVDD\0')
        if not setup.SetupDiSetDeviceRegistryPropertyW(handle,C.byref(info),1,hardware,C.sizeof(hardware)):
            raise C.WinError(C.get_last_error())
        if not setup.SetupDiCallClassInstaller(0x19,handle,C.byref(info)):
            raise C.WinError(C.get_last_error())
        registered = True
        update = C.WinDLL('newdev',use_last_error=True).UpdateDriverForPlugAndPlayDevicesW
        update.argtypes = [W.HWND,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.POINTER(W.BOOL)]
        reboot = W.BOOL()
        if not update(None,'Root\\MttVDD',str(inf),0,C.byref(reboot)):
            raise C.WinError(C.get_last_error())
        identifier = C.create_unicode_buffer(512)
        if not setup.SetupDiGetDeviceInstanceIdW(handle,C.byref(info),identifier,512,None):
            raise C.WinError(C.get_last_error())
        return identifier.value, bool(reboot.value)
    except Exception:
        if registered:
            setup.SetupDiRemoveDevice(handle,C.byref(info))
        raise
    finally:
        setup.SetupDiDestroyDeviceInfoList(handle)


def install():
    if owned_instance():
        return 0
    # Changing VDDPATH would also affect other applications using this driver.
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY):
            raise RuntimeError('检测到已有 VDD 配置，未覆盖。请使用现有驱动或先通过原软件卸载。')
    except FileNotFoundError:
        pass
    existing = vdd_devices()
    if existing:
        raise RuntimeError('检测到已有 VDD 设备，未添加重复驱动。')
    source = verify_package()
    target = Path(os.environ['ProgramFiles'])/'DJI Goggles Streamer Display'
    target.mkdir(parents=True,exist_ok=True)
    for name in HASHES:
        shutil.copyfile(source/name,target/name)
    verify_package(target)
    (target/'vdd_settings.xml').write_text(CONFIG,encoding='utf-8')
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, REGISTRY,0,winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key,'VDDPATH',0,winreg.REG_SZ,str(target))
    try:
        instance,reboot = _create_device(target/'MttVDD.inf')
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, OWNER,0,winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key,'DeviceInstanceId',0,winreg.REG_SZ,instance)
        return 3010 if reboot else 0
    except Exception:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE,REGISTRY)
        raise


def remove():
    instance = owned_instance()
    if not instance or not instance.upper().startswith('ROOT\\DISPLAY\\'):
        raise RuntimeError('没有由本客户端安装的扩展屏驱动。')
    tool = Path(os.environ['SystemRoot'])/'System32/pnputil.exe'
    result = subprocess.run([str(tool),'/remove-device',instance],capture_output=True,
                             timeout=90,creationflags=NO_WINDOW)
    if result.returncode not in (0,3010):
        raise RuntimeError(f'Windows 无法移除扩展屏设备（{result.returncode}）。')
    # Leave the signed driver store package; it may now be used by other software.
    winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE,OWNER)
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,REGISTRY) as key:
        path = winreg.QueryValueEx(key,'VDDPATH')[0]
    others = vdd_devices()
    if not others and path == str(Path(os.environ['ProgramFiles'])/'DJI Goggles Streamer Display'):
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE,REGISTRY)
    return result.returncode


def vdd_devices():
    return powershell_json("Get-CimInstance Win32_PnPEntity | Where-Object { "
        "$_.HardwareID -contains 'Root\\MttVDD' -or $_.HardwareID -contains 'MttVDD' } | "
        "Select-Object PNPDeviceID | ConvertTo-Json -Compress")


def elevated_main(remove_driver=False):
    # This entry point accepts no paths or arbitrary commands from the caller.
    if not C.windll.shell32.IsUserAnAdmin():
        return 5
    log = Path(os.environ['ProgramData'])/'DJI Goggles Streamer'
    log.mkdir(parents=True,exist_ok=True)
    try:
        code = remove() if remove_driver else install()
        report = dict(success=True,code=code)
    except Exception as exc:
        code = 1
        report = dict(success=False,error=str(exc))
    (log/'display-install.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
    return code
