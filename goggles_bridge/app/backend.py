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
from ..engine import CHOICES, MAX_FRAME_BYTES, NO_WINDOW, BridgeEngine, BridgeSettings, check_encoder, default_windows_encoder, find_program
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


def data_dir():
    if WINDOWS:
        return Path(os.environ.get('LOCALAPPDATA', Path.home()), APP_NAME)
    if MAC:
        return Path.home()/'Library'/'Application Support'/APP_NAME
    return Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local'/'share'), 'goggles-bridge')


def find_ffmpeg():
    """Return the FFmpeg shipped beside a packaged app, else GOGGLES_FFMPEG, else the one on PATH."""
    bundled = Path(sys.executable).parent/'ffmpeg'/('ffmpeg.exe' if WINDOWS else 'ffmpeg')
    found = bundled if bundled.is_file() else os.environ.get('GOGGLES_FFMPEG') or find_program('ffmpeg')
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
            for reply in decoder.feed(usb.read(timeout_ms=50) or b''):
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
    # encoder stays None, so the engine detects NVENC or AMF; Windows capture follows that encoder
    capture = 'screencapturekit' if MAC else BridgeSettings(None, None).capture
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
    def __init__(self, *, settings_path=None, engine_factory=BridgeEngine, check=check_encoder, identify=identify):
        self._settings_path = Path(settings_path or data_dir()/'settings.json')
        self._engine_factory, self._check, self._identify = engine_factory, check, identify
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
        self._state = dict(phase='idle', problem=None, stats=None, oversize=0, log=None)
        self._checks = (0, None)
        self._displays = []
        self._ffmpeg = find_ffmpeg()
        self._native_ffmpeg = None
        self._native_runtime = None
        if WINDOWS and engine_factory is BridgeEngine and check is check_encoder:
            from .windows.paths import native_ffmpeg_path
            from .windows.runtime import WindowsRuntime
            self._native_ffmpeg = native_ffmpeg_path()
            if self._native_ffmpeg is not None:
                self._native_runtime = WindowsRuntime()
        self._options = default_options()
        self._onboarded = False
        try:
            saved = json.loads(self._settings_path.read_text(encoding='utf-8'))
            self._onboarded = bool(saved.get('onboarded'))
            self._settings({**self._options, **{k: v for k, v in saved.items() if k in OPTIONS}})
        except (OSError, ValueError, TypeError, AttributeError):
            pass  # keep the defaults when nothing valid is saved

    def _settings(self, options):
        """Validate options and adopt them; the engine's own rules decide what is allowed."""
        merged = {**self._options, **{k: v for k, v in options.items() if k in OPTIONS}}
        settings = BridgeSettings(find_dll(), self._selected_ffmpeg(merged), **merged)
        self._options = merged
        return settings

    def _selected_ffmpeg(self, options=None):
        selected = self._options if options is None else options
        if (self._native_ffmpeg is not None and selected['capture'] == 'ddagrab'
                and (selected['encoder'] or default_windows_encoder()) == 'nvenc'):
            return self._native_ffmpeg
        return self._ffmpeg

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
            ffmpeg = self._selected_ffmpeg()
            result = dict(driver=dict(needed=WINDOWS, ok=not WINDOWS or find_dll().is_file()),
                          screen=dict(needed=MAC, ok=not MAC or screen_access()),
                          ffmpeg=dict(needed=needs_ffmpeg, ok=not needs_ffmpeg or bool(ffmpeg and ffmpeg.is_file())),
                          attached=goggles_attached())
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
        return (self._thread is not None and self._thread.is_alive()
                or self._native_runtime is not None and self._native_runtime.busy())

    def snapshot(self):
        """Return everything the window draws."""
        with self._lock:
            state = dict(self._state)
        checks = self._preflight()  # first, because a disconnect clears the identity
        state['device'] = self._device or None
        if not self._running() or not self._displays:
            self._displays = list_displays()
            if self._displays and self._options['display_index'] not in {d['index'] for d in self._displays}:
                # the saved display is gone, so fall back to the main one
                self._options['display_index'] = next((d['index'] for d in self._displays if d['primary']), 0)
        return dict(app=dict(name=APP_NAME, version=__version__, platform=sys.platform, updatable=UPDATABLE),
                    checks=checks, displays=self._displays, options=dict(self._options),
                    choices=dict(fps=CHOICES['fps'], capture=CAPTURES, preset=CHOICES['preset'],
                                 keyframe_seconds=CHOICES['keyframe_seconds'], h264_profile=CHOICES['h264_profile'],
                                 usb_write_size=CHOICES['usb_write_size'], bitrates=self._bitrates()),
                    frame_limit=MAX_FRAME_BYTES, onboarded=self._onboarded, **state)

    def set_options(self, options):
        """Adopt and save changed options. Returns the problem when the engine refuses them."""
        try:
            self._settings(options)
        except (ValueError, TypeError) as exc:
            return dict(error=str(exc))
        self._save()
        return dict(ok=True)

    def finish_setup(self):
        """Remember that the setup guide was finished or skipped."""
        self._onboarded = True
        self._save()
        return dict(ok=True)

    def _save(self):
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._settings_path.write_text(json.dumps(dict(self._options, onboarded=self._onboarded), indent=1),
                                       encoding='utf-8')

    def start(self):
        with self._lock:
            if self._running():
                return dict(ok=True)
            if self._updating:
                return dict(ok=False)  # the app is about to close
            checks = self._preflight()
            for name in ('driver', 'screen', 'ffmpeg'):
                if not checks[name]['ok']:
                    self._state.update(phase='error', problem=dict(code=name, message=f'{name} not found'))
                    return dict(ok=False)
            settings = self._settings({})
            log = data_dir()/'logs'/f'{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.jsonl'
            self._stop.clear()
            self._state.update(phase='checking', problem=None, stats=None, oversize=0, log=str(log))
            self._thread = threading.Thread(target=self._run, args=(settings, log), daemon=True)
            self._thread.start()
        return dict(ok=True)

    def stop(self):
        self._stop.set()
        return dict(ok=True)

    def _fail(self, message):
        with self._lock:
            self._state.update(phase='error', problem=dict(code=problem_code(message), message=message))

    def _run(self, settings, log):
        try:
            if self._probe:
                self._probe.join(5)  # the stream needs the USB interface to itself
            if self._native_runtime is not None and settings.capture == 'ddagrab' and settings.encoder == 'nvenc':
                target = next((d for d in self._displays if d['index'] == settings.display_index), None)
                if not target or not target.get('device'):
                    raise RuntimeError('The selected display is no longer available')
                self._native_runtime.run(settings, target['device'], log, self._stop, self._event)
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
            with self._lock:
                if self._state['phase'] != 'error':
                    self._state.update(phase='idle', stats=None, problem=None)

    def _event(self, row):
        event = row['event']
        with self._lock:
            state = self._state
            if event == 'waiting':
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
        ffmpeg = self._selected_ffmpeg()
        lines = [f'{APP_NAME} {__version__}', f'{platform.platform()} | Python {platform.python_version()}',
                 f'FFmpeg: {ffmpeg}', f'Checks: {json.dumps(self._preflight())}',
                 f'Options: {json.dumps(self._options)}',
                 f"State: {state['phase']} {json.dumps(state['problem'])} {json.dumps(self._device or None)}"]
        if ffmpeg and ffmpeg.is_file():
            version = subprocess.run([str(ffmpeg), '-hide_banner', '-version'], capture_output=True, text=True,
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
    api = Desktop()
    self_test = '--self-test' in sys.argv
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

    webview.start(check if self_test else None)
    api.stop()
    if api._thread:
        api._thread.join(timeout=5)
    if self_test and not drawn:
        raise SystemExit(1)
