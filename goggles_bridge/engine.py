"""Capture the desktop and stream H.264 over the Goggles 2 PC USB route."""
from contextlib import closing
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

from .annexb import AccessUnitStream, is_idr
from .avi import AviPacketStream
from .control import V1Stream
from .mac_capture import helper_path
from .pc_video import PcVideoPacketizer
from .session import ControlSession, SessionLost
from .usb_transport import ControlUsb, UsbTransportError, USB_WRITE_SIZES

# the frame size the goggles display
WIDTH, HEIGHT = 1920, 1080
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
# winget adds this folder to PATH, but terminals opened before the install miss it
WINGET_LINKS = Path(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'WinGet', 'Links')
CHOICES = dict(fps=(60, 75, 90, 100), bitrate_mbps=(8, 10, 12, 16, 20, 24, 30, 32, 40),
               capture=('gfxcapture', 'ddagrab', 'avfoundation', 'screencapturekit'), preset=('p1', 'p4'),
               keyframe_seconds=(1, 3), h264_profile=('baseline', 'high'), usb_write_size=USB_WRITE_SIZES)
# Goggles 2 displayed frames up to 49 KB, but keyframes of about 65 KB froze it or left it
# black until a power cycle. The encoder buffer is capped at this size, and larger frames aren't sent
MAX_FRAME_BYTES = 56_000
MAX_VBV_BITS = MAX_FRAME_BYTES * 8
# Largest tested average frame, 40 Mbps at 100 fps
MAX_AVERAGE_FRAME_BYTES = 50_000


def find_program(name):
    return shutil.which(name) or shutil.which(name, path=str(WINGET_LINKS))


