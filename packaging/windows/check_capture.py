"""Opt-in real-GPU regression: capture, parse, decode and compare H.264 headers.

Run on an unlocked Windows desktop. No desktop image/video is saved or uploaded.
This verifies host-side compatibility only; it cannot observe the goggles.
"""
from pathlib import Path
import json
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from desktop_app.settings import Settings
from desktop_app.video import compatible_command
from goggles_bridge.engine import encoder_command, MAX_FRAME_BYTES
from goggles_bridge.avi import AviPacketStream
from goggles_bridge.annexb import is_idr


def headers(data):
    units = re.split(rb'\x00\x00(?:\x00)?\x01',data)
    return {kind: next(n for n in units if n and n[0]&31 == kind) for kind in (7,8)}


def main():
    settings = Settings(fps=60,bitrate_mbps=8).bridge()
    reference = [str(settings.ffmpeg),'-hide_banner','-nostdin','-v','error',
        '-f','lavfi','-i','testsrc2=size=1920x1080:rate=60','-frames:v','125','-an',
        '-c:v','h264_nvenc','-preset','p1','-tune','ull','-rc','cbr','-b:v','8000000',
        '-maxrate','8000000','-bufsize','266666','-bf','0','-g','60','-profile:v','baseline',
        '-level:v','4.2','-aud','1','-forced-idr','1','-intra-refresh','0',
        '-pix_fmt','yuv420p','-f','h264','pipe:1']
    pattern = subprocess.run(reference,capture_output=True,timeout=30,check=True).stdout
    expected = headers(pattern)
    results = []
    for capture in ('gfxcapture','ddagrab'):
        settings = Settings(fps=60,bitrate_mbps=8,capture=capture).bridge()
        command = compatible_command(encoder_command(settings))
        command[-3:-3] = ['-frames:v','125']
        encoded = subprocess.run(command,capture_output=True,timeout=30,check=True)
        reader = AviPacketStream()
        frames = reader.feed(encoded.stdout)
        reader.finish()
        data = b''.join(frames)
        assert len(frames) == 125
        assert max(map(len,frames)) <= MAX_FRAME_BYTES
        assert headers(data) == expected, f'{capture}: SPS/PPS differs from synthetic clip'
        assert sum(is_idr(frame) for frame in frames) >= 2
        decoded = subprocess.run([str(settings.ffmpeg),'-v','error','-i','pipe:0',
            '-f','null','-'],input=data,capture_output=True,timeout=30,check=True)
        assert not decoded.stderr, decoded.stderr.decode(errors='replace')
        results.append(dict(capture=capture,frames=len(frames),max_frame_bytes=max(map(len,frames)),
            idr_frames=[i for i,f in enumerate(frames) if is_idr(f)],header_match=True,decode_errors=0))
    print(json.dumps(results,indent=2))


if __name__ == '__main__':
    main()
