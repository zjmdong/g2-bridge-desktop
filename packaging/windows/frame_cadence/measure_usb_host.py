"""Bounded host-side timing of the production desktop -> USB path.

No display is created, enabled, reconfigured or removed. The default invocation
only validates arguments; --run explicitly starts capture and USB streaming.
USB write completion is not goggles decode completion or photons-on-lens time.
"""
from __future__ import annotations

import argparse
from array import array
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from desktop_app.device import VerifiedTransport
from desktop_app.encoding import H264_PROFILE
from desktop_app.stream_engine import DesktopBridgeEngine
from desktop_app.video import compatible_command, start_encoder
from goggles_bridge.engine import BridgeSettings, encoder_command
from goggles_bridge.pc_video import MAX_PC_VIDEO_CHUNK
from goggles_bridge.control import V1_MAX_LENGTH, V1_OVERHEAD
from goggles_bridge.duml import VIDEO_HEADER_SIZE
from goggles_bridge.usb_transport import find_dll

FPS = 100
CAPACITY = 20000  # > 3x maximum intended video records; never grows in a run.
EVENT_CAPACITY = 256
NOTICE = ('USB API completed means the host driver accepted the complete write; '
          'it does not measure goggles decode, scanout, or photons-on-lens latency.')


class MemoryJournal:
    """DesktopBridgeEngine logger interface without streaming-time disk I/O."""
    error = None

    def __init__(self, _path):
        self.rows = [None] * EVENT_CAPACITY
        self.count = self.overflow = 0

    def enqueue(self, row):
        if self.count < len(self.rows):
            self.rows[self.count] = dict(row)
            self.count += 1
        else:
            self.overflow += 1

    def close(self):
        return True


class WriteSamples:
    """One writer, preallocated primitive arrays, no per-frame I/O or locks."""
    def __init__(self, capacity=CAPACITY):
        self.before = array('Q', [0]) * capacity
        self.after = array('Q', [0]) * capacity
        self.length = array('I', [0]) * capacity
        self.kind = array('B', [0]) * capacity  # 1 video, 0 control
        self.ok = array('B', [0]) * capacity
        self.count = self.overflow = 0
        self.first_video_ns = 0

    def record(self, before, after, length, video, succeeded):
        if video and succeeded and not self.first_video_ns:
            self.first_video_ns = after
        i = self.count
        if i >= len(self.before):
            self.overflow += 1
            return
        self.before[i], self.after[i], self.length[i] = before, after, length
        self.kind[i], self.ok[i] = video, succeeded
        self.count = i + 1


class TimedVerifiedTransport(VerifiedTransport):
    """Time full video wires, not individual 16 KB backend chunks."""
    def __init__(self, *args, samples, **kwargs):
        self.samples = samples
        self.reader_thread = None
        super().__init__(*args, **kwargs)

    def read(self, **kwargs):
        if self.reader_thread is None:
            self.reader_thread = threading.current_thread()
        return super().read(**kwargs)

    def write(self, data):
        # Same DUML video discriminator as production VerifiedTransport.
        # Preflight happens inside VerifiedTransport.__init__, so those control
        # writes are intentionally excluded from these streaming measurements.
        video = len(data) >= 11 and data[9:11] == b'\x0b\x53'
        before = time.perf_counter_ns()
        try:
            result = super().write(data)
        except BaseException:
            after = time.perf_counter_ns()
            self.samples.record(before, after, len(data), video, False)
            raise
        after = time.perf_counter_ns()
        self.samples.record(before, after, len(data), video, True)
        return result


def wire_estimate(length):
    """Exactly matches current PcVideoPacketizer full-frame concatenation.

    Not a general wire parser: the engine guarantees one complete access unit
    per video write. Full fragments are V1_MAX_LENGTH and each contributes
    V1_OVERHEAD + VIDEO_HEADER_SIZE bytes beyond its encoded payload.
    """
    fragments = (length + V1_MAX_LENGTH - 1) // V1_MAX_LENGTH
    encoded = length - fragments * (V1_OVERHEAD + VIDEO_HEADER_SIZE)
    if encoded < 1 or fragments != (encoded + MAX_PC_VIDEO_CHUNK - 1) // MAX_PC_VIDEO_CHUNK:
        raise ValueError('Write is not a supported full-frame PC video wire')
    return encoded, fragments


def describe(values):
    values = sorted(values)
    if not values:
        return {'count': 0}
    def quantile(q):
        return values[int((len(values) - 1) * q)]
    return dict(count=len(values), min=values[0], mean=statistics.fmean(values),
                p50=quantile(.5), p95=quantile(.95), p99=quantile(.99),
                p999=quantile(.999), max=values[-1])


