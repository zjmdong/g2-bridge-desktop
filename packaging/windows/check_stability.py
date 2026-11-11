"""Opt-in host capture timing. Discards video; never opens USB or measures lenses.

Reports wall-clock access-unit completion and optional DUML serialization work,
not synthetic CFR timestamps. Run on an unlocked desktop with no other GPU test.
"""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from desktop_app.dxgi import outputs
from desktop_app.video import compatible_command, ENCODER_PRIORITY
from desktop_app.scheduling import configure_encoder_process, STREAM_GPU_PRIORITY_CLASS
from goggles_bridge.engine import BridgeSettings, encoder_command, prioritize_gpu, NO_WINDOW
from goggles_bridge.avi import AviPacketStream
from goggles_bridge.pc_video import PcVideoPacketizer


def distribution(values):
    values = sorted(values)
    if not values:
        return None
    return {key: round(values[int((len(values)-1)*fraction)], 4)
            for key, fraction in [('min', 0), ('p01', .01), ('p50', .5),
                                  ('p95', .95), ('p99', .99), ('max', 1)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', type=Path, default=ROOT/'vendor/ffmpeg/ffmpeg.exe')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=20)
    parser.add_argument('--warmup', type=float, default=3)
    parser.add_argument('--fps', type=int, choices=(60,75,90,100), default=100)
    parser.add_argument('--bitrate', type=int, default=20)
    parser.add_argument('--preset', choices=('p1','p4'), default='p4')
    parser.add_argument('--resolution', choices=('720p','1080p'), default='1080p')
    parser.add_argument('--adapter', type=int, default=0)
    parser.add_argument('--output-index', type=int, default=0)
    parser.add_argument('--legacy-clock', action='store_true')
    parser.add_argument('--fifo', action='store_true', help='Compare the original raw FIFO')
    parser.add_argument('--synchronous', action='store_true', help='Compare NVENC synchronous output')
    parser.add_argument('--packetize', action='store_true', help='Measure CPU DUML framing, without USB writes')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Existing evidence is never overwritten')
    if not 0 <= args.warmup < args.seconds <= 300:
        parser.error('Require 0 <= warmup < seconds <= 300')
    ffmpeg = args.ffmpeg.resolve(strict=True)
    target = next((x for x in outputs() if x['adapter'] == args.adapter and x['output'] == args.output_index), None)
    if target is None:
        parser.error('The requested DXGI output is not attached')
    settings = BridgeSettings(dll=Path('unused.dll'), ffmpeg=ffmpeg, capture='ddagrab',
                              fps=args.fps, bitrate_mbps=args.bitrate, preset=args.preset)
    dims = (1280,720) if args.resolution == '720p' else (1920,1080)
    command = compatible_command(encoder_command(settings), output=target, dimensions=dims)
    command.remove('-nostdin')  # Graceful q gives EOS and the raw replacement count.
    command[command.index('-loglevel')+1] = 'info'
    if args.legacy_clock:
        pos = command.index('-filter_complex')+1
        command[pos] = command[pos].replace('precise_clock=1', 'precise_clock=0').replace('acquire_timeout=0', 'acquire_timeout=-1')
    if args.fifo:
        pos = command.index('-latest_frame')
        del command[pos:pos+2]
        command[command.index('-fps_mode')+1] = 'cfr'
    if args.synchronous:
        command[command.index('-async_encode')+1] = '0'
    reader, packetizer = AviPacketStream(), PcVideoPacketizer()
    sequence = itertools.count()
    records, interrupted = [], threading.Event()
    parse_error = None
    start = time.perf_counter()
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log,
            stdin=subprocess.PIPE, bufsize=0, creationflags=NO_WINDOW | ENCODER_PRIORITY)
        qos = configure_encoder_process(process)
        def finish():
            try:
                process.stdin.write(b'q\n')
                process.stdin.flush()
            except (OSError, ValueError):
                pass
        def abort():
            if process.poll() is None:
                interrupted.set()
                process.kill()
        stop = threading.Timer(args.seconds, finish)
        watchdog = threading.Timer(args.seconds+15, abort)
        stop.start(); watchdog.start()
        priority = False
        print(f'Sampling {args.resolution}/{args.fps} on {target["device"]}; video is discarded.', flush=True)
        try:
            while True:
                data = process.stdout.read(16384)
                if not data:
                    break
                arrived = time.perf_counter()
                for frame in reader.feed(data):
                    completed = time.perf_counter()
                    if not records:
                        priority = prioritize_gpu(process, STREAM_GPU_PRIORITY_CLASS)
                    wire_size, packet_ms = None, None
                    if args.packetize:
                        begin = time.perf_counter()
                        wire_size = sum(len(x) for x in packetizer.packetize(frame, lambda: next(sequence)&65535))
                        packet_ms = (time.perf_counter()-begin)*1000
                    records.append(dict(ms=(completed-start)*1000, read_ms=(arrived-start)*1000,
                                        encoded_bytes=len(frame), wire_bytes=wire_size, packetize_ms=packet_ms))
            process.wait(timeout=5)
            try:
                reader.finish()
            except ValueError as exc:
                parse_error = str(exc)
            log.seek(0)
            diagnostics = log.read().decode(errors='replace')
        finally:
            stop.cancel(); watchdog.cancel()
            if process.poll() is None:
                process.kill(); process.wait()
            process.stdout.close(); process.stdin.close()
    selected = [r for r in records if args.warmup*1000 <= r['ms'] <= args.seconds*1000]
    gaps = [b['ms']-a['ms'] for a,b in zip(selected,selected[1:])]
    span = (selected[-1]['ms']-selected[0]['ms'])/1000 if len(selected)>1 else 0
    # Complete, non-overlapping one-second host output windows. These are
    # encoded/serialized bytes, not USB completion or delivered image quality.
    windows = []
    for second in range(math.ceil(args.warmup), math.floor(args.seconds)):
        frames = [r for r in selected if second*1000 <= r['ms'] < (second+1)*1000]
        windows.append(dict(start_seconds=second, frames=len(frames),
            encoded_mbps=sum(r['encoded_bytes'] for r in frames)*8/1_000_000,
            serialized_mbps=(sum(r['wire_bytes'] for r in frames)*8/1_000_000
                             if args.packetize else None)))
    replacements = re.findall(r'(?:latest[^\n]*|replac[^\n]*)', diagnostics, re.I)
    result = dict(measurement='host access-unit arrival; not capture-to-photon latency',
        status='completed' if process.returncode == 0 and not interrupted.is_set() and gaps and not parse_error else 'failed',
        parse_error=parse_error,
        frame_budget_target_met=bool(records) and all(r['encoded_bytes']<=56000 for r in records),
        optical_latency_target='not measured',
        host_interval_one_percent_target_met=bool(gaps) and all(abs(x-1000/args.fps) <= 10/args.fps for x in gaps),
        encoded_bitrate_one_percent_target_met=bool(windows) and all(abs(w['encoded_mbps']-args.bitrate) <= args.bitrate*.01 for w in windows),
        screen_video_saved=False, usb_access=False, ffmpeg_sha256=hashlib.sha256(ffmpeg.read_bytes()).hexdigest(),
        source=target, command=command, qos=qos, gpu_priority=priority, returncode=process.returncode,
        warmup_seconds=args.warmup, requested_seconds=args.seconds, total_frames=len(records),
        measured_frames=len(selected), measured_fps=(len(selected)-1)/span if span else 0,
        interval_ms=distribution(gaps), intervals_over_1_5_period=sum(x > 1500/args.fps for x in gaps),
        intervals_within_one_percent=sum(abs(x-1000/args.fps) <= 10/args.fps for x in gaps),
        packetize_ms=distribution([r['packetize_ms'] for r in selected if r['packetize_ms'] is not None]),
        maximum_frame_bytes=max((r['encoded_bytes'] for r in records), default=0),
        oversize_frames=sum(r['encoded_bytes']>56000 for r in records),
        one_second_host_output=windows,
        raw_frame_log=replacements, diagnostics=diagnostics, frames=records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('frames','command','diagnostics','one_second_host_output')},ensure_ascii=False))
    return 0 if result['status']=='completed' and not result['oversize_frames'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
