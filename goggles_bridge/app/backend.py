"""Desktop app backend: setup checks, saved options, and the stream engine behind the window."""
import ctypes as C
from dataclasses import fields
from datetime import datetime
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser

from .. import __version__
from . import updates
from .displays import list_displays
from ..control import V1Stream
from ..engine import CHOICES, MAX_FRAME_BYTES, NO_WINDOW, BridgeEngine, BridgeSettings, check_encoder, find_program
from ..session import SIMULATOR_SILENT, ControlSession
from ..usb_transport import PRODUCT_ID, VENDOR_ID, ControlUsb, find_dll

APP_NAME = 'Goggles Bridge'
UI = Path(__file__).with_name('ui')
WINDOWS, MAC = sys.platform == 'win32', sys.platform == 'darwin'
LINKS = {
    'driver': 'https://www.dji.com/downloads/softwares/dji-assistant-2-consumer-drones-series',
    'github': 'https://github.com/Ammaar-Alam/goggles-bridge',
    'report': 'https://github.com/Ammaar-Alam/goggles-bridge/issues/new',
    'screen': 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture',
    'webview2': 'https://developer.microsoft.com/microsoft-edge/webview2/',
}
# only the installed app can replace itself
UPDATABLE = getattr(sys, 'frozen', False) and (WINDOWS or MAC)
CAPTURES = (('screencapturekit',) if MAC else ('gfxcapture', 'ddagrab'))
# identity build dates of the firmware that displayed video, by model. Integra 01.09.00.00 also
# displayed video, but its build date was not recorded, so Integra builds are not judged
TESTED_BUILDS = {'DJI Goggles 2': {'Dec 24 2024': '01.11.00.00', 'Feb 26 2025': '01.12.00.00',
                                   'Aug 11 2026': '01.14.00.00'}}
# every stream option the window can change
OPTIONS = tuple(f.name for f in fields(BridgeSettings) if f.name not in ('dll', 'ffmpeg', 'capture_fps'))
APP_OPTIONS = dict(source='display', resolution='1080p', auto_start=False, display_device='')


def data_dir():
    if override := os.environ.get('GOGGLES_BRIDGE_DATA_DIR'):
        return Path(override)
    if WINDOWS:
        return Path(os.environ.get('LOCALAPPDATA', Path.home()), APP_NAME)
    if MAC:
        return Path.home()/'Library'/'Application Support'/APP_NAME
    return Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local'/'share'), 'goggles-bridge')


def find_ffmpeg():
    """Return the FFmpeg shipped beside a packaged app, else GOGGLES_FFMPEG, else the one on PATH."""
    bundled = Path(sys.executable).parent/'ffmpeg'/('ffmpeg.exe' if WINDOWS else 'ffmpeg')
    development = Path(__file__).resolve().parents[2]/'vendor'/'ffmpeg'/'ffmpeg.exe'
    found = (bundled if bundled.is_file() else os.environ.get('GOGGLES_FFMPEG') or
             (development if WINDOWS and development.is_file() else find_program('ffmpeg')))
    return Path(found) if found else None


def goggles_attached():
    """Return whether the goggles are on USB, without opening them; None when that cannot be told."""
    if WINDOWS:
        cfg = C.WinDLL('cfgmgr32')
        cfg.CM_Get_Device_ID_List_SizeW.argtypes = [C.POINTER(C.c_ulong), C.c_wchar_p, C.c_ulong]
        cfg.CM_Get_Device_ID_ListW.argtypes = [C.c_wchar_p, C.c_wchar_p, C.c_ulong, C.c_ulong]
        present = 0x101  # CM_GETIDLIST_FILTER_ENUMERATOR | CM_GETIDLIST_FILTER_PRESENT
        size = C.c_ulong()
        if cfg.CM_Get_Device_ID_List_SizeW(C.byref(size), 'USB', present) or not size.value:
            return None
        ids = C.create_unicode_buffer(size.value)
        if cfg.CM_Get_Device_ID_ListW('USB', ids, size, present):
            return None
        wanted = f'USB\\VID_{VENDOR_ID:04X}&PID_{PRODUCT_ID:04X}'
        return any(i.upper().startswith(wanted) for i in ids[:size.value].split('\0'))
    try:
        import usb.core
        return usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID) is not None
    except Exception:
        return None


