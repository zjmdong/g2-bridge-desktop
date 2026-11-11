"""Check generated SDR pictures through the production GPU/NVENC pipeline.

Requires Windows, an NVIDIA GPU and the patched FFmpeg. Never opens a desktop
capture source or USB device. Temporary pictures contain generated colours and
frame IDs only, and are removed on exit. The JSON report contains measurements,
not pictures. This is a pixel/order/bitstream regression, not a latency test.

The production latest-frame mailbox is deliberately disabled: a fast offline
producer must preserve all 48 IDs for this test, unlike live capture admission.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from desktop_app.video import compatible_command
from goggles_bridge.annexb import is_idr
from goggles_bridge.avi import AviPacketStream
from goggles_bridge.engine import BridgeSettings, encoder_command, MAX_FRAME_BYTES, NO_WINDOW

COLOURS = [(g, g, g) for g in (0, 8, 16, 32, 64, 128, 192, 255)] + [
    (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
    (0, 255, 255), (255, 0, 255), (52, 97, 171), (199, 32, 57)]
FRAME_COUNT = 48
RAW_TOLERANCE = 2
ENCODED_TOLERANCE = 4  # At most four 8-bit code values, including conversion.
SOURCES = ((128, 72), (344, 144), (108, 192))
TARGETS = ((1280, 720), (1920, 1080))
NAL_START = re.compile(rb'\x00\x00(?:\x00)?\x01')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def fit_rect(source, target):
    """The public even-aligned aspect-fit contract of desktop_sdr, not stretch."""
    sw, sh = source
    tw, th = target
    w, h = tw, th
    if sw * h > sh * w:
        h = (sh * w // sw) & ~1
    else:
        w = (sw * h // sh) & ~1
    return ((tw - w) // 2 & ~1, (th - h) // 2 & ~1, w, h)


def id_rect(source, bit):
    sw, sh = source
    start, length = sw // 10, sw * 8 // 10
    return (start + length * bit // 6, sh * 3 // 4,
            start + length * (bit + 1) // 6, sh * 15 // 16)


def write_input(path, source):
    sw, sh = source
    with path.open('wb') as stream:
        for index in range(FRAME_COUNT):
            r, g, b = COLOURS[index % len(COLOURS)]
            picture = bytearray(bytes((b, g, r, 255)) * (sw * sh))
            for bit in range(6):
                x0, y0, x1, y1 = id_rect(source, bit)
                value = 255 if index & (1 << bit) else 0
                row = bytes((value, value, value, 255)) * (x1 - x0)
                for y in range(y0, y1):
                    picture[(y * sw + x0) * 4:(y * sw + x1) * 4] = row
            stream.write(picture)


def cpu_conversion(source, target):
    x, y, w, h = fit_rect(source, target)
    tw, th = target
    return (f'scale={w}:{h}:flags=bilinear:in_range=pc:'
            'out_color_matrix=bt709:out_range=tv,format=nv12,'
            f'pad={tw}:{th}:{x}:{y}:color=black')


def remove_option(command, option):
    removed = []
    while option in command:
        pos = command.index(option)
        require(pos + 1 < len(command), f'Missing value after {option}')
        removed.append(command[pos + 1])
        del command[pos:pos + 2]
    return removed


def offline_command(ffmpeg, source, target, input_path, adapter):
    """Replace only capture/admission, preserving production NVENC/AVI options."""
    settings = BridgeSettings(dll=Path('unused.dll'), ffmpeg=ffmpeg,
                              capture='ddagrab', capture_fps=100, fps=100,
                              bitrate_mbps=20, preset='p4')
    command = compatible_command(encoder_command(settings), dimensions=target,
                                 output=dict(adapter=adapter, output=0, vendor_id=0x10de,
                                             width=source[0], height=source[1]))
    original = list(command)
    latest = remove_option(command, '-latest_frame')
    require('-frames:v' not in command, 'Unexpected production output-frame limit')
    require('-i' not in command, 'Production source is no longer a direct graph')
    pos = command.index('-filter_complex') + 1
    capture, separator, filters = command[pos].partition(',')
    require(separator and capture.startswith('ddagrab='), 'Expected production DDA source')
    scalers = re.findall(r'scale_d3d11=[^,;\[]+', filters)
    formats = [re.search(r'(?:^|:)format=([^:]+)', scaler) for scaler in scalers]
    require(filters.endswith('[desktop]') and all(formats) and
            [match.group(1) for match in formats] in (['nv12'], ['bgra', 'nv12']),
            'Expected one NV12 conversion, optionally preceded by BGRA upscaling')
    require(command[command.index('-c:v') + 1] == 'h264_nvenc', 'NVENC is required')
    require(command[-3:] == ['-f', 'avi', 'pipe:1'], 'Expected production AVI framing')
    command[pos] = '[0:v]hwupload,' + filters
    # Latest admission permits passthrough timestamps. Offline verification must
    # consume every input ID, including with stock FFmpeg r/passthrough checks.
    if '-fps_mode' in command:
        command[command.index('-fps_mode') + 1] = 'cfr'
    else:
        command[-3:-3] = ['-fps_mode', 'cfr']
    sw, sh = source
    pos = command.index('-filter_complex')
    command[pos:pos] = ['-f', 'rawvideo', '-pixel_format', 'bgra',
                        '-video_size', f'{sw}x{sh}', '-framerate', '100',
                        '-i', str(input_path)]
    command[-3:-3] = ['-frames:v', str(FRAME_COUNT)]
    require(not any('ddagrab=' in arg or 'gfxcapture=' in arg for arg in command),
            'Refusing to run a desktop capture command')
    return command, filters.removesuffix('[desktop]'), dict(
        latest_frame_removed=latest, fps_mode='cfr', gpu_scaler_passes=len(scalers),
        reason='Preserve every generated ID; live frame admission is not tested',
        production_encoder_options=original[original.index('-c:v'):])


def raw_command(ffmpeg, source, input_path, filters, adapter=None):
    command = [str(ffmpeg), '-hide_banner', '-nostdin', '-v', 'error']
    if adapter is not None:
        command += ['-init_hw_device', f'd3d11va=cap:{adapter}', '-filter_hw_device', 'cap']
    command += ['-f', 'rawvideo', '-pixel_format', 'bgra', '-video_size',
                f'{source[0]}x{source[1]}', '-framerate', '100', '-i', str(input_path),
                '-vf', filters, '-r', '100', '-fps_mode', 'cfr',
                '-frames:v', str(FRAME_COUNT),
                '-c:v', 'rawvideo', '-pix_fmt', 'nv12', '-f', 'rawvideo', 'pipe:1']
    return command


def read_exact(stream, count):
    chunks, remaining = [], count
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def run_nv12(command, target, inspect, timeout=90):
    """Read one NV12 frame at a time; never accumulate 48 full-size pictures."""
    size = target[0] * target[1] * 3 // 2
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=errors, creationflags=NO_WINDOW)
        expired = threading.Event()

        def deadline():
            expired.set()
            try:
                process.kill()
            except OSError:
                pass

        timer = threading.Timer(timeout, deadline)
        timer.daemon = True
        timer.start()
        count = 0
        try:
            while True:
                frame = read_exact(process.stdout, size)
                if not frame:
                    break
                require(len(frame) == size, f'Partial NV12 frame {count}: {len(frame)}/{size}')
                require(count < FRAME_COUNT, 'Unexpected duplicated/extra output frame')
                inspect(count, frame)
                count += 1
            process.wait(timeout=5)
            errors.seek(0)
            stderr = errors.read().decode(errors='replace')
            require(not expired.is_set(), f'FFmpeg timed out after {timeout}s: {stderr}')
            require(process.returncode == 0, f'FFmpeg exited {process.returncode}: {stderr}')
            require(not stderr.strip(), f'FFmpeg reported decode/conversion errors: {stderr}')
            require(count == FRAME_COUNT, f'Expected {FRAME_COUNT} frames, received {count}')
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
    return count


def sample_yuv(frame, target, x, y):
    width, height = target
    uv = width * height + (y // 2) * width + (x & ~1)
    return [frame[y * width + x], frame[uv], frame[uv + 1]]


def bars(source, target):
    x, y, w, h = fit_rect(source, target)
    tw, th = target
    return [(0, 0, tw, y), (0, y + h, tw, th),
            (0, y, x, y + h), (x + w, y, tw, y + h)]


def black_error(frame, source, target, margin):
    """Check every pixel in black bars (lossy checks omit an 8-pixel boundary)."""
    width, height = target
    maximum, components = 0, 0
    for x0, y0, x1, y1 in bars(source, target):
        x0, y0, x1, y1 = x0 + margin, y0 + margin, x1 - margin, y1 - margin
        if x1 <= x0 or y1 <= y0:
            continue
        for y in range(y0, y1):
            values = frame[y * width + x0:y * width + x1]
            maximum = max(maximum, abs(min(values) - 16), abs(max(values) - 16))
            components += len(values)
        for y in range(y0 // 2, y1 // 2):
            values = frame[width * height + y * width + x0:width * height + y * width + x1]
            maximum = max(maximum, abs(min(values) - 128), abs(max(values) - 128))
            components += len(values)
    return maximum, components


def inspect_frames(command, source, target, reference=None, encoded=False, colour_gate=True):
    x, y, w, h = fit_rect(source, target)
    tolerance = ENCODED_TOLERANCE if encoded else RAW_TOLERANCE
    samples, ids = [], []
    maximum_error = maximum_spread = maximum_neutral_error = maximum_black_error = 0
    black_components = 0
    worst_component = None
    colour_violations = []

    def check_colour(condition, message):
        if not condition:
            colour_violations.append(message)
            if colour_gate:
                raise RuntimeError(message)

    def inspect(index, frame):
        nonlocal maximum_error, maximum_spread, maximum_neutral_error
        nonlocal maximum_black_error, black_components, worst_component
        # Well inside the uniform field, away from resampled edges and ID cells.
        interior = [sample_yuv(frame, target, x + int(w * fx), y + int(h * fy))
                    for fy in (.12, .30, .48, .60) for fx in (.15, .50, .85)]
        # Include pure-colour content boundaries: an apparently correct black
        # bar can hide chroma contamination in the adjacent one/two pixel rows.
        # Each GPU sample is compared to the CPU sample at the same location.
        edge_positions = [(x + int(w * fx), yy) for fx in (.15, .50, .85)
                          for yy in (y, y + 1, y + h - 2, y + h - 1)]
        edge_positions += [(xx, y + int(h * fy)) for fy in (.12, .30, .48)
                           for xx in (x, x + 1, x + w - 2, x + w - 1)]
        points = interior + [sample_yuv(frame, target, xx, yy) for xx, yy in edge_positions]
        spreads = [max(p[c] for p in interior) - min(p[c] for p in interior) for c in range(3)]
        maximum_spread = max(maximum_spread, *spreads)
        check_colour(max(spreads) <= (4 if encoded else 1),
                     f'Frame {index}: nonuniform colour field {spreads}')
        if index % len(COLOURS) < 8:
            neutral = max(abs(p[c] - 128) for p in points for c in (1, 2))
            maximum_neutral_error = max(maximum_neutral_error, neutral)
            check_colour(neutral <= (3 if encoded else 2), f'Frame {index}: nonneutral gray {points}')
        decoded_id = 0
        for bit in range(6):
            x0, y0, x1, y1 = id_rect(source, bit)
            px = x + int((x0 + x1) * w / (2 * source[0]))
            py = y + int((y0 + y1) * h / (2 * source[1]))
            actual = sample_yuv(frame, target, px, py)
            expected = [235 if index & (1 << bit) else 16, 128, 128]
            require(max(abs(a - b) for a, b in zip(actual, expected)) <= tolerance,
                    f'Frame {index}, ID bit {bit}: expected {expected}, received {actual}')
            decoded_id |= (actual[0] > 128) << bit
        require(decoded_id == index, f'Frame order changed: expected {index}, received {decoded_id}')
        ids.append(decoded_id)
        error, components = black_error(frame, source, target, 8 if encoded else 0)
        maximum_black_error = max(maximum_black_error, error)
        black_components += components
        check_colour(error <= (ENCODED_TOLERANCE if encoded else 0),
                     f'Frame {index}: black bars differ from Y=16, U=V=128 by {error}')
        if reference is not None:
            error, point_index, component = max(
                (abs(p[c] - q[c]), pi, c)
                for pi, (p, q) in enumerate(zip(points, reference[index])) for c in range(3))
            if error > maximum_error:
                maximum_error = error
                worst_component = dict(frame=index, sample=point_index, component='YUV'[component],
                                       expected=reference[index][point_index][component],
                                       actual=points[point_index][component])
            check_colour(error <= tolerance,
                         f'Frame {index}, sample {point_index}: component error {error} exceeds {tolerance}; '
                         f'expected {reference[index][point_index]}, received {points[point_index]}')
        samples.append(points)

    count = run_nv12(command, target, inspect)
    reuse_error = max(abs(a - b) for index in range(16, FRAME_COUNT)
                      for p, q in zip(samples[index], samples[index % 16]) for a, b in zip(p, q))
    check_colour(reuse_error <= (ENCODED_TOLERANCE if encoded else 0),
                 f'Repeated colour changed after texture reuse: {reuse_error}')
    return samples, dict(frames=count, frame_ids=ids, maximum_component_error=maximum_error,
                        worst_component=worst_component,
                        colour_thresholds_enforced=colour_gate,
                        colour_threshold_violations=colour_violations,
                        compared_with_cpu_reference=reference is not None,
                        maximum_uniform_field_spread=maximum_spread,
                        maximum_gray_chroma_error=maximum_neutral_error,
                        maximum_black_bar_error=maximum_black_error,
                        checked_black_bar_components=black_components,
                        colour_sample_positions_per_frame=len(samples[0]),
                        content_edges_checked=True,
                        repeated_colour_error=reuse_error,
                        colour_yuv_samples=[points[0] for points in samples[:16]])


def encode(command, path):
    result = subprocess.run(command, capture_output=True, timeout=90, creationflags=NO_WINDOW)
    stderr = result.stderr.decode(errors='replace')
    require(result.returncode == 0, f'NVENC failed ({result.returncode}): {stderr}')
    reader = AviPacketStream()
    frames = reader.feed(result.stdout)
    reader.finish()
    require(len(frames) == FRAME_COUNT, f'NVENC produced {len(frames)} access units')
    largest = max(map(len, frames))
    require(largest <= MAX_FRAME_BYTES, f'Access unit {largest} exceeds {MAX_FRAME_BYTES}-byte SDK guard')
    headers = {kind: set() for kind in (7, 8)}
    for frame in frames:
        for nal in NAL_START.split(frame):
            if nal and nal[0] & 31 in headers:
                headers[nal[0] & 31].add(nal)
    require(all(len(values) == 1 for values in headers.values()), 'Missing/changing SPS or PPS')
    require(is_idr(frames[0]), 'Stream does not begin with an IDR')
    require(next(iter(headers[7]))[1] == 100, 'Expected production 8-bit H.264 High SPS')
    with path.open('wb') as stream:
        for frame in frames:
            stream.write(frame)
    return headers, dict(frames=len(frames), maximum_access_unit_bytes=largest,
                         oversized_access_units=0,
                         idr_frames=[i for i, frame in enumerate(frames) if is_idr(frame)],
                         sps_hex=next(iter(headers[7])).hex(),
                         pps_hex=next(iter(headers[8])).hex(), encoder_stderr=stderr)


def decoder_command(ffmpeg, input_path):
    return [str(ffmpeg), '-hide_banner', '-nostdin', '-v', 'error', '-xerror',
            '-f', 'h264', '-i', str(input_path), '-an', '-c:v', 'rawvideo',
            '-pix_fmt', 'nv12', '-fps_mode', 'passthrough', '-f', 'rawvideo', 'pipe:1']


def check_case(ffmpeg, source, target, folder, adapter, result):
    input_path = folder / 'generated.bgra'
    write_input(input_path, source)
    production, filters, admission = offline_command(ffmpeg, source, target, input_path, adapter)
    result['offline_admission'] = admission
    cpu_filters = cpu_conversion(source, target)
    result['gpu_filters'] = filters
    result['cpu_filters'] = cpu_filters
    cpu_samples, result['cpu_raw'] = inspect_frames(
        raw_command(ffmpeg, source, input_path, cpu_filters), source, target)
    _, result['gpu_raw'] = inspect_frames(raw_command(
        ffmpeg, source, input_path, 'hwupload,' + filters + ',hwdownload,format=nv12', adapter),
        source, target, cpu_samples)
    gpu_path, cpu_path = folder / 'gpu.h264', folder / 'cpu.h264'
    gpu_headers, result['gpu_encoded'] = encode(production, gpu_path)
    _, result['gpu_decoded'] = inspect_frames(decoder_command(ffmpeg, gpu_path),
                                               source, target, cpu_samples, encoded=True)
    # Preserve the production encoder options while replacing only its colour
    # conversion. This is still NVIDIA hardware encoding, with CPU NV12 input.
    cpu_command = list(production)
    remove_option(cpu_command, '-init_hw_device')
    remove_option(cpu_command, '-filter_hw_device')
    graph_index = cpu_command.index('-filter_complex') + 1
    graph = cpu_command[graph_index].replace('[0:v]hwupload,', '[0:v]', 1)
    # The GPU may enlarge RGB separately to avoid this driver's chroma-border
    # bug. CPU swscale does one aspect-fit conversion directly from the source.
    scalers = re.findall(r'scale_d3d11=[^,;\[]+', graph)
    for intermediate in scalers[:-1]:
        require(':format=bgra:' in intermediate, 'Unexpected intermediate GPU format')
        graph = graph.replace(intermediate + ',', '', 1)
    graph, replacements = re.subn(r'scale_d3d11=[^,;\[]+', cpu_filters, graph)
    require(replacements == 1, 'Could not substitute the production colour conversion')
    cpu_command[graph_index] = graph
    cpu_headers, result['cpu_encoded'] = encode(cpu_command, cpu_path)
    require(gpu_headers == cpu_headers, 'GPU conversion changed firmware-compatible SPS/PPS')
    # The previous CPU-conversion path is a bitstream/order compatibility
    # baseline, not the new pixel-quality gate. Its lossy edge errors are still
    # measured and reported; all CPU IDs and decoder errors remain fatal.
    _, result['cpu_decoded'] = inspect_frames(decoder_command(ffmpeg, cpu_path),
                                               source, target, cpu_samples, encoded=True,
                                               colour_gate=False)
    result['cpu_decoded']['role'] = 'Non-gating previous CPU-path colour baseline; frame order and decoding are gated'
    result['sps_pps_match_cpu_path'] = True
    result['status'] = 'passed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', type=Path, default=ROOT / 'vendor/ffmpeg/ffmpeg.exe')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--adapter', type=int, default=0, help='NVIDIA DXGI adapter index (default: 0)')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new report path; existing evidence is not overwritten')
    if args.adapter < 0:
        parser.error('--adapter must be nonnegative')
    ffmpeg = args.ffmpeg.resolve(strict=True)
    with ffmpeg.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    report = dict(status='running', measurement='Generated pixel, frame-order and H.264 compatibility checks; '
                  'not optical latency, live pacing or goggles-display validation',
                  ffmpeg=str(ffmpeg), ffmpeg_sha256=digest, adapter=args.adapter,
                  screen_capture=False, usb_access=False, frames_per_case=FRAME_COUNT,
                  source_rgb=COLOURS, raw_component_tolerance=RAW_TOLERANCE,
                  decoded_component_tolerance=ENCODED_TOLERANCE, cases=[])
    started = time.monotonic()
    code = 0
    try:
        with tempfile.TemporaryDirectory(prefix='goggles-generated-gpu-') as temporary:
            for source in SOURCES:
                for target in TARGETS:
                    case = dict(source=list(source), target=list(target),
                                aspect_fit_rect=list(fit_rect(source, target)), status='running')
                    report['cases'].append(case)
                    print(f'Checking generated {source[0]}x{source[1]} -> {target[0]}x{target[1]}', flush=True)
                    check_case(ffmpeg, source, target, Path(temporary), args.adapter, case)
        report['status'] = 'passed'
    except (Exception, KeyboardInterrupt) as error:
        report['status'] = 'failed'
        report['error'] = f'{type(error).__name__}: {error}'
        if report['cases'] and report['cases'][-1]['status'] == 'running':
            report['cases'][-1]['status'] = 'failed'
        code = 130 if isinstance(error, KeyboardInterrupt) else 1
        print(report['error'], file=sys.stderr)
    finally:
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        report['validation_frame_counts'] = {
            stage: sum(case.get(stage, {}).get('frames', 0) for case in report['cases'])
            for stage in ('cpu_raw', 'gpu_raw', 'cpu_encoded', 'gpu_encoded', 'cpu_decoded', 'gpu_decoded')}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')
    print(f"{report['status'].upper()}: {args.output}")
    return code


if __name__ == '__main__':
    raise SystemExit(main())
