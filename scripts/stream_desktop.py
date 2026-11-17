"""Stream the Windows or macOS desktop to stock DJI Goggles 2 in Virtual Flight mode."""
import argparse
from dataclasses import fields
from datetime import datetime
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from goggles_bridge import mac_capture
from goggles_bridge.engine import CHOICES, HEIGHT, WIDTH, BridgeEngine, BridgeSettings, check_encoder, find_program
from goggles_bridge.usb_transport import DEFAULT_DLL, find_dll

MAC = sys.platform == 'darwin'
MAC_CAPTURE = 'screencapturekit' if MAC and mac_capture.supported() else 'avfoundation'
FFMPEG_INSTALL = 'brew install ffmpeg' if MAC else 'winget install Gyan.FFmpeg'
SETUP_HINTS = {
    'dll': 'DJI USB driver not found. Install DJI Assistant 2 (Consumer Drones Series), or pass --dll',
    'ffmpeg': f'FFmpeg not found. Run "{FFMPEG_INSTALL}", or pass --ffmpeg',
}


def ask(question):
    try:
        return input(f'{question} [y/N] ').strip().lower() in ('y', 'yes')
    except EOFError:
        return False


def install_mac_dependencies(parser, args):
    """Offer to install the developer tools, FFmpeg, and libusb when the chosen capture needs them."""
    if args.capture == 'screencapturekit' and subprocess.run(['xcode-select', '-p'], capture_output=True).returncode:
        if not ask("Apple's command-line developer tools are needed to build the capture helper. Install them?"):
            parser.error('Run "xcode-select --install", then try again')
        subprocess.run(['xcode-select', '--install'])
        parser.error('Finish installing the command-line developer tools, then run this again')
    import usb.backend.libusb1
    missing = [name for name, absent in (('ffmpeg', args.capture == 'avfoundation' and args.ffmpeg is None),
                                         ('libusb', usb.backend.libusb1.get_backend() is None)) if absent]
    if not missing:
        return
    names, command = ' and '.join(missing), f'brew install {" ".join(missing)}'
    brew = shutil.which('brew') or next((p for p in ('/opt/homebrew/bin/brew', '/usr/local/bin/brew')
                                         if Path(p).is_file()), None)
    if brew is None:
        parser.error(f'{names} not found. Install Homebrew from https://brew.sh, then run "{command}"')
    if not ask(f'{names} not found. Install with "{command}"?'):
        parser.error(f'Run "{command}", then try again')
    if subprocess.run([brew, 'install', *missing]).returncode != 0:
        parser.error(f'"{command}" failed')
    if args.ffmpeg is None:
        found = shutil.which('ffmpeg') or shutil.which('ffmpeg', path=str(Path(brew).parent))
        args.ffmpeg = Path(found) if found else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    # destinations match BridgeSettings fields
    parser.add_argument('--dll', type=Path,
                        help='Windows only: DJI x64 libusb0_device.dll (default: DJI_USB_DLL or the installed driver copy)')
    parser.add_argument('--ffmpeg', type=Path, default=os.environ.get('GOGGLES_FFMPEG') or find_program('ffmpeg'),
                        help='FFmpeg executable with NVENC, AMF or VideoToolbox and the chosen capture (default: GOGGLES_FFMPEG or PATH)')
    parser.add_argument('--python-deps', type=Path, help='Optional directory containing PyUSB 1.3.1')
    parser.add_argument('--fps', type=int, choices=CHOICES['fps'], default=BridgeSettings.fps,
                        help='Target encoder frame rate (default: %(default)s)')
    parser.add_argument('--bitrate-mbps', type=int, choices=CHOICES['bitrate_mbps'],
                        help='Video bitrate (Windows default: 24 at 60 fps, 30 at 75 fps, otherwise 32; macOS: 20 Mbps)')
    parser.add_argument('--aq', dest='adaptive_quant', action='store_true',
                        help='Turn on adaptive quantization (Windows only)')
    parser.add_argument('--capture', choices=('screencapturekit', 'avfoundation') if MAC else ('gfxcapture', 'ddagrab'),
                        default=MAC_CAPTURE if MAC else BridgeSettings.capture,
                        help='Windows: Graphics Capture with GPU scaling, or Desktop Duplication with CPU scaling '
                             '(default: Desktop Duplication with AMF, otherwise Graphics Capture). '
                             'macOS: ScreenCaptureKit on 12.3 and later, or AVFoundation through FFmpeg')
    parser.add_argument('--capture-fps', type=int, default=BridgeSettings.capture_fps,
                        help='Maximum capture rate (default: 1000 for Windows Graphics Capture, otherwise 240)')
    parser.add_argument('--display', dest='display_index', metavar='DISPLAY', type=int,
                        default=BridgeSettings.display_index,
                        help='Zero-based monitor index')
    parser.add_argument('--hide-cursor', dest='show_cursor', action='store_false')
    parser.add_argument('--encoder', choices=CHOICES['encoder'], default=BridgeSettings.encoder,
                        help='Windows hardware encoder: NVIDIA NVENC or AMD AMF (default: auto-detected)')
    parser.add_argument('--preset', choices=CHOICES['preset'], default=BridgeSettings.preset,
                        help='Windows encoder preset (default: %(default)s)')
    parser.add_argument('--h264-profile', choices=CHOICES['h264_profile'], default=BridgeSettings.h264_profile,
                        help='H.264 profile (default: %(default)s)')
    parser.add_argument('--keyframe-seconds', type=int, choices=CHOICES['keyframe_seconds'],
                        default=BridgeSettings.keyframe_seconds)
    parser.add_argument('--low-latency', action=argparse.BooleanOptionalAction, default=BridgeSettings.low_latency,
                        help='Release complete encoded frames immediately and remove H.264 filler data (default: on)')
    parser.add_argument('--usb-write-size', type=int, choices=CHOICES['usb_write_size'],
                        default=BridgeSettings.usb_write_size, help='Maximum bytes per USB write (default: %(default)s)')
    parser.add_argument('--seconds', type=float, default=0, help='Duration in seconds, including reconnects (0 runs until stopped)')
    parser.add_argument('--no-reconnect', action='store_true', help='Exit on USB or heartbeat loss')
    parser.add_argument('--stop-file', type=Path, help='Stop if this file is created')
    parser.add_argument('--log', type=Path, help='Path for a new JSON Lines log (default: a unique file in work/logs)')
    args = parser.parse_args()
    if args.stop_file and args.stop_file.exists():
        parser.error('--stop-file already exists; use a new path or remove the old stop marker')
    if args.python_deps:
        sys.path.insert(0, str(args.python_deps.resolve()))
    try:
        import usb
    except ImportError:
        usb = None
    if getattr(usb, '__version__', None) != '1.3.1':
        parser.error('PyUSB 1.3.1 is required. Run "python -m pip install -r requirements.txt"')
    if MAC:
        install_mac_dependencies(parser, args)
    if args.capture == 'screencapturekit':
        if not mac_capture.helper_path().is_file():
            print('Building the screen capture helper...', flush=True)
        try:
            mac_capture.build()
        except RuntimeError as exc:
            parser.error(str(exc))
    dll = find_dll(args.dll)
    if not MAC and not dll.is_file():
        parser.error(SETUP_HINTS['dll'] if dll == DEFAULT_DLL else f'--dll file not found: {dll}')
    if args.capture != 'screencapturekit' and (args.ffmpeg is None or not args.ffmpeg.is_file()):
        parser.error(SETUP_HINTS['ffmpeg'] if args.ffmpeg is None else f'--ffmpeg file not found: {args.ffmpeg}')
    stop = threading.Event()
    log_path = args.log or ROOT / 'work' / 'logs' / f'{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.jsonl'

    def report(row):
        event = row['event']
        if event == 'waiting':
            print(f"Waiting / reconnecting: {row['message']}", flush=True)
        elif event == 'streaming':
            print(f'Streaming {WIDTH}x{HEIGHT} at target {settings.fps} fps, {settings.bitrate_mbps} Mbps. '
                  'Ctrl+C stops.', flush=True)
        elif event == 'stats':
            print(f"Sent {row['fps']:.1f} fps | queue p95 {row['queue_ms_p95']:.1f} ms | send p95 {row['send_ms_p95']:.1f} ms"
                  f" | largest frame {row['frame_bytes_max']/1000:.0f} KB", flush=True)
        elif event == 'oversize_frame':
            print(f"Skipped a {row['bytes']/1000:.0f} KB frame, over the {row['limit']/1000:.0f} KB limit. "
                  'If this repeats, lower --bitrate-mbps.', flush=True)
        elif event == 'ready':
            print(f"Found {row['model']} ({row['identity']})", flush=True)
        elif event == 'encoder_restart':
            print('Restarting video after an oversized frame.', flush=True)
        elif event in ('connected', 'stopped'):
            print(event.capitalize(), flush=True)

    try:
        settings = BridgeSettings(**{field.name: getattr(args, field.name) for field in fields(BridgeSettings)})
        print('Checking screen capture...', flush=True)
        problem = check_encoder(settings)
        if problem:
            print(problem, file=sys.stderr)
            return 1
        engine = BridgeEngine(settings, log_path, on_event=report, stop_event=stop,
            stop_file=args.stop_file, duration=args.seconds, reconnect=not args.no_reconnect)
        previous_handler = signal.signal(signal.SIGINT, lambda *_: stop.set())
        print(f'Log: {log_path}\nPower the goggles and open More > DJI Virtual Flight.', flush=True)
        try:
            engine.run()
        finally:
            signal.signal(signal.SIGINT, previous_handler)
    except (Exception, KeyboardInterrupt) as exc:
        print(f'Bridge stopped: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