def identify():
    """Read the model and identity from attached goggles without entering simulator mode."""
    session, decoder = ControlSession(enter_simulator=False), V1Stream()
    with ControlUsb(find_dll()) as usb:
        deadline = time.monotonic()+2
        while session.state != 'identified' and time.monotonic() < deadline:
            for packet in session.poll(time.monotonic()):
                usb.write(packet.serialize())
            # Like the stream engine, avoid frequent DJI endpoint aborts on read timeout.
            for reply in decoder.feed(usb.read(timeout_ms=500) or b''):
                for packet in session.receive(reply, time.monotonic()):
                    usb.write(packet.serialize())
    return (session.model, session.identity) if session.state == 'identified' else None


def describe(model, identity):
    """Return the goggles' model, firmware build, its version when recorded, and whether that build is tested."""
    found = re.search(r'[A-Z][a-z]{2} +\d+ \d{4}', identity)
    build = found.group() if found else identity
    known = TESTED_BUILDS.get(model)
    return dict(model=model, identity=identity, build=build, version=(known or {}).get(build),
                tested=None if known is None else build in known,
                tested_versions=sorted(known.values()) if known else [])


def screen_access(request=False):
    """Return whether macOS lets this app record the screen; a request also lists the app in System Settings."""
    cg = C.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    check = cg.CGRequestScreenCaptureAccess if request else cg.CGPreflightScreenCaptureAccess
    check.restype = C.c_bool
    return check()


def default_options():
    capture = 'screencapturekit' if MAC else BridgeSettings.capture
    return {name: (capture if name == 'capture' else getattr(BridgeSettings, name)) for name in OPTIONS}


def problem_code(message):
    """Name the kind of problem in an engine message so the window can explain the recovery."""
    for code, text in (('virtual_flight', SIMULATOR_SILENT), ('unplugged', 'Waiting for powered goggles'),
                       ('slow_link', 'full-speed'), ('rejected', 'Goggles rejected'),
                       ('unsupported', 'Unsupported goggles'), ('oversize', 'exceed the size limit'),
                       ('no_video', 'No video from display'), ('driver', 'libusb0')):
        if text in message:
            return code
    return 'other'


