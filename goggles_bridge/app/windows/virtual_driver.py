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
import xml.etree.ElementTree as ET
try:
    import winreg
except ImportError:  # Other platforms can import the app without Windows services.
    winreg = None

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
<global><g_refresh_rate>60</g_refresh_rate><g_refresh_rate>75</g_refresh_rate>
<g_refresh_rate>90</g_refresh_rate><g_refresh_rate>100</g_refresh_rate></global>
<resolutions><resolution><width>1920</width><height>1080</height>
<refresh_rate>60</refresh_rate></resolution><resolution><width>1280</width><height>720</height>
<refresh_rate>60</refresh_rate></resolution></resolutions>
<options><logging>false</logging><debuglogging>false</debuglogging>
<SDR10bit>false</SDR10bit><HDRPlus>false</HDRPlus><HardwareCursor>false</HardwareCursor>
<CustomEdid>false</CustomEdid></options></vdd_settings>
'''


def owned_instance():
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, OWNER) as key:
            return winreg.QueryValueEx(key, 'DeviceInstanceId')[0]
    except FileNotFoundError:
        return None


def install_folder():
    # Keep the 0.1/0.2 installation path and ownership key during migration.
    return Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'DJI Goggles Streamer Display'


def _owns_configuration():
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY) as key:
            path = winreg.QueryValueEx(key, 'VDDPATH')[0]
        return Path(path).resolve() == install_folder().resolve()
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return False


def _instance_registered(instance):
    if not instance or not instance.upper().startswith('ROOT\\DISPLAY\\') or winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            'SYSTEM\\CurrentControlSet\\Enum\\' + instance) as key:
            identifiers = winreg.QueryValueEx(key, 'HardwareID')[0]
        if isinstance(identifiers, str):
            identifiers = [identifiers]
        return any(value.lower() in ('root\\mttvdd', 'mttvdd') for value in identifiers)
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return False


def configuration_details(text):
    """Check modes while preserving an explicitly configured render-GPU preference."""
    try:
        current, expected = ET.fromstring(text), ET.fromstring(CONFIG)
        gpu = current.find('gpu/friendlyname')
        if gpu is None or not (gpu.text or '').strip():
            return False, None
        preference = gpu.text.strip()
        gpu.text = 'default'
        for root in (current, expected):
            for node in root.iter():
                node.text = (node.text or '').strip() or None
                node.tail = None
        return ET.tostring(current) == ET.tostring(expected), preference
    except ET.ParseError:
        return False, None


def status():
    if os.name != 'nt':
        return dict(owned=False, installed=False, displays=[], config_current=False,
                    needs_update=False, gpu_preference=None, supported=False)
    from .displays import inventory
    instance = owned_instance()
    adapters = [r for r in inventory() if r['hardware_id'].lower() in ('root\\mttvdd','mttvdd')]
    screens = [r for r in adapters if r['monitor_id']]
    current, preference = False, None
    manageable = bool(instance and _owns_configuration() and _instance_registered(instance))
    if instance:
        try:
            current, preference = configuration_details(
                (install_folder() / 'vdd_settings.xml').read_text(encoding='utf-8'))
        except OSError:
            pass
    return dict(owned=manageable, installed=bool(instance or adapters), displays=screens,
                config_current=manageable and current, needs_update=manageable and not current,
                gpu_preference=preference, supported=True)


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
                      'remove-display-driver' if remove else 'install-display-driver']))


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
    if os.name != 'nt':
        raise RuntimeError('Virtual display installation is only available on Windows.')
    if instance := owned_instance():
        target = install_folder()
        if not _owns_configuration() or not _instance_registered(instance):
            raise RuntimeError('扩展屏配置已由其他软件接管，未覆盖。')
        devices = vdd_devices()
        if len(devices) != 1 or devices[0]['PNPDeviceID'].casefold() != instance.casefold():
            raise RuntimeError('存在其他软件的同类扩展屏设备，未更改共享驱动配置。')
        verify_package(target)
        config = target/'vdd_settings.xml'
        original = config.read_text(encoding='utf-8')
        current, preference = configuration_details(original)
        if current:
            return 0
        updated = ET.fromstring(CONFIG)
        if preference:
            updated.find('gpu/friendlyname').text = preference
        config.write_text(ET.tostring(updated, encoding='unicode'), encoding='utf-8')
        tool = Path(os.environ['SystemRoot'])/'System32/pnputil.exe'
        try:
            result = subprocess.run([str(tool), '/restart-device', instance], capture_output=True,
                                    timeout=90, creationflags=NO_WINDOW)
            if result.returncode not in (0, 3010):
                raise RuntimeError(f'Windows 无法刷新扩展屏模式（{result.returncode}）。')
        except Exception:
            config.write_text(original, encoding='utf-8')
            raise
        return result.returncode
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
    target = install_folder()
    target.mkdir(parents=True,exist_ok=True)
    for name in HASHES:
        shutil.copyfile(source/name,target/name)
    verify_package(target)
    (target/'vdd_settings.xml').write_text(CONFIG,encoding='utf-8')
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, REGISTRY,0,winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key,'VDDPATH',0,winreg.REG_SZ,str(target))
    created_instance = None
    try:
        instance,reboot = _create_device(target/'MttVDD.inf')
        created_instance = instance
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, OWNER,0,winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key,'DeviceInstanceId',0,winreg.REG_SZ,instance)
        return 3010 if reboot else 0
    except Exception as exc:
        # Device creation can succeed before persisting ownership fails. Remove
        # only that exact new instance; never leave it pointing at a deleted key.
        if created_instance:
            tool = Path(os.environ['SystemRoot'])/'System32/pnputil.exe'
            try:
                rollback = subprocess.run([str(tool), '/remove-device', created_instance],
                    capture_output=True, timeout=90, creationflags=NO_WINDOW)
                if rollback.returncode not in (0,3010):
                    raise RuntimeError(f'Windows 未能回滚扩展屏安装（{rollback.returncode}）。')
            except Exception as cleanup_error:
                if hasattr(exc, 'add_note'):
                    exc.add_note(str(cleanup_error))
                raise exc
        if _owns_configuration():
            winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE,REGISTRY)
        raise


def remove():
    instance = owned_instance()
    if not instance or not _instance_registered(instance):
        raise RuntimeError('没有由本客户端安装的扩展屏驱动。')
    tool = Path(os.environ['SystemRoot'])/'System32/pnputil.exe'
    result = subprocess.run([str(tool),'/remove-device',instance],capture_output=True,
                             timeout=90,creationflags=NO_WINDOW)
    if result.returncode not in (0,3010):
        raise RuntimeError(f'Windows 无法移除扩展屏设备（{result.returncode}）。')
    # Leave the signed driver store package; it may now be used by other software.
    winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE,OWNER)
    others = vdd_devices()
    if not others and _owns_configuration():
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE,REGISTRY)
    return result.returncode


def vdd_devices():
    rows = powershell_json("Get-CimInstance Win32_PnPEntity | Where-Object { "
        "$_.HardwareID -contains 'Root\\MttVDD' -or $_.HardwareID -contains 'MttVDD' } | "
        "Select-Object PNPDeviceID | ConvertTo-Json -Compress")
    return rows if isinstance(rows, list) else [rows] if rows else []


def elevated_main(remove_driver=False):
    # This entry point accepts no paths or arbitrary commands from the caller.
    if os.name != 'nt' or not C.windll.shell32.IsUserAnAdmin():
        return 5
    log = Path(os.environ['ProgramData'])/'DJI Goggles Streamer'
    log.mkdir(parents=True,exist_ok=True)
    try:
        # A second app instance must not restart/remove the driver's live
        # swapchain while a worker owns a virtual-display stream.
        from .display_session import _process_lease
        with _process_lease():
            code = remove() if remove_driver else install()
        report = dict(success=True,code=code)
    except Exception as exc:
        code = 1
        report = dict(success=False,error=str(exc))
    (log/'display-install.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
    return code


def maintenance_main(argv):
    """Dispatch only fixed maintenance operations after --windows-maintenance."""
    operations = {'install-display-driver': False, 'remove-display-driver': True}
    if len(argv) != 1 or argv[0] not in operations:
        return 64
    return elevated_main(remove_driver=operations[argv[0]])