def summarize(samples, origin, warmup_seconds):
    rows, video_rows, control_rows = [], [], []
    previous_video = None
    for i in range(samples.count):
        before, after = samples.before[i], samples.after[i]
        video = bool(samples.kind[i])
        row = dict(index=i, kind='video' if video else 'control',
                   before_ns=before, after_ns=after, before_since_start_ms=(before-origin)/1e6,
                   duration_ms=(after-before)/1e6, wire_bytes=samples.length[i],
                   completed=bool(samples.ok[i]))
        if video:
            row['encoded_bytes_estimate'], row['fragment_count_estimate'] = wire_estimate(samples.length[i])
            if row['completed']:
                row['completion_interval_ms'] = ((after-previous_video)/1e6
                                                 if previous_video is not None else None)
                previous_video = after
                video_rows.append(row)
        else:
            control_rows.append(row)
        rows.append(row)
    cutoff = samples.first_video_ns + int(warmup_seconds * 1e9)
    stable = [r for r in video_rows if r['before_ns'] >= cutoff]
    gaps = [r['completion_interval_ms'] for r in stable if r['completion_interval_ms'] is not None]
    # Window totals use completion timestamps, not packet timestamps. They are
    # deliberately computed after stop, with exact 1-second bin definitions.
    bins = {}
    for r in stable:
        bucket = (r['after_ns']-cutoff)//1_000_000_000
        value = bins.setdefault(bucket, dict(frames=0, wire_bytes=0, encoded_bytes_estimate=0))
        value['frames'] += 1
        value['wire_bytes'] += r['wire_bytes']
        value['encoded_bytes_estimate'] += r['encoded_bytes_estimate']
    full_bins = []
    if stable:
        end = stable[-1]['after_ns']
        for b, values in sorted(bins.items()):
            if cutoff + (b+1)*1_000_000_000 <= end:
                full_bins.append(dict(start_ns=cutoff+b*1_000_000_000, **values,
                                      wire_mbps=values['wire_bytes']*8/1e6,
                                      encoded_mbps_estimate=values['encoded_bytes_estimate']*8/1e6))
    return dict(records=rows, completed_video_count=len(video_rows), control_write_count=len(control_rows),
                failed_write_count=sum(not r['completed'] for r in rows),
                warmup_seconds=warmup_seconds, steady_video_count=len(stable),
                steady_usb_write_ms=describe([r['duration_ms'] for r in stable]),
                steady_completion_interval_ms=describe(gaps),
                steady_intervals_outside_10ms_plus_minus_1pct=sum(abs(v-10) > .1 for v in gaps),
                steady_full_second_bins=full_bins, records_dropped=samples.overflow)


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=int, choices=(0, 1), required=True,
                        help='Existing active DXGI output index on --adapter; never a new display')
    parser.add_argument('--adapter', type=int, default=0, help='Existing DXGI adapter index (default: 0)')
    parser.add_argument('--ffmpeg', type=Path, default=ROOT/'vendor/ffmpeg/ffmpeg.exe',
                        help='Explicit FFmpeg build; default is bundled release')
    parser.add_argument('--dll', type=Path, default=None, help='Verified DJI USB DLL, default system install')
    parser.add_argument('--duration', type=float, default=20, help='Seconds after first video completion, 20..60')
    parser.add_argument('--timeout', type=float, default=None, help='Overall timeout; default duration + 30 seconds')
    parser.add_argument('--warmup', type=float, default=3, help='Exclude startup IDRs from steady summaries, default 3s')
    parser.add_argument('--output', type=Path, help='New JSON path; existing files are never overwritten')
    parser.add_argument('--run', action='store_true', help='Actually open USB and capture; omitted means dry-run')
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or not 20 <= args.duration <= 60:
        parser.error('--duration must be finite and between 20 and 60 seconds')
    if args.timeout is None:
        args.timeout = args.duration + 30
    if not math.isfinite(args.timeout) or not args.duration + 5 <= args.timeout <= args.duration + 60:
        parser.error('--timeout must be between duration + 5 and duration + 60 seconds')
    if not math.isfinite(args.warmup) or not 0 <= args.warmup < args.duration - 1:
        parser.error('--warmup must be nonnegative and less than duration - 1')
    if not 0 <= args.adapter < 32:
        parser.error('--adapter must be 0..31')
    args.ffmpeg = args.ffmpeg.resolve(strict=True)
    if not args.ffmpeg.is_file():
        parser.error('--ffmpeg must name a file')
    if args.output is None:
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        args.output = Path(__file__).parent/f'usb-host-a{args.adapter}-o{args.source}-{stamp}-{uuid.uuid4().hex[:8]}.json'
    args.output = args.output.resolve()
    if args.output.exists():
        parser.error('--output already exists; choose a unique path')
    return args