class Desktop:
    """The object the window's JavaScript calls. Public methods return JSON-ready values."""
    def __init__(self, *, settings_path=None, engine_factory=BridgeEngine, check=check_encoder, identify=identify,
                 runtime=None):
        self._settings_path = Path(settings_path or data_dir()/'settings.json')
        self._engine_factory, self._check, self._identify = engine_factory, check, identify
        self._runtime = runtime
        if WINDOWS and runtime is None and engine_factory is BridgeEngine:
            from .windows.runtime import WindowsRuntime
            self._runtime = WindowsRuntime()
        # the connected goggles: None before a look, False after a failed one, else what describe returns.
        # A stream's ready event also sets it, and a disconnect clears it
        self._device = None
        self._probe = None
        self._update = None
        self._updating = False
        self._quit = lambda: None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._watch_stop = threading.Event()
        self._watcher = None
        self._connection_attempted = False
        self._last_attached = None
        self._installing = None
        self._install_problem = {}
        self._install_thread = None
        self._display_path = None
        self._state = dict(phase='idle', problem=None, stats=None, oversize=0, log=None)
        self._checks = (0, None)
        self._displays = []
        self._ffmpeg = find_ffmpeg()
        self._options = {**default_options(), **(APP_OPTIONS if WINDOWS else {})}
        if self._runtime:
            self._options['capture'] = 'ddagrab'
        self._onboarded = False
        try:
            if not self._settings_path.exists() and WINDOWS and settings_path is None:
                self._migrate_legacy()
            saved = json.loads(self._settings_path.read_text(encoding='utf-8'))
            self._onboarded = bool(saved.get('onboarded'))
            self._settings(saved)
        except (OSError, ValueError, TypeError, AttributeError):
            pass  # keep the defaults when nothing valid is saved

    def _settings(self, options):
        """Validate options and adopt them; the engine's own rules decide what is allowed."""
        allowed = (*OPTIONS, *(APP_OPTIONS if WINDOWS else ()))
        merged = {**self._options, **{k: v for k, v in options.items() if k in allowed}}
        if WINDOWS:
            if merged['source'] not in ('display', 'virtual') or merged['resolution'] not in ('720p', '1080p'):
                raise ValueError('Unsupported display source or resolution')
            if type(merged['auto_start']) is not bool or not isinstance(merged['display_device'], str):
                raise ValueError('Invalid automatic streaming or display setting')
            if len(merged['display_device']) > 256:
                raise ValueError('Invalid display identifier')
        if self._runtime:
            merged.update(capture='ddagrab', low_latency=True, h264_profile='high', adaptive_quant=False)
        engine = {k: v for k, v in merged.items() if k in OPTIONS}
        if self._runtime:
            engine['capture_fps'] = engine['fps']
        settings = BridgeSettings(find_dll(), self._ffmpeg, **engine)
        self._options = merged
        return settings

    def _migrate_legacy(self):
        """Read the previous fork once, without replacing upstream preferences or deleting the original."""
        legacy = Path(os.environ.get('LOCALAPPDATA', Path.home()))/'DJI Goggles Streamer'/'settings.json'
        try:
            saved = json.loads(legacy.read_text(encoding='utf-8'))
            saved['source'] = 'virtual' if saved.get('source') == 'extended' else 'display'
            saved['onboarded'] = True
            self._settings(saved)
        except (OSError, ValueError, TypeError, AttributeError):
            return
        self._onboarded = True
        self._save()

    def _bitrates(self):
        """For each frame rate, the bitrates the engine accepts and the one it picks by default."""
        table = {}
        for fps in CHOICES['fps']:
            allowed = []
            for bitrate in CHOICES['bitrate_mbps']:
                try:
                    BridgeSettings(None, None, fps=fps, bitrate_mbps=bitrate, capture=self._options['capture'])
                    allowed.append(bitrate)
                except ValueError:
                    pass
            auto = BridgeSettings(None, None, fps=fps, capture=self._options['capture']).bitrate_mbps
            table[str(fps)] = dict(allowed=allowed, auto=auto)
        return table

    def _preflight(self):
        """Check the driver, FFmpeg, and the cable at most once a second, and never during a stream."""
        checked, result = self._checks
        if result is None or (not self._running() and time.monotonic()-checked >= 1):
            needs_ffmpeg = self._options['capture'] != 'screencapturekit'
            result = dict(driver=dict(needed=WINDOWS, ok=not WINDOWS or find_dll().is_file()),
                          screen=dict(needed=MAC, ok=not MAC or screen_access()),
                          ffmpeg=dict(needed=needs_ffmpeg, ok=not needs_ffmpeg or bool(self._ffmpeg and self._ffmpeg.is_file())),
                          attached=goggles_attached())
            if self._runtime:
                from .windows.virtual_driver import status
                from .windows.system import driver_status
                driver = driver_status()
                result['driver'].update(ok=driver['status'] == 'verified',
                                        problem=None if driver['status'] == 'verified' else driver['message'])
                try:
                    virtual = status()
                    result['virtual_display'] = dict(needed=self._options['source'] == 'virtual',
                        ok=virtual['owned'] and not virtual['needs_update'], **virtual)
                except Exception as exc:
                    result['virtual_display'] = dict(needed=self._options['source'] == 'virtual',
                        ok=False, installed=False, needs_update=False, problem=str(exc))
            for name in ('driver', 'virtual_display'):
                if name in result:
                    result[name].update(installing=self._installing == name,
                                        problem=self._install_problem.get(name) or result[name].get('problem'))
            self._checks = (time.monotonic(), result)
            if result['attached'] is False:
                self._device = None
            elif (result['attached'] and result['driver']['ok'] and self._device is None and not self._running()
                  and not (self._probe and self._probe.is_alive())):
                # ask newly attached goggles who they are, once per connection
                self._probe = threading.Thread(target=self._look, daemon=True)
                self._probe.start()
        return result

    def _look(self):
        try:
            found = self._identify()
            self._device = describe(*found) if found else False
        except Exception:
            self._device = False  # goggles that do not answer are identified when a stream starts

    def _running(self):
        return bool((self._thread is not None and self._thread.is_alive()) or
                    (self._runtime and getattr(self._runtime, 'busy', lambda: False)()))

    def snapshot(self):
        """Return everything the window draws."""
        with self._lock:
            state = dict(self._state)
        if self._runtime and getattr(self._runtime, 'busy', lambda: False)() and not (
                self._thread and self._thread.is_alive()):
            state['phase'] = 'stopping'
        checks = self._preflight()  # first, because a disconnect clears the identity
        state['device'] = self._device or None
        if not self._running() or not self._displays:
            self._displays = list_displays()
            if self._displays and self._options['display_index'] not in {d['index'] for d in self._displays}:
                # the saved display is gone, so fall back to the main one
                self._options['display_index'] = next((d['index'] for d in self._displays if d['primary']), 0)
            if WINDOWS and self._options['source'] == 'display':
                device = self._options.get('display_device')
                target = next((d for d in self._displays if d.get('device') == device), None) if device else None
                if target:
                    self._options['display_index'] = target['index']
                elif not device:
                    target = next((d for d in self._displays if d['index'] == self._options['display_index']), None)
                    if target and target.get('device'):
                        self._options['display_device'] = target['device']
        capabilities = dict(virtual_display=bool(self._runtime), resolution=bool(self._runtime),
            auto_start=bool(self._runtime), captures=['ddagrab'] if self._runtime else list(CAPTURES),
            fixed_encoder_options=bool(self._runtime))
        return dict(app=dict(name=APP_NAME, version=__version__, platform=sys.platform, updatable=UPDATABLE),
                    checks=checks, displays=self._displays, options=dict(self._options),
                    capabilities=capabilities, display_path=self._display_path,
                    choices=dict(fps=CHOICES['fps'], capture=capabilities['captures'], preset=CHOICES['preset'],
                                 keyframe_seconds=CHOICES['keyframe_seconds'], h264_profile=CHOICES['h264_profile'],
                                 usb_write_size=CHOICES['usb_write_size'], bitrates=self._bitrates()),
                    frame_limit=MAX_FRAME_BYTES, onboarded=self._onboarded, **state)

    def set_options(self, options):
        """Adopt and save changed options. Returns the problem when the engine refuses them."""
        with self._lock:
            if self._running() or self._installing or self._updating:
                return dict(error='Stop streaming or wait for setup before changing options')
            try:
                self._settings(options)
            except (ValueError, TypeError, AttributeError) as exc:
                return dict(error=str(exc))
            self._checks = (0, None)
            self._save()
        return dict(ok=True)

    def finish_setup(self):
        """Remember that the setup guide was finished or skipped."""
        self._onboarded = True
        self._save()
        return dict(ok=True)

    def _save(self):
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._settings_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(self._options, onboarded=self._onboarded), indent=1), encoding='utf-8')
        os.replace(temporary, self._settings_path)

    def start(self):
        with self._lock:
            if self._running():
                return dict(ok=True)
            if self._updating or self._installing:
                return dict(ok=False)  # the app is about to close
            checks = self._preflight()
            self._connection_attempted = True
            for name in ('driver', 'screen', 'ffmpeg', *(['virtual_display'] if
                         self._runtime and self._options['source'] == 'virtual' else [])):
                if not checks[name]['ok']:
                    self._state.update(phase='error', problem=dict(code=name, message=f'{name} not found'))
                    return dict(ok=False)
            settings = self._settings({})
            log = data_dir()/'logs'/f'{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.jsonl'
            self._stop.clear()
            self._state.update(phase='preparing' if self._runtime and self._options['source'] == 'virtual' else 'checking', problem=None,
                               stats=None, oversize=0, log=str(log))
            self._thread = threading.Thread(target=self._run, args=(settings, log), daemon=True)
            self._thread.start()
        return dict(ok=True)

    def stop(self):
        self._connection_attempted = True
        self._stop.set()
        return dict(ok=True)

    def _hotplug_tick(self, attached):
        """One attempt per cable connection; manual Stop never immediately starts again."""
        if attached is None:
            return
        if not attached:
            self._stop.set()
            self._connection_attempted = False
            self._device = None
        elif (not self._connection_attempted and self._options.get('auto_start') and
              self._onboarded and not self._running() and not self._installing and not self._updating):
            # Mark first: both a successful start and a failed setup wait for a new cable event.
            self._connection_attempted = True
            self.start()
        self._last_attached = attached

    def start_monitor(self):
        if not self._runtime or self._watcher:
            return

        def watch():
            while not self._watch_stop.wait(.5):
                try:
                    self._hotplug_tick(goggles_attached())
                except OSError:
                    pass  # transient PnP failure is not a confirmed unplug

        self._watcher = threading.Thread(target=watch, daemon=True, name='usb-presence')
        self._watcher.start()

    def close(self):
        self._watch_stop.set()
        self.stop()
        if self._watcher:
            self._watcher.join(timeout=2)
        if self._thread:
            self._thread.join(timeout=20)  # the worker's finally releases the virtual display

    def _install(self, kind):
        if not self._runtime:
            return dict(error='Automatic driver setup is available in the Windows app')
        with self._lock:
            if self._running() or self._installing or self._updating:
                return dict(error='Stop streaming or wait for the current setup')
            self._installing = kind
            self._install_problem.pop(kind, None)
            self._checks = (0, None)

        def install():
            from .windows.drivers import download_assistant, prepare_driver, InstallerProcess
            from .windows.virtual_driver import VirtualInstaller
            try:
                if kind == 'virtual_display':
                    operation = VirtualInstaller()
                else:
                    package = download_assistant(self._watch_stop, lambda *a, **k: None)
                    inf = prepare_driver(package, self._watch_stop, lambda *a, **k: None)
                    operation = InstallerProcess(inf)
                while (code := operation.poll()) is None:
                    time.sleep(.2)
                if code not in (0, 3010):
                    raise RuntimeError(f'Windows driver installation stopped ({code})')
            except Exception as exc:
                self._install_problem[kind] = str(exc)
            finally:
                self._installing = None
                self._checks = (0, None)

        self._install_thread = threading.Thread(target=install, daemon=True, name='driver-setup')
        self._install_thread.start()
        return self.snapshot()

    def install_virtual_driver(self):
        return self._install('virtual_display')

    def install_driver(self):
        return self._install('driver')

    def _fail(self, message):
        with self._lock:
            self._state.update(phase='error', problem=dict(code=problem_code(message), message=message))

    def _run(self, settings, log):
        try:
            if self._probe:
                self._probe.join(5)  # the stream needs the USB interface to itself
                if self._probe.is_alive():
                    raise RuntimeError('Device identification has not released USB yet. Try again shortly.')
            if self._runtime:
                self._runtime.run(settings, dict(self._options), log, self._stop, self._event)
                return
            problem = self._check(settings)
            if problem:
                with self._lock:
                    self._state.update(phase='error', problem=dict(code='encoder', message=problem))
                return
            if not self._stop.is_set():
                self._engine_factory(settings, log, on_event=self._event, stop_event=self._stop).run()
        except Exception as exc:
            self._fail(str(exc))
        finally:
            self._checks = (0, None)
            with self._lock:
                if self._state['phase'] != 'error':
                    self._state.update(phase='idle', stats=None, problem=None)

    def _event(self, row):
        event = row['event']
        with self._lock:
            state = self._state
            if event in ('preparing_display', 'checking_capture'):
                if state['phase'] != 'error':
                    state['phase'] = 'preparing' if event == 'preparing_display' else 'checking'
            elif event == 'releasing_display':
                if state['phase'] != 'error':
                    state['phase'] = 'stopping'
            elif event == 'display_cleanup_error':
                state.update(phase='error', problem=dict(code='virtual_display', message=row['message']))
            elif event == 'display_path':
                self._display_path = {k: v for k, v in row.items() if k != 'event'}
            elif event == 'waiting':
                state.update(phase='waiting', problem=dict(code=problem_code(row['message']), message=row['message']))
            elif event == 'connected':
                state.update(phase='connecting', problem=None)
            elif event == 'ready':
                state['phase'] = 'ready'
                self._device = describe(row['model'], row['identity'])
            elif event == 'streaming':
                state['phase'] = 'streaming'
            elif event == 'stats':
                state['stats'] = {k: row[k] for k in ('fps', 'send_ms_p95', 'frame_bytes_max')}
            elif event == 'oversize_frame':
                state['oversize'] += 1
            elif event == 'error':
                state.update(phase='error', problem=dict(code=problem_code(row['message']), message=row['message']))

    def diagnostics(self):
        """Copy a plain-text report to the clipboard and return it."""
        with self._lock:
            state = dict(self._state)
        lines = [f'{APP_NAME} {__version__}', f'{platform.platform()} | Python {platform.python_version()}',
                 f'FFmpeg: {self._ffmpeg}', f'Checks: {json.dumps(self._preflight())}',
                 f'Options: {json.dumps(self._options)}',
                 f'Display path: {json.dumps(self._display_path)}',
                 f"State: {state['phase']} {json.dumps(state['problem'])} {json.dumps(self._device or None)}"]
        if self._ffmpeg and self._ffmpeg.is_file():
            version = subprocess.run([str(self._ffmpeg), '-hide_banner', '-version'], capture_output=True, text=True,
                                     errors='replace', timeout=10, creationflags=NO_WINDOW).stdout.splitlines()
            lines.append(f'FFmpeg version: {version[0] if version else "unknown"}')
        log = Path(state['log']) if state['log'] else None
        if log and log.is_file():
            rows = [row for row in log.read_text(encoding='utf-8').splitlines() if '"control_' not in row]
            lines += ['', f'Last events ({log.name}):', *rows[-60:]]
            for encoder_log in sorted(log.parent.glob(f'{log.stem}.encoder-*.log'))[-1:]:
                tail = encoder_log.read_text(encoding='utf-8', errors='replace').replace('\r', '\n').splitlines()
                lines += ['', f'Encoder ({encoder_log.name}):', *[row for row in tail if row.strip()][-25:]]
        report = '\n'.join(lines)
        if WINDOWS or MAC:
            subprocess.run(['clip'] if WINDOWS else ['pbcopy'], input=report.encode('utf-16le' if WINDOWS else 'utf-8'),
                           timeout=10, creationflags=NO_WINDOW)
        return report

    def check_update(self):
        """Look for a newer release. Returns its version, or None when the app is up to date."""
        try:
            self._update = updates.find(__version__)
        except Exception:
            return dict(error="Couldn't check for updates")
        return dict(version=self._update and self._update['version'])

    def install_update(self):
        """Download the release that check_update found, run its installer, and close the app so it can be replaced."""
        with self._lock:
            if self._running():
                return dict(error='To update, stop streaming')
            self._updating = True
        try:
            installer = updates.download(self._update, data_dir()/'updates')
            if MAC:
                app = Path(sys.executable).parents[2]  # Goggles Bridge.app/Contents/MacOS/Goggles Bridge
                subprocess.Popen(['/bin/sh', '-c', updates.SWAP, 'swap', str(installer), str(app), str(os.getpid())],
                                 start_new_session=True)
            else:
                # silent mode skips the wizard pages, and the installer reopens the app when it finishes
                subprocess.Popen([str(installer), '/SILENT', '/SUPPRESSMSGBOXES'])
        except Exception:
            self._updating = False
            return dict(error="Couldn't install the update")
        self._quit()
        return dict(ok=True)

    def open_link(self, name):
        """Open a known page, or the folder that holds the logs."""
        if name == 'logs':
            folder = data_dir()/'logs'
            folder.mkdir(parents=True, exist_ok=True)
            if WINDOWS:
                os.startfile(folder)
            else:
                subprocess.run(['open' if MAC else 'xdg-open', str(folder)])
        elif name == 'screen':
            screen_access(request=True)
            subprocess.run(['open', LINKS['screen']])
        elif name in LINKS:
            webbrowser.open(LINKS[name])
        return dict(ok=True)


