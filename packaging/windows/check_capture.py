"""Opt-in real-desktop NVENC/AVI decode check. No screen images are saved.

Run on an unlocked Windows desktop. This checks host codec compatibility;
it does not open USB or observe the goggles. GPU pixel/geometry validation is
in check_gpu_pipeline.py; actual output timing is in check_stability.py.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from desktop_app.dxgi import outputs
from desktop_app.video import compatible_command, ENCODER_PRIORITY
from goggles_bridge.engine import BridgeSettings, encoder_command, MAX_FRAME_BYTES, NO_WINDOW
from goggles_bridge.avi import AviPacketStream
from goggles_bridge.annexb import is_idr


def headers(data):
    units = re.split(rb'\x00\x00(?:\x00)?\x01', data)
    return {kind: next(n for n in units if n and n[0] & 31 == kind) for kind in (7, 8)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', type=Path, default=ROOT/'vendor/ffmpeg/ffmpeg.exe')
    parser.add_argument('--adapter', type=int, default=0)
    parser.add_argument('--output-index', type=int, default=0)
    args = parser.parse_args()
    ffmpeg = args.ffmpeg.resolve(strict=True)
    target = next((x for x in outputs() if x['adapter'] == args.adapter and
                   x['output'] == args.output_index), None)
    if target is None:
        parser.error('The requested DXGI output is not attached')
    settings = BridgeSettings(dll=Path('unused.dll'), ffmpeg=ffmpeg,
                              capture='ddagrab', fps=100, bitrate_mbps=20, preset='p4')
    command = encoder_command(settings)
    # Bound before adaptation: the live latest-frame policy deliberately rejects
    # finite-frame encodes. Its overload behavior is checked by native tests.
    command[-3:-3] = ['-frames:v', '305']
    command = compatible_command(command, output=target)
    reference = list(command)
    for option in ('-init_hw_device', '-filter_hw_device'):
        while option in reference:
            pos = reference.index(option)
            del reference[pos:pos+2]
    reference[reference.index('-filter_complex')+1] = (
        'testsrc2=size=1920x1080:rate=100,format=nv12,setsar=1,'
        'setparams=range=limited:color_primaries=unknown:'
        'color_trc=unknown:colorspace=unknown[desktop]')
    results, expected = [], None
    for label, cmd in [('generated_reference', reference), ('desktop_duplication', command)]:
        encoded = subprocess.run(cmd, capture_output=True, timeout=45, check=True,
                                 creationflags=NO_WINDOW | ENCODER_PRIORITY)
        reader = AviPacketStream()
        frames = reader.feed(encoded.stdout)
        reader.finish()
        data = b''.join(frames)
        assert len(frames) == 305, (label, len(frames))
        assert max(map(len, frames)) <= MAX_FRAME_BYTES, label
        if expected is None:
            expected = headers(data)
        assert headers(data) == expected, f'{label}: SPS/PPS differs from reference'
        idrs = [i for i, frame in enumerate(frames) if is_idr(frame)]
        assert idrs == [0, 100, 200], (label, idrs)
        decoded = subprocess.run([str(ffmpeg), '-v', 'error', '-i', 'pipe:0',
            '-f', 'null', '-'], input=data, capture_output=True, timeout=30,
            check=True, creationflags=NO_WINDOW)
        assert not decoded.stderr, decoded.stderr.decode(errors='replace')
        results.append(dict(mode=label, frames=len(frames), max_frame_bytes=max(map(len, frames)),
                            idr_frames=idrs, header_match=True, decode_errors=0))
    print(json.dumps(dict(measurement='Host codec compatibility; not optical latency',
                          usb_access=False, screen_video_saved=False, results=results), indent=2))


if __name__ == '__main__':
    main()
