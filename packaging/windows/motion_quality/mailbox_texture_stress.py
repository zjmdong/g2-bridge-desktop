"""Generated D3D11 VP -> latest raw mailbox -> NVENC identity stress.

No desktop capture, USB, software encoder, native patch or device configuration.
The deliberately slow AVI reader is test-only backpressure, NOT latency data.
Run --self-test for a small CPU-only check; GPU execution requires --run.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import zlib

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
from check_motion_quality import Pattern, planes_from_nv12, distribution, require, parse_trace
from goggles_bridge.avi import AviPacketStream
from goggles_bridge.annexb import is_idr

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
DROP_RE = re.compile(r'Latest-frame mailbox replaced (\d+) unencoded video frames')


class IdentityPattern:
    """Eight cached moving backgrounds, 17 independently salted ID+CRC regions.

    Background reuse makes the producer fast without a huge raw input file.
    Every submitted picture still has a unique 16-bit source ID in every region.
    Marker cells are part of the same BGRA texture as the moving background.
    This is an ownership stress pattern, not a realistic quality benchmark.
    """
    cell = 12
    def __init__(self, width=1920, height=1080, cache_frames=8):
        require(width >= 640 and height >= 360 and not width % 2 and not height % 2,
                'Even source dimensions >=640x360 required')
        self.width, self.height = width, height
        source = Pattern(width, height, scene='fast-pan', bootstrap=0, seed=53)
        self.cache_planes = [source.planes(i) for i in range(cache_frames)]
        self.cache_bgra = [source.bgra(i) for i in range(cache_frames)]
        self.rects = [(x, y) for y in (8, height//3, 2*height//3, height-56)
                      for x in (8, width-104)]
        self.rects += [(width*k//4-48, height*j//4-24)
                       for j in (1, 2, 3) for k in (1, 2, 3)]
        for a, (x, y) in enumerate(self.rects):
            require(0 <= x <= width-96 and 0 <= y <= height-48, 'Marker outside frame')
            for xx, yy in self.rects[:a]:
                require(x+96 <= xx or xx+96 <= x or y+48 <= yy or yy+48 <= y,
                        'Marker rectangles overlap')

    @staticmethod
    def word(index, region):
        coded = index ^ (region*997)
        crc = zlib.crc32(index.to_bytes(2, 'little')+bytes([region])) & 65535
        return coded | (crc << 16)

    def stamp(self, image, index, rgb=False):
        require(0 <= index < 65536, '16-bit source ID would wrap')
        for region, (left, top) in enumerate(self.rects):
            code = self.word(index, region)
            for bit in range(32):
                x, y = left+(bit % 8)*self.cell, top+(bit//8)*self.cell
                value = 224 if code & (1 << bit) else 24
                if rgb:
                    value = round((value-16)*255/219)
                    image[y:y+self.cell, x:x+self.cell, :3] = value
                else:
                    image[y:y+self.cell, x:x+self.cell] = value

    def bgra(self, index):
        picture = np.frombuffer(self.cache_bgra[index % len(self.cache_bgra)], np.uint8).reshape(
            self.height, self.width, 4).copy()
        self.stamp(picture, index, rgb=True)
        return picture.tobytes()

    def planes(self, index):
        y, u, v = (plane.copy() for plane in self.cache_planes[index % len(self.cache_planes)])
        self.stamp(y, index)
        for left, top in self.rects:
            # All rectangles have even alignment at the supported dimensions.
            u[top//2:(top+48)//2, left//2:(left+96)//2] = 128
            v[top//2:(top+48)//2, left//2:(left+96)//2] = 128
        return y, u, v

    def identity(self, y, margin=24):
        decoded = []
        for region, (left, top) in enumerate(self.rects):
            word, confidence = 0, 255.0
            for bit in range(32):
                x, yy = left+(bit % 8)*self.cell, top+(bit//8)*self.cell
                value = float(np.median(y[yy+4:yy+8, x+4:x+8]))
                confidence = min(confidence, abs(value-124))
                word |= int(value >= 124) << bit
            index = (word & 65535) ^ (region*997)
            crc_valid = word == self.word(index, region)
            decoded.append(dict(region=region, source_id=index, crc_valid=crc_valid,
                                margin=confidence, valid=crc_valid and confidence >= margin))
        valid_ids = {r['source_id'] for r in decoded if r['valid']}
        if len(valid_ids) > 1:
            status = 'confirmed_mixed'
        elif len(valid_ids) == 1 and all(r['valid'] for r in decoded):
            status = 'valid'
        else:
            status = 'inconclusive_marker'
        return dict(status=status, source_id=next(iter(valid_ids)) if len(valid_ids) == 1 else None,
                    minimum_margin=min(r['margin'] for r in decoded), regions=decoded)


def make_command(args):
    command = json.loads(args.template.read_text(encoding='utf-8'))
    command[0] = str(args.ffmpeg)
    require(command[-3:] == ['-f', 'avi', 'pipe:1'], 'Expected production AVI pipe output')
    require(command[command.index('-c:v')+1] == 'h264_nvenc', 'NVENC only')
    require(command[command.index('-latest_frame')+1] == '1', 'Latest mailbox must stay enabled')
    require(command[command.index('-async_encode')+1] == '1', 'Production async path required')
    require('-frames:v' not in command and '-i' not in command, 'Unexpected template inputs/limits')
    i = command.index('-filter_complex')+1
    capture, comma, filters = command[i].partition(',')
    require(comma and capture.startswith('ddagrab='), 'Expected direct DDA graph template')
    require('scale_d3d11=' in filters and 'format=nv12:desktop_sdr=1' in filters,
            'Production GPU conversion missing')
    command[i] = '[0:v]hwupload,' + filters
    i = command.index('-filter_complex')
    command[i:i] = ['-f', 'rawvideo', '-pixel_format', 'bgra', '-video_size', '1920x1080',
                    '-framerate', str(args.input_rate), '-i', 'pipe:0']
    command[command.index('-loglevel')+1] = 'info'
    require(not any('ddagrab=' in x or 'gfxcapture=' in x for x in command), 'Capture forbidden')
    require(command[command.index('-r')+1] == '100', 'Keep production 100 fps encoder timing')
    return command


def encode(args, pattern, command, report):
    errors, counters, packets = [], {'submitted': 0}, []
    log_path = args.output.with_suffix('.encoder.log')
    bitstream_path = args.output.with_suffix('.h264')
    deadline = time.monotonic()+args.timeout
    with log_path.open('wb') as log, bitstream_path.open('wb') as encoded:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=log, bufsize=0, creationflags=NO_WINDOW)
        def watchdog():
            while process.poll() is None:
                if time.monotonic() > deadline:
                    errors.append('Encoder exceeded bounded timeout')
                    process.kill()
                    return
                time.sleep(.1)
        def feed():
            started = time.monotonic()
            try:
                for index in range(args.frames):
                    raw = memoryview(pattern.bgra(index))
                    while raw:
                        n = process.stdin.write(raw)
                        require(n and n > 0, 'Input pipe stopped accepting pixels')
                        raw = raw[n:]
                    counters['submitted'] += 1
            except BaseException as exc:
                errors.append('Producer: '+repr(exc))
            finally:
                process.stdin.close()
                counters['producer_seconds'] = time.monotonic()-started
        watcher = threading.Thread(target=watchdog, daemon=True)
        feeder = threading.Thread(target=feed, daemon=True)
        started = time.monotonic()
        watcher.start()
        feeder.start()
        parser = AviPacketStream()
        try:
            while True:
                block = process.stdout.read(args.read_chunk)
                if not block:
                    break
                for frame in parser.feed(block):
                    packets.append({'bytes': len(frame), 'idr': is_idr(frame)})
                    encoded.write(frame)
                # Explicit test backpressure; it never enters production code.
                if args.reader_sleep_ms:
                    time.sleep(args.reader_sleep_ms/1000)
            parser.finish()
        except BaseException as exc:
            errors.append('AVI reader: '+repr(exc))
            process.kill()
        finally:
            process.stdout.close()
            if process.poll() is None:
                try:
                    process.wait(timeout=max(.1, deadline-time.monotonic()))
                except subprocess.TimeoutExpired:
                    process.kill()
                    errors.append('Encoder failed to drain')
            process.wait()
            feeder.join(timeout=5)
            watcher.join(timeout=1)
        elapsed = time.monotonic()-started
    text = log_path.read_text(errors='replace')
    replacements = DROP_RE.findall(text)
    report['encode'] = dict(counters, returncode=process.returncode, errors=errors,
        elapsed_seconds=elapsed, submitted_wall_fps=counters['submitted']/max(elapsed, .001),
        access_units=len(packets), packet_bytes=distribution(p['bytes'] for p in packets),
        idr_indices=[i for i, p in enumerate(packets) if p['idr']],
        mailbox_replaced=int(replacements[0]) if len(replacements) == 1 else None,
        mailbox_summary_count=len(replacements), slow_reader_ms=args.reader_sleep_ms,
        read_chunk=args.read_chunk, log=str(log_path), bitstream=str(bitstream_path))
    require(not feeder.is_alive(), 'Input producer did not terminate')
    require(not errors and process.returncode == 0, 'Encode/AVI failure; inspect encoder log')
    require(counters['submitted'] == args.frames, 'Not all input frames were submitted')
    require(len(replacements) == 1, 'Exactly one native mailbox summary required')
    require(packets and packets[0]['idr'], 'Reference chain must start with IDR')
    return bitstream_path, len(packets)


def decode(args, pattern, path, access_units, report):
    command = [str(args.ffmpeg), '-hide_banner', '-nostdin', '-v', 'error', '-xerror',
        '-err_detect', 'explode', '-i', str(path), '-map', '0:v:0', '-an',
        '-fps_mode', 'passthrough', '-pix_fmt', 'nv12', '-c:v', 'rawvideo',
        '-f', 'rawvideo', 'pipe:1']
    # H.264 software decoding is deliberate validation. Encoding above is NVENC only.
    log_path = args.output.with_suffix('.decoder.log')
    rows, previous = [], None
    with log_path.open('wb') as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log,
            stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        deadline = time.monotonic()+args.timeout
        stop = threading.Event()
        def watchdog():
            while not stop.wait(.1):
                if process.poll() is not None:
                    return
                if time.monotonic() > deadline:
                    process.kill()
                    return
        watcher = threading.Thread(target=watchdog, daemon=True)
        watcher.start()
        try:
            size = pattern.width*pattern.height*3//2
            while True:
                raw = bytearray()
                while len(raw) < size:
                    chunk = process.stdout.read(size-len(raw))
                    if not chunk:
                        break
                    raw.extend(chunk)
                if not raw:
                    break
                require(len(raw) == size, 'Truncated decoded picture')
                planes = planes_from_nv12(raw, pattern.width, pattern.height)
                identity = pattern.identity(planes[0])
                row = dict(output_index=len(rows), **identity)
                index = identity['source_id']
                if identity['status'] == 'valid':
                    require(index < args.frames, 'Decoded source ID was never generated')
                    row['order_valid'] = previous is None or index > previous
                    previous = index
                    expected = pattern.planes(index)
                    # Full-plane truth metrics, not thresholds for diagnosing races.
                    row['truth'] = {}
                    for name, actual, reference in zip(('y', 'u', 'v'), planes, expected):
                        error = actual.astype(np.float32)-reference.astype(np.float32)
                        row['truth'][name+'_mse'] = float(np.square(error).mean(dtype=np.float64))
                        row['truth'][name+'_mae'] = float(np.abs(error).mean(dtype=np.float64))
                rows.append(row)
        finally:
            if process.poll() is None and time.monotonic() > deadline:
                process.kill()
            process.stdout.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            finally:
                stop.set()
                watcher.join(timeout=1)
    report['decode'] = dict(command=command, returncode=process.returncode,
        stderr=log_path.read_text(errors='replace'), frames=len(rows), rows=rows,
        confirmed_mixed=sum(r['status'] == 'confirmed_mixed' for r in rows),
        inconclusive=sum(r['status'] == 'inconclusive_marker' for r in rows),
        duplicate_or_reverse=sum(r.get('order_valid') is False for r in rows),
        minimum_marker_margin=min((r['minimum_margin'] for r in rows), default=None))
    require(process.returncode == 0 and not report['decode']['stderr'].strip(),
            'Strict H.264 decoder reported an error')
    require(len(rows) == access_units, 'AVI access-unit count differs from decoded-picture count')
    valid_ids = [r['source_id'] for r in rows if r['status'] == 'valid']
    report['decode']['source_ids'] = valid_ids
    report['decode']['truth_y_mse'] = distribution(r['truth']['y_mse'] for r in rows if 'truth' in r)
    require(not report['decode']['confirmed_mixed'], 'Different CRC-valid region IDs: confirmed mixed frame')
    require(not report['decode']['duplicate_or_reverse'], 'Unexpected duplicate/reversed decoded ID')
    require(not report['decode']['inconclusive'], 'Marker damage: identity result inconclusive')
    require(valid_ids and valid_ids[-1] == args.frames-1, 'Final submitted frame was not drained')
    drops = report['encode']['mailbox_replaced']
    require(args.frames-len(rows) == drops, 'Lost source IDs do not reconcile with native mailbox replacements')
    require(drops >= args.min_replacements, 'Mailbox replacements below stress coverage requirement')
    require(len(rows) >= args.min_decoded, 'Too few encoded pictures for ownership coverage')


def reference_chain(args, path, access_units, report):
    """Parse complete H.264 syntax after encoding; no GPU or live-path logging."""
    command = [str(args.ffmpeg), '-hide_banner', '-nostdin', '-v', 'verbose',
        '-f', 'h264', '-i', str(path), '-map', '0:v:0', '-c:v', 'copy',
        '-bsf:v', 'trace_headers', '-f', 'null', '-']
    log_path = args.output.with_suffix('.trace.log')
    with log_path.open('wb') as log:
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=log,
            stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=args.timeout)
    require(result.returncode == 0, 'H.264 syntax tracing failed')
    require(log_path.stat().st_size <= 40*1024*1024, 'Header trace exceeded bounded size')
    trace = parse_trace(log_path.read_text(errors='replace'))
    report['reference_chain'] = dict(trace, returncode=result.returncode, log=str(log_path))
    require(len(trace['pictures']) == access_units, 'Trace picture count differs from AVI AU count')
    require(not trace['frame_num_errors'], 'Reference-picture frame_num discontinuity')
    require(trace['pictures'] and trace['pictures'][0].get('nal_unit_type') == 5,
            'Complete H.264 sequence does not begin with an IDR picture')


def self_test():
    p = IdentityPattern(640, 360, 2)
    for index in (0, 1, 127, 255, 1024, 65535):
        y, u, v = p.planes(index)
        found = p.identity(y)
        require(found['status'] == 'valid' and found['source_id'] == index, 'ID+CRC round-trip failed')
        rgb = np.frombuffer(p.bgra(index), np.uint8).reshape(360, 640, 4)
        # Neutral RGB marker readback converted to canonical limited luminance.
        neutral = np.rint(rgb[:, :, 0].astype(np.float32)*(219/255)+16).astype(np.uint8)
        require(p.identity(neutral)['status'] == 'valid', 'BGRA marker generation failed')
    y = p.planes(41)[0]
    other = p.planes(42)[0]
    x, top = p.rects[10]
    y[top:top+48, x:x+96] = other[top:top+48, x:x+96]
    require(p.identity(y)['status'] == 'confirmed_mixed', 'Mixed-region detector did not fire')
    y = p.planes(41)[0]
    x, top = p.rects[0]
    y[top:top+48, x:x+96] = 124
    require(p.identity(y)['status'] == 'inconclusive_marker', 'Uncertain marker mislabeled as corruption')
    y = p.planes(41)[0]
    y[top+4:top+8, x+4:x+8] = 224 if y[top+4, x+4] == 24 else 24
    require(p.identity(y)['status'] == 'inconclusive_marker', 'CRC-damaged marker mislabeled as mixed')
    y = p.planes(41)[0]
    y = np.clip(y.astype(np.int16)+16, 0, 255).astype(np.uint8)
    require(p.identity(y)['status'] == 'valid', 'Moderate quantization error rejected valid IDs')
    print('PASS: CPU-only 17-region ID/CRC, BGRA markers, mixed frame, ambiguity and damaged-CRC checks')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--self-test', action='store_true')
    mode.add_argument('--run', action='store_true')
    parser.add_argument('--ffmpeg', type=Path, default=ROOT/'vendor/ffmpeg/ffmpeg.exe')
    parser.add_argument('--template', type=Path, default=HERE/'baseline-command-v024.json')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--frames', type=int, default=1000)
    parser.add_argument('--input-rate', type=int, default=400)
    parser.add_argument('--reader-sleep-ms', type=float, default=4)
    parser.add_argument('--read-chunk', type=int, default=4096)
    parser.add_argument('--min-replacements', type=int, default=100)
    parser.add_argument('--min-decoded', type=int, default=30)
    parser.add_argument('--timeout', type=float, default=120)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.output is None:
        parser.error('--output is required with --run')
    require(1 <= args.frames <= 4096, 'Bounded run needs 1..4096 unique 16-bit input IDs')
    require(100 < args.input_rate <= 1000, 'Nominal producer rate must exceed 100 fps')
    require(0 <= args.reader_sleep_ms <= 25 and 512 <= args.read_chunk <= 65536, 'Unsafe pressure parameters')
    require(1 <= args.min_replacements < args.frames and 1 <= args.min_decoded < args.frames,
            'Invalid coverage thresholds')
    require(1 <= args.timeout <= 300, 'Timeout must be bounded to 1..300 seconds')
    args.output = args.output.resolve()
    require(args.output.suffix.lower() == '.json', 'Output report must have a .json suffix')
    require(not any(args.output.with_suffix(s).exists() for s in ('.json', '.h264', '.encoder.log', '.decoder.log', '.trace.log')),
            'Choose a new output basename; existing evidence is never overwritten')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.ffmpeg = args.ffmpeg.resolve(strict=True)
    report = dict(status='running', screen_capture=False, usb=False, software_encoding=False,
        source='Eight cached deterministic moving backgrounds plus 17 independent source-ID/CRC regions',
        scope='D3D11 upload/conversion/pool/latest/NVENC stress; does not exercise DDA or measure normal latency',
        caution='Identity probes cover their regions; PSNR/MSE are evidence, not proof of mixed surface ownership.',
        ffmpeg=str(args.ffmpeg), ffmpeg_sha256=hashlib.sha256(args.ffmpeg.read_bytes()).hexdigest(),
        template_sha256=hashlib.sha256(args.template.read_bytes()).hexdigest(),
        frames_requested=args.frames, nominal_source_rate=args.input_rate)
    code = 0
    try:
        command = make_command(args)
        report['command'] = command
        prepared = time.monotonic()
        pattern = IdentityPattern()
        report['source_cache_prepare_seconds'] = time.monotonic()-prepared
        path, access_units = encode(args, pattern, command, report)
        decode(args, pattern, path, access_units, report)
        reference_chain(args, path, access_units, report)
        report['status'] = 'passed'
    except BaseException as exc:
        report['status'] = 'failed_or_inconclusive'
        report['error'] = repr(exc)
        code = 1
    finally:
        args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('status', 'error') if k in report}))
    raise SystemExit(code)


if __name__ == '__main__':
    main()