def has_webview2():
    """Return whether the WebView2 Runtime, which draws the window on Windows, is installed."""
    import winreg
    client = r'Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    for root, path in ((winreg.HKEY_LOCAL_MACHINE, rf'SOFTWARE\WOW6432Node\{client}'),
                       (winreg.HKEY_LOCAL_MACHINE, rf'SOFTWARE\{client}'), (winreg.HKEY_CURRENT_USER, rf'Software\{client}')):
        try:
            with winreg.OpenKey(root, path) as key:
                if winreg.QueryValueEx(key, 'pv')[0] not in ('', '0.0.0.0'):
                    return True
        except OSError:
            pass
    return False


def tint_title_bar(window):
    """Match the Windows title bar to the window's light ground."""
    try:
        handle = C.c_void_p(window.native.Handle.ToInt64())
        for attribute, value in ((20, 0), (35, 0x00F7F5F5)):  # light mode, then caption color as 0x00BBGGRR
            C.WinDLL('dwmapi').DwmSetWindowAttribute(handle, attribute, C.byref(C.c_int(value)), 4)
    except Exception:
        pass  # cosmetic only


def main():
    import webview
    self_test = '--self-test' in sys.argv
    api = Desktop(identify=(lambda: None) if self_test else identify)
    if WINDOWS and not self_test and not has_webview2():
        # the fallback renderer cannot run the interface, so say what is missing before the window opens
        text = ('Goggles Bridge needs the Microsoft Edge WebView2 Runtime to show its window.\n\n'
                'To open the download page, select OK.')
        if C.windll.user32.MessageBoxW(None, text, APP_NAME, 0x31) == 1:  # OK and Cancel, with a warning icon
            webbrowser.open(LINKS['webview2'])
    window = webview.create_window(APP_NAME, str(UI/'index.html'), js_api=api, width=1120, height=740,
                                   min_size=(940, 660), background_color='#F5F5F7', hidden=self_test)
    window.events.closed += api._stop.set
    api._quit = window.destroy
    # the installer left by the last update
    shutil.rmtree(data_dir()/'updates', ignore_errors=True)
    if WINDOWS:
        window.events.shown += lambda: tint_title_bar(window)
    drawn = []

    def check():
        # the packaged app passes when its window draws a status from the backend
        for _ in range(40):
            time.sleep(.25)
            if window.evaluate_js("document.getElementById('version').textContent"):
                drawn.append(True)
                break
        window.destroy()

    if not self_test:
        api.start_monitor()
    try:
        webview.start(check if self_test else None)
    finally:
        api.close()
    if self_test and not drawn:
        raise SystemExit(1)
