"""Check capture-frame selection with in-memory IDs, without screen capture or USB.

Runs the production command's selection prefix against synthetic raw frames.
These are frame freshness/cadence checks, not an optical latency measurement.
"""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from desktop_app.video import compatible_command, frame_selection
from goggles_bridge.engine import BridgeSettings, encoder_command, NO_WINDOW
from goggles_bridge.annexb import is_idr
from goggles_bridge.avi import AviPacketStream


def production_selection(ffmpeg, fps):
    """Read the real DDA graph; changing display identity must not add buffering."""
    expected = frame_selection(fps)
    for output in (dict(adapter=0, output=0), dict(adapter=0, output=1)):
        for dimensions in ((1280, 720), (1920, 1080)):
            settings = BridgeSettings(dll=Path('unused.dll'), ffmpeg=ffmpeg,
                                      capture='ddagrab', fps=fps, bitrate_mbps=20)
            command = compatible_command(encoder_command(settings), output=output,
                                         dimensions=dimensions)
            assert '-i' not in command and '-vf' not in command
            graph = command[command.index('-filter_complex')+1]
            source, separator, filters = graph.partition(',')
            assert separator and source.startswith('ddagrab=')
            assert filters.endswith('[desktop]')
            assert command[command.index('-map')+1] == '[desktop]'
            filters = filters.removesuffix('[desktop]')
            prefix, separator, _ = filters.partition(',hwdownload')
            assert separator and prefix == expected, (fps, output, dimensions, filters)
            assert '-x264-params' not in command
            assert command[command.index('-c:v')+1] == 'h264_nvenc'
    return prefix


def select_ids(ffmpeg, raw, source_fps, fps, gap_ms, jitter_us, selection):
    graph = (f"settb=1/1000000,setpts='PTS+if(gte(N,300),{gap_ms}*1000,0)"
             f"+if(gt(N,0),(2*mod(N,2)-1)*{jitter_us},0)'," + selection)
    command = [str(ffmpeg), '-v', 'error', '-nostdin', '-f', 'rawvideo',
               '-pixel_format', 'gray', '-video_size', '16x16',
               '-framerate', str(source_fps), '-i', 'pipe:0', '-vf', graph,
               '-r', str(fps), '-fps_mode', 'cfr', '-f', 'rawvideo', 'pipe:1']
    result = subprocess.run(command, input=raw, capture_output=True, check=True,
                            timeout=15, creationflags=NO_WINDOW)
    assert len(result.stdout) % 256 == 0, 'Partial raw output frame'
    ids = [sum((value > 128) << bit for bit, value in enumerate(result.stdout[i:i+16]))
           for i in range(0, len(result.stdout), 256)]
    return ids