def run(args):
    from desktop_app.dxgi import outputs
    matches = [r for r in outputs() if r['adapter'] == args.adapter and r['output'] == args.source]
    if len(matches) != 1:
        raise RuntimeError('Requested DXGI output is not uniquely active; no display was changed')
    output = matches[0]
    bridge = BridgeSettings(dll=find_dll(args.dll), ffmpeg=args.ffmpeg, fps=100,
                            bitrate_mbps=20, preset='p4', capture='ddagrab',
                            display_index=args.source, h264_profile=H264_PROFILE, keyframe_seconds=3)
    command = compatible_command(encoder_command(bridge), output=output, dimensions=(1920, 1080))
    stop, watchdog_done = threading.Event(), threading.Event()
    samples = WriteSamples()
    processes, transports, cleanup_errors = [], [], []
    reason = {'value': 'engine_finished'}
    origin = time.perf_counter_ns()
    failure = None
    engine = None

    def watchdog():
        while not watchdog_done.wait(.02):
            now = time.perf_counter_ns()
            if samples.first_video_ns and now-samples.first_video_ns >= args.duration*1e9:
                reason['value'] = 'duration_reached'
                stop.set()
                return
            if now-origin >= args.timeout*1e9:
                reason['value'] = 'overall_timeout'
                stop.set()
                return

    def transport_factory(dll):
        value = TimedVerifiedTransport(dll, stop=stop, emit=lambda *_a, **_k: None,
                                       write_size=bridge.usb_write_size, samples=samples)
        transports.append(value)
        return value

    def process_factory(command, **kwargs):
        value = start_encoder(command, output=output, dimensions=(1920, 1080), **kwargs)
        processes.append(value)
        return value

    watcher = threading.Thread(target=watchdog, name='usb-host-deadline', daemon=True)
    # The SDK owns a normally empty EventLog plus warning-only encoder stderr.
    # Per-frame write records and SDK events stay in memory until cleanup ends.
    with tempfile.TemporaryDirectory(prefix='g2-usb-host-') as temporary:
        log = Path(temporary)/'session.jsonl'
        try:
            watcher.start()
            engine = DesktopBridgeEngine(bridge, log, stop_event=stop, reconnect=False,
                log_factory=MemoryJournal, process_factory=process_factory,
                transport_factory=transport_factory, presence_probe=lambda: True)
            engine.run()
        except KeyboardInterrupt:
            reason['value'] = 'keyboard_interrupt'
        except BaseException as exc:
            failure = dict(type=type(exc).__name__, message=str(exc))
            reason['value'] = 'error'
        finally:
            stop.set()
            watchdog_done.set()
            watcher.join(timeout=1)
            for process in processes:
                try:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=3)
                    if process.stdout:
                        process.stdout.close()
                except Exception as exc:
                    cleanup_errors.append(f'encoder cleanup: {exc}')
            for transport in transports:
                # SDK already requests its reader exit and joins it before the
                # context closes. Check that outcome; don't hide a live reader.
                reader = transport.reader_thread
                if reader and reader is not threading.current_thread():
                    reader.join(timeout=1)
                    if reader.is_alive():
                        cleanup_errors.append('USB reader still alive after SDK shutdown')
                try:
                    transport.close()
                except Exception as exc:
                    cleanup_errors.append(f'USB cleanup: {exc}')
            if watcher.is_alive():
                cleanup_errors.append('Deadline watcher still alive')
        stderr_logs = {p.name: p.read_text(encoding='utf-8', errors='replace')[-65536:]
                       for p in Path(temporary).glob('*.encoder-*.log')}

    report = dict(schema=1, created_utc=datetime.now(timezone.utc).isoformat(), notice=NOTICE,
        measurement_scope='complete VerifiedTransport.write call on host; preflight control writes excluded',
        encoded_bytes_method='full PC DUML V1 wire length minus 45 bytes per 1023-byte-maximum fragment',
        settings=dict(width=1920, height=1080, fps=100, bitrate_mbps=20, preset='p4',
                      encoder='h264_nvenc', h264_profile=H264_PROFILE, usb_write_size=bridge.usb_write_size),
        source=output, ffmpeg=str(args.ffmpeg), ffmpeg_sha256=hashlib.sha256(args.ffmpeg.read_bytes()).hexdigest(),
        command=command, duration_requested_seconds=args.duration, timeout_seconds=args.timeout,
        host_run_seconds=(time.perf_counter_ns()-origin)/1e9, stop_reason=reason['value'],
        failure=failure, cleanup_errors=cleanup_errors,
        encoder_returncodes=[p.poll() for p in processes],
        transports_closed=[bool(getattr(t.usb, 'closed', False)) for t in transports],
        encoder_stderr=stderr_logs,
        events=engine.journal.rows[:engine.journal.count] if engine and engine.journal else [],
        events_dropped=engine.journal.overflow if engine and engine.journal else 0,
        **summarize(samples, origin, args.warmup))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps(dict(output=str(args.output), stop_reason=report['stop_reason'],
        completed_video_count=report['completed_video_count'],
        steady_usb_write_ms=report['steady_usb_write_ms'],
        steady_completion_interval_ms=report['steady_completion_interval_ms'],
        failure=failure, cleanup_errors=cleanup_errors, notice=NOTICE), ensure_ascii=False, indent=2))
    return 0 if not failure and not cleanup_errors and reason['value'] == 'duration_reached' else 2


def main(argv=None):
    args = arguments(argv)
    if not args.run:
        print(json.dumps(dict(dry_run=True, source=args.source, adapter=args.adapter,
            ffmpeg=str(args.ffmpeg), output=str(args.output), duration=args.duration,
            timeout=args.timeout, settings='1080p / 100 fps / 20 Mbps / NVENC P4',
            notice=NOTICE, next='Add --run to open USB and start capture'), indent=2))
        return 0
    if sys.platform != 'win32':
        raise RuntimeError('This measurement tool requires Windows')
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
