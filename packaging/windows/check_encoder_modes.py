"""Generated-video NVENC mode matrix; no desktop capture, USB, or timing claims.

Checks both resolutions, all refresh targets, both presets and each SDK bitrate
ceiling. A grey-to-motion cut occurs after startup IDRs. This finite content
sample is not a guarantee for every possible image or headset firmware.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from desktop_app.settings import bitrates
from desktop_app.video import compatible_command, ENCODER_PRIORITY
from goggles_bridge.annexb import is_idr
from goggles_bridge.avi import AviPacketStream
from goggles_bridge.engine import BridgeSettings, encoder_command, MAX_FRAME_BYTES, NO_WINDOW


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', type=Path, default=ROOT/'vendor/ffmpeg/ffmpeg.exe')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--adapter', type=int, default=0)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new evidence file')
    ffmpeg = args.ffmpeg.resolve(strict=True)
    results = []
    for dimensions in ((1280, 720), (1920, 1080)):
        for fps in (60, 75, 90, 100):
            for preset in ('p1', 'p4'):
                bitrate = max(bitrates(fps))
                count = 3*fps+5
                settings = BridgeSettings(Path('unused.dll'), ffmpeg, capture='ddagrab',
                    fps=fps, bitrate_mbps=bitrate, preset=preset)
                command = encoder_command(settings)
                command[-3:-3] = ['-frames:v', str(count)]
                command = compatible_command(command, dimensions=dimensions,
                    output=dict(adapter=args.adapter, output=0, vendor_id=0x10de,
                                width=dimensions[0], height=dimensions[1]))
                pos = command.index('-filter_complex')+1
                capture, _, filters = command[pos].partition(',')
                assert capture.startswith('ddagrab=') and '-latest_frame' not in command
                command[pos] = (
                    f'testsrc2=size={dimensions[0]}x{dimensions[1]}:rate={fps},format=bgra,'
                    f"drawbox=x=0:y=0:w=iw:h=ih:color=0x808080:t=fill:enable='lt(n,{2*fps+fps//3})',"
                    'hwupload,' + filters)
                assert not any('ddagrab=' in x or 'gfxcapture=' in x for x in command)
                encoded = subprocess.run(command, capture_output=True, timeout=45, check=True,
                    creationflags=NO_WINDOW | ENCODER_PRIORITY)
                reader = AviPacketStream()
                frames = reader.feed(encoded.stdout)
                reader.finish()
                data = b''.join(frames)
                decoded = subprocess.run([str(ffmpeg), '-v', 'error', '-i', 'pipe:0',
                    '-f', 'framemd5', 'pipe:1'], input=data, capture_output=True, timeout=30,
                    check=True, creationflags=NO_WINDOW)
                hashes = [x for x in decoded.stdout.decode().splitlines() if x and not x.startswith('#')]
                idrs = [i for i, frame in enumerate(frames) if is_idr(frame)]
                result = dict(resolution=list(dimensions), fps=fps, bitrate_mbps=bitrate,
                    preset=preset, frames=len(frames), decoded_frames=len(hashes),
                    maximum_frame_bytes=max(map(len, frames), default=0), startup_idrs=idrs,
                    decoder_errors=decoded.stderr.decode(errors='replace'))
                result['passed'] = (len(frames) == len(hashes) == count and
                    0 < result['maximum_frame_bytes'] <= MAX_FRAME_BYTES and
                    idrs == [0, fps, 2*fps] and not result['decoder_errors'])
                results.append(result)
                print(json.dumps(result), flush=True)
    result = dict(measurement='Finite generated codec/frame-budget checks, not hardware/optical acceptance',
        desktop_access=False, usb_access=False, ffmpeg_sha256=hashlib.sha256(ffmpeg.read_bytes()).hexdigest(),
        passed=all(x['passed'] for x in results), modes=results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