def check_synthetic_encoder(ffmpeg):
    """Verify direct-graph NVENC/AVI with generated pictures, never desktop input."""
    settings = BridgeSettings(dll=Path('unused.dll'), ffmpeg=ffmpeg,
                              capture='ddagrab', fps=100, bitrate_mbps=20, preset='p4')
    production = compatible_command(encoder_command(settings))
    graph_index = production.index('-filter_complex')+1
    _, _, filters = production[graph_index].partition(',')
    filters = filters.removesuffix('[desktop]')
    assert filters.count('hwdownload,format=bgra') == 1
    # testsrc2 supplies CPU frames; preserve the real selection, scale, NVENC
    # settings, framing, and output options. No DDA/WGC or USB is opened.
    filters = filters.replace('hwdownload,format=bgra', 'format=bgra', 1)
    # Pin the generated format: in a direct graph testsrc2 can negotiate BGRA,
    # whereas the separate lavfi input defaults to YUV420P before the -vf graph.
    source = 'testsrc2=size=1920x1080:rate=240,format=yuv420p'
    results, unencoded = [], {}
    for mode in ('direct_graph', 'lavfi_comparison'):
        command = list(production)
        command[graph_index] = source+','+filters+'[desktop]'
        if mode == 'lavfi_comparison':
            index = command.index('-filter_complex')
            del command[index:index+2]
            index = command.index('-map')
            command[index:index+2] = ['-f', 'lavfi', '-i', source, '-vf', filters]
        command[-3:-3] = ['-frames:v', '400']
        assert not any('ddagrab=' in value or 'gfxcapture=' in value for value in command)
        result = subprocess.run(command, capture_output=True, check=True, timeout=30,
                                creationflags=NO_WINDOW)
        parser = AviPacketStream()
        frames = parser.feed(result.stdout)
        parser.finish()
        check = subprocess.run([str(ffmpeg), '-v', 'error', '-i', 'pipe:0',
                                '-f', 'framemd5', '-'], input=b''.join(frames),
                               capture_output=True, check=True, timeout=30,
                               creationflags=NO_WINDOW)
        hashes = [line.rsplit(',', 1)[1].strip() for line in check.stdout.decode().splitlines()
                  if not line.startswith('#')]
        idrs = [index for index, frame in enumerate(frames) if is_idr(frame)]
        assert len(frames) == len(hashes) == 400
        assert max(map(len, frames)) <= 56_000
        assert idrs == [0, 100, 200]
        assert not check.stderr, check.stderr.decode(errors='replace')
        # Compare the admitted source pictures before lossy rate control. Two
        # separately scheduled NVENC runs need not reconstruct identical pixels.
        raw_command = [str(ffmpeg), '-v', 'error', '-nostdin']
        if mode == 'direct_graph':
            raw_command += ['-filter_complex', source+','+filters+'[desktop]',
                            '-map', '[desktop]']
        else:
            raw_command += ['-f', 'lavfi', '-i', source, '-vf', filters]
        raw_command += ['-r', '100', '-fps_mode', 'cfr', '-frames:v', '400',
                        '-c:v', 'rawvideo', '-f', 'framemd5', '-']
        raw_result = subprocess.run(raw_command, capture_output=True, check=True,
                                    timeout=30, creationflags=NO_WINDOW)
        unencoded[mode] = [line.rsplit(',', 1)[1].strip()
                          for line in raw_result.stdout.decode().splitlines()
                          if not line.startswith('#')]
        assert len(unencoded[mode]) == 400
        results.append(dict(mode=mode, frames=len(frames), maximum_frame_bytes=max(map(len, frames)),
                            oversized_frames=0, startup_idrs=idrs, decoder_errors=''))
    assert unencoded['direct_graph'] == unencoded['lavfi_comparison'], 'Admitted synthetic pictures differ'
    return dict(resolution='1920x1080', fps=100, bitrate_mbps=20, encoder='h264_nvenc',
                preset='p4', results=results, preencode_pixels_identical=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', type=Path, default=ROOT/'vendor/ffmpeg/ffmpeg.exe')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check-encoder', action='store_true',
                        help='Also exercise NVIDIA NVENC on synthetic frames, without screen/USB access')
    args = parser.parse_args()
    ffmpeg = args.ffmpeg.resolve(strict=True)
    if args.output.exists():
        parser.error('Choose a new output file; existing evidence is not overwritten')

    count = 600
    raw = b''.join(bytes(235 if frame & (1 << bit) else 16 for bit in range(16))*16
                   for frame in range(count))
    cases = []
    for fps in (60, 75, 90, 100):
        selection = production_selection(ffmpeg, fps)
        for source_fps in (fps, fps-0.1, fps+0.1, 240, 30):
            for gap in (0, 20, 200):
                for jitter in (0, 500, -500):
                    ids = select_ids(ffmpeg, raw, source_fps, fps, gap, jitter, selection)
                    case = (fps, source_fps, gap, jitter)
                    assert ids and all(0 <= value < count for value in ids), case
                    assert ids == sorted(ids) and len(ids) == len(set(ids)), case
                    if source_fps <= fps:
                        assert ids == list(range(count)), case
                    else:
                        assert abs(len(ids)-count*fps/source_fps) <= 3, case
                    if gap:
                        assert 300 in ids, ('First fresh frame after gap was lost', case)

                    # One-frame tolerance for scheduling jitter, matching the SDK.
                    times = [round(Fraction(i*1_000_000)/Fraction(str(source_fps)))
                             + (gap*1000 if i >= 300 else 0)
                             + ((2*(i % 2)-1)*jitter if i else 0) for i in ids]
                    minimum_offset = -times[0]*fps/1_000_000
                    for index, timestamp in enumerate(times):
                        offset = index-timestamp*fps/1_000_000
                        assert offset-minimum_offset <= 1+fps/1_000_000, case
                        minimum_offset = min(minimum_offset, offset)
                    cases.append(dict(fps=fps, source_fps=source_fps, gap_ms=gap,
                                      jitter_us=jitter, frames=len(ids), duplicates=0,
                                      first_after_gap=next((i for i in ids if i >= 300), None)))

    controls = []
    for gap in (20, 200):
        ids = select_ids(ffmpeg, raw, 100, 100, gap, 0, 'fps=100:round=near')
        duplicates = len(ids)-len(set(ids))
        assert duplicates == gap//10 and ids.count(299) == 1+duplicates
        controls.append(dict(filter='fps=100:round=near', gap_ms=gap,
                             repeated_stale_frames=duplicates))

    manifest = dict(measurement='Synthetic frame identities; not optical or capture latency',
                    ffmpeg=str(ffmpeg), ffmpeg_sha256=hashlib.sha256(ffmpeg.read_bytes()).hexdigest(),
                    production_cases=cases, old_filter_controls=controls)
    if args.check_encoder:
        manifest['synthetic_encoder'] = check_synthetic_encoder(ffmpeg)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, indent=2)
        stream.write('\n')
    print(f'Passed {len(cases)} production frame-ID checks and {len(controls)} stale-frame controls; '
          f'no screen/USB access. Results: {args.output}')


if __name__ == '__main__':
    main()