@dataclass(frozen=True)
class BridgeSettings:
    dll: Path
    ffmpeg: Path
    fps: int = 100
    bitrate_mbps: int | None = None
    capture: str = 'gfxcapture'
    capture_fps: int = 240
    display_index: int = 0
    show_cursor: bool = True
    preset: str = 'p1'
    keyframe_seconds: int = 3
    low_latency: bool = True
    usb_write_size: int = 16384
    h264_profile: str = 'high'
    # NVENC spatial and temporal adaptive quantization, off until its goggles latency is measured
    adaptive_quant: bool = False

    @property
    def nvenc(self):
        """Windows captures encode with NVENC, the only encoder whose frame-size cap is verified on goggles."""
        return self.capture in ('gfxcapture', 'ddagrab')

    def __post_init__(self):
        def check(name):
            value, choices = getattr(self, name), CHOICES[name]
            if type(value) is not type(choices[0]) or value not in choices:
                raise ValueError(f'Unsupported {name}: {value}')

        # the default bitrate depends on fps
        check('fps')
        if self.bitrate_mbps is None:
            object.__setattr__(self, 'bitrate_mbps',
                               min(32, self.fps*8*MAX_AVERAGE_FRAME_BYTES//1_000_000) if self.nvenc else 20)
        for name in ('low_latency', 'adaptive_quant'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f'{name} must be a boolean')
        for name in CHOICES:
            check(name)
        if self.adaptive_quant and not self.nvenc:
            raise ValueError('Adaptive quantization needs the Windows NVENC encoder')
        # shortcut: only the NVENC buffer cap is verified on goggles, so macOS keeps the earlier
        # 24 Mbps ceiling and its frames are never skipped; lift both once a Mac cap is verified
        if not self.nvenc and self.bitrate_mbps > 24:
            raise ValueError('macOS capture supports at most 24 Mbps')
        # The buffer cap bounds keyframes, but in CBR every frame averages bitrate/fps
        if self.bitrate_mbps * 1_000_000 // (8 * self.fps) > MAX_AVERAGE_FRAME_BYTES:
            limit = max(b for b in CHOICES['bitrate_mbps'] if b * 1_000_000 // (8 * self.fps) <= MAX_AVERAGE_FRAME_BYTES)
            raise ValueError(f'At {self.fps} fps, use at most {limit} Mbps. '
                             f'{self.bitrate_mbps} Mbps makes frames too large for the goggles')
        if type(self.capture_fps) is not int or not self.fps <= self.capture_fps <= 1000:
            raise ValueError('Capture ceiling must be between output fps and 1000')
        if type(self.display_index) is not int or self.display_index < 0:
            raise ValueError('Display index must be a nonnegative integer')


def encoder_command(settings, frames=0):
    """Return the capture and encoder command; with frames, encode that many pictures and discard them."""
    bitrate = settings.bitrate_mbps * 1_000_000
    if settings.capture == 'screencapturekit':
        command = [str(helper_path()), '--display', str(settings.display_index), '--fps', str(settings.fps),
                   '--capture-fps', str(settings.capture_fps), '--bitrate', str(bitrate),
                   '--keyframe-seconds', str(settings.keyframe_seconds), '--profile', settings.h264_profile,
                   '--format', 'avi' if settings.low_latency else 'h264']
        return (command + ([] if settings.show_cursor else ['--hide-cursor'])
                + (['--frames', str(frames)] if frames else []))
    # More NVENC bitrate must not enlarge the previous 20 Mbps buffer budget
    vbv = min(min(bitrate, 20_000_000)*2//settings.fps, MAX_VBV_BITS) if settings.nvenc else bitrate*2//settings.fps
    rate = ['-b:v', str(bitrate), '-maxrate', str(bitrate), '-bufsize', str(vbv), '-bf', '0',
            '-g', str(settings.fps*settings.keyframe_seconds), '-level:v', '4.2' if settings.fps == 60 else '5.1',
            '-flush_packets', '1']
    command = [str(Path(settings.ffmpeg).resolve()), '-hide_banner', '-nostdin', '-loglevel', 'info']
    if settings.capture == 'avfoundation':
        # Scale Retina captures on the GPU, then pad to the frame the goggles expect
        wide = 'gte(iw/ih,16/9)'
        command += ['-init_hw_device', 'videotoolbox=vt', '-filter_hw_device', 'vt',
                    '-f', 'avfoundation', '-capture_cursor', str(int(settings.show_cursor)),
                    '-framerate', str(settings.capture_fps), '-pixel_format', 'nv12',
                    '-i', f'Capture screen {settings.display_index}:none', '-r', str(settings.fps), '-fps_mode', 'cfr',
                    '-vf', f"hwupload,scale_vt=w='if({wide},{WIDTH},-2)':h='if({wide},-2,{HEIGHT})',hwdownload,"
                           f'format=nv12,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2',
                    # low_delay enables low-latency rate control, which rejects plain baseline
                    '-an', '-c:v', 'h264_videotoolbox', '-realtime', '1', '-prio_speed', '1', '-flags', '+low_delay',
                    '-profile:v', 'constrained_baseline' if settings.h264_profile == 'baseline' else 'high', *rate,
                    # VideoToolbox writes no AUDs, which both frame readers need
                    '-bsf:v', 'h264_metadata=aud=insert']
    else:
        if settings.capture == 'gfxcapture':
            source = (f'gfxcapture=monitor_idx={settings.display_index}:max_framerate={settings.capture_fps}'
                      f':width={WIDTH}:height={HEIGHT}:resize_mode=scale_aspect:scale_mode=bicubic'
                      f':capture_cursor={int(settings.show_cursor)}')
            # ld(0) holds the next eligible timestamp with at most one frame of jitter credit
            pacing = ("select='if(isnan(prev_selected_pts),st(0,pts*TB);1,"
                      "if(gte((pts+0.5)*TB,ld(0)),"
                      f"st(0,max(ld(0)+1/{settings.fps},pts*TB));1,0))',"
                      # Compact capture gaps so CFR does not replay stale pictures to catch up
                      f'setpts=N/({settings.fps}*TB):strip_fps=1')
            command += ['-f', 'lavfi', '-i', source, '-vf', pacing,
                        '-r', str(settings.fps), '-fps_mode', 'cfr']
        else:
            source = (f'ddagrab=output_idx={settings.display_index}:framerate={settings.fps}'
                      f':draw_mouse={int(settings.show_cursor)}')
            command += ['-f', 'lavfi', '-i', source, '-vf',
                        f'hwdownload,format=bgra,scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:'
                        f'flags=fast_bilinear,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=nv12']
        command += ['-an', '-c:v', 'h264_nvenc', '-preset', settings.preset, '-tune', 'ull', '-rc', 'cbr',
                    '-zerolatency', '1', '-delay', '0', '-profile:v', settings.h264_profile, *rate,
                    '-aud', '1', '-forced-idr', '1',
                    '-multipass', 'qres', '-intra-refresh', '1', '-single-slice-intra-refresh', '1']
        if settings.adaptive_quant:
            command += ['-spatial-aq', '1', '-temporal-aq', '1']
        if settings.low_latency:
            command += ['-bsf:v', 'filter_units=remove_types=12']
    if settings.low_latency:
        command += ['-thread_queue_size', '1']
    if frames:
        return command + ['-frames:v', str(frames), '-f', 'null', '-']
    return command + ['-f', 'avi' if settings.low_latency else 'h264', 'pipe:1']


def check_encoder(settings, run=subprocess.run):
    """Encode one captured frame and return a setup problem, or None if the encoder can stream."""
    command = encoder_command(settings, frames=1)
    try:
        result = run(command, capture_output=True, text=True, errors='replace', timeout=30, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return 'No frame was captured within 30 seconds'
    if result.returncode == 0:
        return None
    details = '\n  '.join(result.stderr.strip().splitlines()[-3:])
    if settings.capture == 'screencapturekit':
        return f'Screen capture test failed.\n  {details}'
    if settings.capture == 'avfoundation':
        if 'Filter not found' in result.stderr or 'Encoder not found' in result.stderr:
            return 'This FFmpeg build lacks VideoToolbox support. Update it with "brew upgrade ffmpeg"'
        return ('FFmpeg test encode failed. In System Settings > Privacy & Security, allow screen recording '
                f'for this terminal, and check the --display index.\n  {details}')
    if 'Filter not found' in result.stderr:
        return (f'This FFmpeg build has no {settings.capture} capture. '
                'Update it with "winget upgrade Gyan.FFmpeg", or try --capture ddagrab')
    if 'Encoder not found' in result.stderr:
        return 'This FFmpeg build has no NVIDIA encoder. Install it with "winget install Gyan.FFmpeg"'
    return f'FFmpeg test encode failed. Check the NVIDIA driver and --display index.\n  {details}'


def _validate_gpu_priority_class(priority_class):
    if priority_class is not None and (type(priority_class) is not int or not 0 <= priority_class <= 5):
        raise ValueError('GPU priority class must be None or an integer from 0 to 5')


def prioritize_gpu(process, priority_class=5):
    """Best-effort GPU scheduling for this encoder's existing Windows handle.

    The default preserves the CLI's realtime policy. None leaves the OS policy
    untouched. Call once after the encoder produces its first frame, when it has
    a graphics context. An unsupported or rejected request is not a stream error.
    """
    _validate_gpu_priority_class(priority_class)
    if priority_class is None or sys.platform != 'win32':
        return False
    import ctypes
    try:
        handle = getattr(process, '_handle', None)
        if handle is None or type(handle) is bool or getattr(handle, 'closed', False):
            return False
        handle = int(handle)
        # NULL, negative/pseudo handles and their unsigned representations must
        # never target this process or thread by accident. No PID-based fallback.
        if not 0 < handle < 1 << (ctypes.sizeof(ctypes.c_void_p)*8-1):
            return False
        # Restrict DLL resolution to System32 instead of the working directory.
        library = ctypes.WinDLL('gdi32.dll', winmode=0x00000800)
        set_class = library.D3DKMTSetProcessSchedulingPriorityClass
        set_class.argtypes = [ctypes.c_void_p, ctypes.c_int32]  # HANDLE, enum
        set_class.restype = ctypes.c_int32  # NTSTATUS is 32-bit on Windows x64.
        return set_class(handle, priority_class) == 0
    except (OSError, AttributeError, TypeError, ValueError, OverflowError):
        return False


class EventLog:
    """Write timestamped JSON Lines rows to a new file."""
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open('x', encoding='utf-8')
        self.started = time.perf_counter()

    def __call__(self, event, **fields):
        row = dict(seconds=round(time.perf_counter()-self.started, 6), event=event, **fields)
        self.stream.write(json.dumps(row)+'\n')
        self.stream.flush()
        return row

    def close(self):
        self.stream.close()


class BridgeEngine:
    """Manage the encoder and USB session, reconnecting after link loss."""
    def __init__(self, settings, log_path, *, on_event=None, stop_event=None,
                 stop_file=None, duration=0, reconnect=True, retry_delay=1,
                 transport_factory=None, process_factory=subprocess.Popen,
                 gpu_priority_class=5):
        if not math.isfinite(duration) or duration < 0:
            raise ValueError('Duration must be nonnegative and finite')
        if not math.isfinite(retry_delay) or retry_delay < 0:
            raise ValueError('Retry delay must be nonnegative and finite')
        _validate_gpu_priority_class(gpu_priority_class)
        self.settings = settings
        self.log_path = Path(log_path)
        self.on_event = on_event or (lambda event: None)
        self.stop_event = stop_event or threading.Event()
        self.stop_file = Path(stop_file) if stop_file else None
        self.duration = duration
        self.reconnect = reconnect
        self.retry_delay = retry_delay
        self.transport_factory = (partial(ControlUsb, write_size=settings.usb_write_size)
                                  if transport_factory is None else transport_factory)
        self.process_factory = process_factory
        self.gpu_priority_class = gpu_priority_class
        self.log = None
        self.waiting = None

    def stopping(self):
        return (self.stop_event.is_set() or (self.stop_file is not None and self.stop_file.exists())
                or (self.duration > 0 and time.perf_counter()-self.log.started >= self.duration))

    def emit(self, event, **fields):
        self.on_event(self.log(event, **fields))

    def run(self):
        with closing(EventLog(self.log_path)) as self.log:
            settings = {name: value for name, value in asdict(self.settings).items() if name not in ('dll', 'ffmpeg')}
            self.emit('starting', resolution=f'{WIDTH}x{HEIGHT}', intra_refresh=self.settings.nvenc,
                      multipass='qres' if self.settings.nvenc else 'disabled', **settings)
            try:
                attempt = 0
                while not self.stopping():
                    attempt += 1
                    try:
                        self._session(attempt)
                    except (UsbTransportError, SessionLost) as exc:
                        if not self.reconnect:
                            raise
                        if self.waiting != str(exc):
                            self.emit('waiting', message=str(exc))
                        self.waiting = str(exc)
                        retry_at = time.perf_counter()+self.retry_delay
                        while not self.stopping() and time.perf_counter() < retry_at:
                            self.stop_event.wait(min(.1, max(0, retry_at-time.perf_counter())))
            except Exception as exc:
                self.emit('error', message=str(exc))
                raise
            finally:
                self.emit('stopped')

    def _session(self, attempt):
        local_stop = threading.Event()
        incoming = queue.Queue(maxsize=256)
        frames = queue.Queue(maxsize=1 if self.settings.low_latency else 3)
        errors = queue.Queue()
        session = ControlSession()
        decoder = V1Stream()
        packetizer = PcVideoPacketizer()
        process = None
        encoder_thread = None
        encoder_stop = threading.Event()
        encoder_first_frame = True
        restart_attempts = 0
        last_restart = None
        threads = []
        frame_count = byte_count = previous_frames = oversize_count = largest_frame = 0
        resync = False
        queue_times, send_times = [], []
        last_frame = last_progress = time.perf_counter()
        encoder_path = self.log_path.with_name(f'{self.log_path.stem}.encoder-{attempt}.log')
        with self.transport_factory(self.settings.dll) as usb:
            self.emit('connected', attempt=attempt)

            def read_usb():
                try:
                    while not local_stop.is_set():
                        data = usb.read(timeout_ms=50)
                        if data:
                            incoming.put(data, timeout=.2)
                except Exception as exc:
                    if not local_stop.is_set():
                        errors.put(exc)

            def read_encoder(encoder):
                splitter = AviPacketStream() if self.settings.low_latency else AccessUnitStream()
                try:
                    while not local_stop.is_set() and not encoder_stop.is_set():
                        data = encoder.stdout.read(16384)
                        if not data:
                            raise RuntimeError(f'Capture ended. See {encoder_path}')
                        for frame in splitter.feed(data):
                            completed_at = time.perf_counter()
                            while not local_stop.is_set() and not encoder_stop.is_set():
                                try:
                                    frames.put((completed_at, frame), timeout=.1)
                                    break
                                except queue.Full:
                                    pass
                except Exception as exc:
                    if not local_stop.is_set() and not encoder_stop.is_set():
                        errors.put(exc)

            def stop_encoder():
                nonlocal process, encoder_thread
                encoder_stop.set()
                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                if process and process.stdout:
                    process.stdout.close()
                if encoder_thread:
                    encoder_thread.join(timeout=1)
                    if encoder_thread.is_alive():
                        raise RuntimeError('Encoder reader did not stop')
                process = encoder_thread = None
                while not frames.empty():
                    frames.get_nowait()

            def start_encoder():
                nonlocal process, encoder_thread, encoder_first_frame, last_frame
                encoder_stop.clear()
                # restarts append to the session's log, and the encoder keeps its own handle
                with encoder_path.open('a', encoding='utf-8') as encoder_log:
                    process = self.process_factory(encoder_command(self.settings), stdout=subprocess.PIPE,
                        stderr=encoder_log, stdin=subprocess.DEVNULL, bufsize=0, creationflags=NO_WINDOW)
                last_frame = time.perf_counter()
                encoder_first_frame = True
                encoder_thread = threading.Thread(target=read_encoder, args=(process,), daemon=True)
                encoder_thread.start()

            def send_control(packet):
                data = packet.serialize()
                usb.write(data)
                self.emit('control_send', hex=data.hex())

            try:
                thread = threading.Thread(target=read_usb, daemon=True)
                threads.append(thread)
                thread.start()
                while not self.stopping():
                    if not errors.empty():
                        raise errors.get_nowait()
                    # Accept queued replies before judging their deadlines
                    while not incoming.empty():
                        data = incoming.get_nowait()
                        self.emit('control_receive', hex=data.hex())
                        for reply in decoder.feed(data):
                            for packet in session.receive(reply, time.perf_counter()):
                                send_control(packet)
                    for packet in session.poll(time.perf_counter()):
                        send_control(packet)
                    if session.state == 'ready' and process is None:
                        self.waiting = None
                        self.emit('ready', model=session.model, identity=session.identity)
                        start_encoder()
                    if session.state == 'ready':
                        try:
                            completed_at, frame = frames.get(timeout=.002)
                        except queue.Empty:
                            if time.perf_counter()-last_frame > 5:
                                raise RuntimeError(f'No video from display. See {encoder_path}')
                            continue
                        last_frame = time.perf_counter()
                        oversize = self.settings.nvenc and len(frame) > MAX_FRAME_BYTES
                        if oversize:
                            oversize_count += 1
                            self.emit('oversize_frame', bytes=len(frame), limit=MAX_FRAME_BYTES)
                            # A fitting IDR alone must not reset repeated oversize failures
                            if last_restart is None or last_frame-last_restart >= 5:
                                restart_attempts = 0
                            restart_attempts += 1
                            last_restart = last_frame
                            stop_encoder()
                            if restart_attempts >= 3:
                                raise RuntimeError('Encoded frames repeatedly exceed the size limit. Lower the bitrate')
                            if not self.stopping():
                                start_encoder()
                                self.emit('encoder_restart', attempt=restart_attempts)
                            resync = True
                            continue
                        # Later frames reference a skipped one, so resume only at a keyframe that fits
                        if resync and not is_idr(frame):
                            continue
                        resync = False
                        largest_frame = max(largest_frame, len(frame))
                        queue_times.append((last_frame-completed_at)*1000)
                        wire = b''.join(packetizer.packetize(frame, session.reserve_sequence))
                        usb.write(wire)
                        send_times.append((time.perf_counter()-last_frame)*1000)
                        byte_count += len(wire)
                        frame_count += 1
                        if encoder_first_frame:
                            applied = prioritize_gpu(process, self.gpu_priority_class)
                            self.emit('streaming', encoder_pid=process.pid,
                                      gpu_realtime=applied and self.gpu_priority_class == 5,
                                      gpu_priority_class=self.gpu_priority_class, gpu_priority_applied=applied)
                            encoder_first_frame = False
                    else:
                        self.stop_event.wait(.002)
                    now = time.perf_counter()
                    if now-last_progress >= 5:
                        def p95(values):
                            return round(sorted(values)[int((len(values)-1)*.95)], 2) if values else 0
                        self.emit('stats', frames=frame_count, bytes=byte_count, queued_frames=frames.qsize(),
                                  fps=round((frame_count-previous_frames)/(now-last_progress), 2),
                                  queue_ms_p95=p95(queue_times), send_ms_p95=p95(send_times),
                                  frame_bytes_max=largest_frame, oversize_frames=oversize_count)
                        previous_frames, last_progress, largest_frame = frame_count, now, 0
                        queue_times.clear()
                        send_times.clear()
            finally:
                local_stop.set()
                try:
                    stop_encoder()
                finally:
                    for thread in threads:
                        thread.join(timeout=1)
                    self.emit('session_ended', frames=frame_count, bytes=byte_count,
                              discarded_bytes=decoder.discarded)
