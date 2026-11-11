"""Offline generated-content quality diagnostic; NEVER captures a desktop or opens USB.

Both paths encode with NVIDIA NVENC. cpu-nv12 feeds canonical generated NV12;
gpu-upload converts its deterministic RGB equivalent through production D3D11.
The latter exercises conversion/texture reuse, NOT DDA capture ownership. Quality
and throughput runs must be scheduled separately; this is not a latency test.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from goggles_bridge.avi import AviPacketStream
from goggles_bridge.annexb import is_idr
from goggles_bridge.engine import MAX_FRAME_BYTES

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
FPS = 100
NAL_START = re.compile(rb'\x00\x00(?:\x00)?\x01')
TRACE_FIELD = re.compile(r'\]\s+\d+\s+([A-Za-z0-9_]+)(?:\[\d+\])?\s+\S+\s+=\s+(-?\d+)')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def distribution(values):
    a = sorted(float(x) for x in values if x is not None)
    if not a:
        return None
    return dict(count=len(a), mean=sum(a)/len(a), **{
        k: a[int((len(a)-1)*p)] for k, p in
        [('min', 0), ('p01', .01), ('p50', .5), ('p95', .95), ('p99', .99), ('max', 1)]})


def psnr(mse):
    # JSON null denotes exact identity; do not publish nonstandard Infinity.
    return None if mse == 0 else 10*math.log10(255**2/mse)


class Pattern:
    """Integer-only source, stable across NumPy versions and explicit frame IDs.

    Chroma is moderate and luma stays in gamut so RGB round-trip differences
    remain bounded. Every frame is new, including bootstrap. Eight spatial IDs
    can expose partial old/new textures even when the first marker is correct.
    """
    def __init__(self, width=1920, height=1080, scene='mixed', bootstrap=300, seed=53):
        require(width >= 320 and height >= 128 and width % 2 == height % 2 == 0,
                'Even dimensions >=320x128 required')
        self.width, self.height, self.scene = width, height, scene
        self.bootstrap, self.seed = bootstrap, seed
        self.x = np.arange(width, dtype=np.int32)[None, :]
        self.y = np.arange(height, dtype=np.int32)[:, None]
        self.marker_rects = [(x, y) for y in (8, height//3, 2*height//3, height-24)
                             for x in (8, width-136)]

    @staticmethod
    def noise(x, y, seed):
        # All arithmetic fits signed int32 for this bounded source domain.
        z = ((x*1103) ^ (y*2137) ^ (seed*733)) & 65535
        return ((z ^ (z >> 7))*109) & 255

    def phase(self, index):
        if index < self.bootstrap:
            return 'bootstrap'
        if self.scene != 'mixed':
            return self.scene
        return ('fast-pan', 'cut', 'fine', 'overwrite')[min(3, (index-self.bootstrap)//60)]

    def planes(self, index):
        phase = self.phase(index)
        n = index-self.bootstrap
        speed = 3 if phase == 'bootstrap' else 48
        px, py = self.x+index*speed, self.y+index*7
        seed = self.seed
        if phase == 'cut':
            seed += 23*(n//12)
            px, py = self.x+(n % 12)*28, self.y+(n % 12)*19
        elif phase == 'fine':
            px, py = self.x+index*5, self.y+index*3
        elif phase == 'overwrite':
            # Deliberately adversarial, independent content every frame.
            seed += 17*index
            px, py = self.x, self.y
        coarse = self.noise(px//32, py//32, seed)
        detail = self.noise(px//(2 if phase in ('fine', 'overwrite') else 8),
                            py//(2 if phase in ('fine', 'overwrite') else 8), seed+9)
        lum = (64 + coarse//3 + detail//6).astype(np.uint8)
        # A sparse high-contrast wire grid gives block/ringing metrics real edges.
        grid = ((px % 97) < 2) | ((py % 67) < 2)
        lum[grid] = 205
        uu = (120 + self.noise(px[:, ::2]//64, py[::2, :]//64, seed+3)//16).astype(np.uint8)
        vv = (120 + self.noise(px[:, ::2]//48, py[::2, :]//48, seed+5)//16).astype(np.uint8)
        for region, (left, top) in enumerate(self.marker_rects):
            coded = (index ^ (region*997)) & 65535
            for bit in range(16):
                lum[top:top+16, left+8*bit:left+8*(bit+1)] = 224 if coded & (1 << bit) else 24
            uu[top//2:(top+16)//2, left//2:(left+128)//2] = 128
            vv[top//2:(top+16)//2, left//2:(left+128)//2] = 128
        return lum, uu, vv

    def nv12(self, index):
        y, u, v = self.planes(index)
        uv = np.empty((self.height//2, self.width), dtype=np.uint8)
        uv[:, 0::2], uv[:, 1::2] = u, v
        return y.tobytes()+uv.tobytes()

    def bgra(self, index):
        y, u, v = self.planes(index)
        yf = (y.astype(np.float32)-16)*(255/219)
        uf = (np.repeat(np.repeat(u, 2, 0), 2, 1).astype(np.float32)-128)*(255/224)
        vf = (np.repeat(np.repeat(v, 2, 0), 2, 1).astype(np.float32)-128)*(255/224)
        out = np.empty((self.height, self.width, 4), dtype=np.uint8)
        for channel, values in enumerate((yf+1.8556*uf, yf-.187324*uf-.468124*vf, yf+1.5748*vf)):
            out[:, :, channel] = np.clip(np.rint(values), 0, 255).astype(np.uint8)
        out[:, :, 3] = 255
        return out.tobytes()

    def identity(self, y):
        ids, minimum_margin = [], 255.0
        for region, (left, top) in enumerate(self.marker_rects):
            coded = 0
            for bit in range(16):
                value = float(y[top+4:top+12, left+bit*8+2:left+bit*8+6].mean())
                minimum_margin = min(minimum_margin, abs(value-124))
                if value >= 124:
                    coded |= 1 << bit
            ids.append(coded ^ (region*997))
        return dict(region_ids=ids, minimum_cell_threshold_margin=minimum_margin,
                    regions_agree=len(set(ids)) == 1)


def planes_from_nv12(raw, width, height):
    require(len(raw) == width*height*3//2, 'Incomplete NV12 picture')
    all_data = np.frombuffer(raw, dtype=np.uint8)
    y = all_data[:width*height].reshape(height, width)
    uv = all_data[width*height:].reshape(height//2, width)
    return y, uv[:, 0::2], uv[:, 1::2]


def quality(actual, expected):
    result = {}
    total_square, total_count = 0., 0
    errors = []
    for name, a, b in zip(('y', 'u', 'v'), actual, expected):
        err = a.astype(np.float32)-b.astype(np.float32)
        errors.append(err)
        square = float(np.square(err).sum(dtype=np.float64))
        mse = square/err.size
        result[name+'_psnr_db'] = psnr(mse)
        result[name+'_mse'] = mse
        result[name+'_mae'] = float(np.abs(err).mean())
        result[name+'_max_abs_error'] = float(np.abs(err).max())
        total_square += square
        total_count += err.size
    result['yuv_psnr_db'] = psnr(total_square/total_count)
    e = errors[0]
    h, w = (x//16*16 for x in e.shape)
    block_mse = np.square(e[:h, :w]).reshape(h//16, 16, w//16, 16).mean(axis=(1, 3))
    result['block16_mse_p95'] = float(np.percentile(block_mse, 95))
    result['block16_mse_max'] = float(block_mse.max())
    result['block16_fraction_mse_over_100'] = float((block_mse > 100).mean())
    # Boundary error jump, subtracting the true source edge by differencing the
    # residual rather than the decoded image. Not a perceptual quality score.
    jumps = np.concatenate((np.abs(e[:, 16::16]-e[:, 15:-1:16]).ravel(),
                            np.abs(e[16::16, :]-e[15:-1:16, :]).ravel()))
    result['block16_boundary_residual_mae'] = float(jumps.mean())
    result['block16_boundary_residual_p95'] = float(np.percentile(jumps, 95))
    return result


def set_option(command, name, value):
    if name in command:
        position = command.index(name)
        command[position+1] = str(value)
    else:
        command[-3:-3] = [name, str(value)]


def remove_option(command, name):
    while name in command:
        at = command.index(name)
        del command[at:at+2]


def commands(args):
    command = json.loads(args.template.read_text(encoding='utf-8'))
    command[0] = str(args.ffmpeg)
    remove_option(command, '-latest_frame')
    graph_at = command.index('-filter_complex')+1
    source, _, filters = command[graph_at].partition(',')
    require(source.startswith('ddagrab=') and filters.endswith('[desktop]'), 'Unknown frozen graph')
    if args.path == 'cpu-nv12':
        remove_option(command, '-init_hw_device')
        remove_option(command, '-filter_hw_device')
        graph_at = command.index('-filter_complex')+1
        filters = re.sub(r'scale_d3d11=[^,;\[]+', 'format=nv12', filters)
        command[graph_at] = '[0:v]'+filters
    else:
        command[command.index('-init_hw_device')+1] = f'd3d11va=cap:{args.adapter}'
        command[graph_at] = '[0:v]hwupload,'+filters
    at = command.index('-filter_complex')
    command[at:at] = ['-f', 'rawvideo', '-pixel_format', 'nv12' if args.path == 'cpu-nv12' else 'bgra',
        '-video_size', '1920x1080', '-framerate', '100', '-i', 'pipe:0']
    for key, value in (('-frames:v', args.frames), ('-fps_mode', 'cfr'),
        ('-profile:v', args.profile), ('-preset', args.preset), ('-spatial-aq', args.spatial_aq),
        ('-temporal-aq', args.temporal_aq), ('-aq-strength', args.aq_strength),
        ('-refs', args.refs), ('-multipass', args.multipass), ('-async_encode', args.async_encode)):
        set_option(command, key, value)
    if args.surfaces is not None:
        set_option(command, '-surfaces', args.surfaces)
    if args.buffer_bits is not None:
        set_option(command, '-bufsize', args.buffer_bits)
    if '-coder' in command:
        coder = command[command.index('-coder')+1]
        require(not (args.profile == 'baseline' and coder in ('cabac', '1')),
                'Baseline cannot use explicit CABAC; select --profile high for the candidate template')
    require(not any('ddagrab=' in x or 'gfxcapture=' in x for x in command), 'Capture source refused')
    require(command[command.index('-c:v')+1] == 'h264_nvenc', 'NVENC required')
    return command


def run_stream(command, input_frames, receive, timeout):
    """One bounded source frame and output chunk at a time, with a deadline."""
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=errors, creationflags=NO_WINDOW)
        writer_errors = []
        def write():
            try:
                for frame in input_frames:
                    proc.stdin.write(frame)
                proc.stdin.close()
            except BaseException as error:
                writer_errors.append(str(error))
                try:proc.stdin.close()
                except OSError:pass
        worker = threading.Thread(target=write, daemon=True)
        expired = threading.Event()
        def kill():
            expired.set()
            try:proc.kill()
            except OSError:pass
        timer = threading.Timer(timeout, kill)
        timer.daemon = True
        timer.start();worker.start()
        try:
            while data := proc.stdout.read(65536):
                receive(data)
            proc.wait(timeout=10)
            worker.join(timeout=10)
            errors.seek(0)
            stderr = errors.read().decode(errors='replace')
            require(not expired.is_set(), 'FFmpeg timed out')
            require(not worker.is_alive(), 'Input writer did not finish')
            require(proc.returncode == 0, f'FFmpeg exited {proc.returncode}: {stderr[-4000:]}')
            require(not writer_errors, f'Input writer failed: {writer_errors}')
            return stderr
        finally:
            timer.cancel()
            if proc.poll() is None:proc.kill()
            proc.wait()
            proc.stdout.close()
            # Receive/parse failures also interrupt the input pipe. Reap that
            # writer here instead of leaving a daemon to outlive the run.
            worker.join(timeout=10)
            if not worker.is_alive():
                try:proc.stdin.close()
                except OSError:pass
            require(not worker.is_alive(), 'Input writer did not finish during cleanup')


def encode(args, pattern, command):
    parser = AviPacketStream()
    frames = []
    def receive(chunk):
        frames.extend(parser.feed(chunk))
        require(len(frames) <= args.frames and sum(map(len, frames)) <= 96*1024*1024,
                'Encoded output exceeded bounded allocation')
    source = pattern.nv12 if args.path == 'cpu-nv12' else pattern.bgra
    stderr = run_stream(command, (source(i) for i in range(args.frames)), receive, args.timeout)
    parser.finish()
    require(len(frames) == args.frames, f'Expected {args.frames} AUs, got {len(frames)}')
    return frames, stderr


def decode(args, frames, pattern, verify_metrics=True):
    command = [str(args.ffmpeg), '-hide_banner', '-nostdin', '-v', 'error', '-xerror',
        '-hwaccel', 'none', '-threads', '1', '-c:v', 'h264', '-f', 'h264', '-i', 'pipe:0',
        '-an', '-threads', '1', '-c:v', 'rawvideo', '-pix_fmt', 'nv12',
        '-fps_mode', 'passthrough', '-f', 'rawvideo', 'pipe:1']
    pending = bytearray(); rows = []; hashes = []
    size = pattern.width*pattern.height*3//2
    def receive(chunk):
        pending.extend(chunk)
        while len(pending) >= size:
            data = bytes(pending[:size]);del pending[:size]
            i = len(hashes)
            hashes.append(hashlib.sha256(data).hexdigest())
            if verify_metrics:
                require(i < args.frames, 'Unexpected extra decoded image')
                actual = planes_from_nv12(data, pattern.width, pattern.height)
                row = dict(index=i, phase=pattern.phase(i), identity=pattern.identity(actual[0]),
                           **quality(actual, pattern.planes(i)))
                row['correct_id'] = all(x == i for x in row['identity']['region_ids'])
                rows.append(row)
    stderr = run_stream(command, iter(frames), receive, args.timeout)
    require(not pending, 'Partial decoded picture')
    require(not stderr.strip(), f'Decode errors: {stderr}')
    require(len(hashes) == len(frames), 'Decoded picture/AU count mismatch')
    return rows, hashes


def parse_trace(text):
    """Extract slice *initial* QP; macroblock AQ deltas are deliberately unknown."""
    pps = {};sps = {}; slices = []; current = None; kind = None
    def flush():
        nonlocal current
        if not current:return
        if kind == 'pps' and 'pic_parameter_set_id' in current:
            pps[current['pic_parameter_set_id']] = current
        elif kind == 'sps' and 'seq_parameter_set_id' in current:
            sps[current['seq_parameter_set_id']] = current
        elif kind == 'slice':
            config = pps.get(current.get('pic_parameter_set_id'), {})
            current['initial_qp'] = (26+config['pic_init_qp_minus26']+current['slice_qp_delta']
                if 'pic_init_qp_minus26' in config and 'slice_qp_delta' in current else None)
            current['sps_id'] = config.get('seq_parameter_set_id')
            slices.append(current)
        current = None
    for line in text.splitlines():
        if 'Sequence Parameter Set' in line:
            flush();kind='sps';current={}
        elif 'Picture Parameter Set' in line:
            flush();kind='pps';current={}
        elif 'Slice Header' in line:
            flush();kind='slice';current={}
        else:
            match = TRACE_FIELD.search(line)
            if current is not None and match:
                current[match.group(1)] = int(match.group(2))
            elif '[trace_headers @ ' in line and not match:
                body = line.partition(']')[2].strip()
                # AUD/SEI/filler headers have their own nal_ref_idc/type. Never
                # let those fields overwrite the preceding slice's identity.
                if body and not body[0].isdigit():
                    flush();kind=None
    flush()
    pictures = [x for x in slices if x.get('first_mb_in_slice') == 0]
    errors = []
    for i, pic in enumerate(pictures):
        config = sps.get(pic.get('sps_id'), {})
        modulo = 1 << (config.get('log2_max_frame_num_minus4', 0)+4)
        frame_num = pic.get('frame_num')
        if pic.get('nal_unit_type') == 5:
            if frame_num != 0:errors.append(f'IDR picture {i} has nonzero frame_num')
        elif i and frame_num is not None:
            # This diagnostic fixes B=0 and expects every P picture to be a ref.
            previous = pictures[i-1]
            expected = (previous.get('frame_num', -1)+bool(previous.get('nal_ref_idc', 0))) % modulo
            if frame_num != expected:
                errors.append(f'Unexpected frame_num at {i}: {frame_num}, expected {expected}')
    return dict(sps=list(sps.values()), pps=list(pps.values()), pictures=pictures,
                slice_count=len(slices), frame_num_errors=errors,
                qp_scope='Initial slice QP only; macroblock/AQ QP is unavailable')


def trace(args, frames):
    command = [str(args.ffmpeg), '-hide_banner', '-nostdin', '-v', 'verbose', '-f', 'h264',
        '-i', 'pipe:0', '-c:v', 'copy', '-bsf:v', 'trace_headers', '-f', 'null', '-']
    # Header trace is generated only after timed encoding, and bounded here.
    result = subprocess.run(command, input=b''.join(frames), stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, creationflags=NO_WINDOW, timeout=args.timeout)
    require(result.returncode == 0, 'H.264 header tracing failed')
    text = result.stderr.decode(errors='replace')
    require(len(text) < 40*1024*1024, 'Unexpectedly large header trace')
    return parse_trace(text)


def gpu_raw_check(args, pattern):
    """Independent conversion/reuse test; NOT the exact NVENC input surfaces."""
    command = [str(args.ffmpeg), '-hide_banner', '-nostdin', '-v', 'error',
        '-init_hw_device', f'd3d11va=cap:{args.adapter}', '-filter_hw_device', 'cap',
        '-f', 'rawvideo', '-pixel_format', 'bgra', '-video_size', '1920x1080',
        '-framerate', '100', '-i', 'pipe:0', '-vf',
        'hwupload,scale_d3d11=width=1920:height=1080:format=nv12:desktop_sdr=1,hwdownload,format=nv12',
        '-frames:v', str(args.frames), '-c:v', 'rawvideo', '-pix_fmt', 'nv12', '-f', 'rawvideo', 'pipe:1']
    pending = bytearray(); rows = [];size=1920*1080*3//2
    def receive(chunk):
        pending.extend(chunk)
        while len(pending)>=size:
            data=bytes(pending[:size]);del pending[:size]
            index=len(rows);require(index<args.frames,'Extra GPU raw frame')
            actual=planes_from_nv12(data,1920,1080)
            ids=pattern.identity(actual[0])
            rows.append(dict(index=index,phase=pattern.phase(index),
                correct_id=all(x==index for x in ids['region_ids']),
                **quality(actual,pattern.planes(index))))
    stderr=run_stream(command,(pattern.bgra(i) for i in range(args.frames)),receive,args.timeout)
    require(not pending and len(rows)==args.frames,'GPU raw frame count mismatch')
    require(not stderr.strip(),f'GPU raw conversion errors: {stderr}')
    return dict(scope='Separate upload/VP/readback pass; no NVENC; not DDA or exact encoded input surfaces',
                frames=len(rows),wrong_identity_count=sum(not x['correct_id'] for x in rows),
                y_psnr_db=distribution(x['y_psnr_db'] for x in rows),
                maximum_y_error=max(x['y_max_abs_error'] for x in rows),rows=rows)


def summary(rows):
    names=('y_psnr_db','yuv_psnr_db','y_mae','u_mae','v_mae','block16_mse_p95',
           'block16_mse_max','block16_fraction_mse_over_100','block16_boundary_residual_mae',
           'au_bytes','initial_slice_qp')
    return dict(frames=len(rows),wrong_identity_count=sum(not x['correct_id'] for x in rows),
                **{key:distribution(x.get(key) for x in rows) for key in names})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg',type=Path,default=ROOT/'vendor/ffmpeg/ffmpeg.exe')
    parser.add_argument('--template',type=Path,default=HERE/'baseline-command-v024.json')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--path',choices=('cpu-nv12','gpu-upload'),default='cpu-nv12')
    parser.add_argument('--scene',choices=('mixed','fast-pan','cut','fine','overwrite'),default='mixed')
    parser.add_argument('--frames',type=int,default=540)
    parser.add_argument('--bootstrap',type=int,default=300)
    parser.add_argument('--seed',type=int,default=53)
    parser.add_argument('--adapter',type=int,default=0)
    parser.add_argument('--profile',choices=('baseline','main','high'),default='baseline')
    parser.add_argument('--preset',choices=('p1','p4'),default='p4')
    parser.add_argument('--spatial-aq',type=int,choices=(0,1),default=0)
    parser.add_argument('--temporal-aq',type=int,choices=(0,1),default=0)
    parser.add_argument('--aq-strength',type=int,choices=range(1,16),default=8)
    parser.add_argument('--refs',type=int,choices=(1,2,3),default=1)
    parser.add_argument('--multipass',choices=('disabled','qres','fullres'),default='qres')
    parser.add_argument('--async-encode',type=int,choices=(0,1),default=1)
    parser.add_argument('--surfaces',type=int)
    parser.add_argument('--buffer-bits',type=int)
    parser.add_argument('--timeout',type=int,default=240)
    parser.add_argument('--gpu-raw-check',action='store_true')
    parser.add_argument('--skip-reference-restart',action='store_true')
    parser.add_argument('--save-generated-h264',type=Path,
        help='Optional synthetic evidence only; no video is saved by default')
    args=parser.parse_args()
    if args.output.exists():parser.error('Choose a fresh report path')
    if not 1<=args.frames<=1000 or not 0<=args.bootstrap<args.frames:parser.error('Invalid bounded frame window')
    if not 0<=args.seed<=10000:parser.error('Seed must be 0..10000')
    if args.surfaces is not None and not 1<=args.surfaces<=64:parser.error('Surfaces must be 1..64')
    if args.buffer_bits is not None and args.buffer_bits<=0:parser.error('Buffer bits must be positive')
    if args.gpu_raw_check and args.path!='gpu-upload':parser.error('GPU raw check requires gpu-upload')
    if args.save_generated_h264 and args.save_generated_h264.exists():parser.error('Video output already exists')
    args.ffmpeg=args.ffmpeg.resolve(strict=True)
    command=commands(args)
    report=dict(status='running',scope=__doc__,screen_capture=False,usb_access=False,
        optical_or_live_pacing_test=False,width=1920,height=1080,fps=100,bitrate_target_mbps=20,
        source_path=args.path,source_scene=args.scene,bootstrap_frames=args.bootstrap,seed=args.seed,
        ffmpeg_sha256=hashlib.sha256(args.ffmpeg.read_bytes()).hexdigest(),
        template_sha256=hashlib.sha256(args.template.read_bytes()).hexdigest(),
        command=['{ffmpeg}',*command[1:]],source_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    began=time.monotonic();exit_code=0
    try:
        pattern=Pattern(scene=args.scene,bootstrap=args.bootstrap,seed=args.seed)
        print('Encoding generated source',flush=True)
        frames,report['encoder_stderr']=encode(args,pattern,command)
        print('Decoding on CPU and comparing every picture',flush=True)
        rows,hashes=decode(args,frames,pattern)
        headers=trace(args,frames)
        require(len(headers['pictures'])==len(frames),'Slice-header/AU count mismatch')
        for row,frame,picture in zip(rows,frames,headers['pictures']):
            row.update(au_bytes=len(frame),nominal_single_frame_mbps=len(frame)*8*100/1e6,
                       idr=is_idr(frame),initial_slice_qp=picture.get('initial_qp'),
                       frame_num=picture.get('frame_num'),slice_type=picture.get('slice_type'))
        report['reference_chain']=dict(header_frame_num_errors=headers['frame_num_errors'],
            decoded_frames=len(hashes),slice_count=headers['slice_count'],sps=headers['sps'],pps=headers['pps'],
            qp_scope=headers['qp_scope'],picture_count=len(headers['pictures']),restart_check='skipped')
        idrs=[i for i,f in enumerate(frames) if is_idr(f)]
        if not args.skip_reference_restart:
            restart=idrs[-1]
            _, restarted=decode(args,frames[restart:],pattern,verify_metrics=False)
            identical=restarted==hashes[restart:]
            report['reference_chain'].update(restart_check='passed' if identical else 'failed',
                restart_from_idr=restart,restarted_frames=len(restarted))
            require(identical,'Decode from last IDR differs from continuous reference chain')
        report.update(frames=len(frames),idr_frames=idrs,maximum_au_bytes=max(map(len,frames)),
            frames_exceeding_sdk_limit=sum(len(f)>MAX_FRAME_BYTES for f in frames),
            sdk_au_limit_bytes=MAX_FRAME_BYTES,summary=summary(rows),
            phases={p:summary([r for r in rows if r['phase']==p]) for p in sorted({r['phase'] for r in rows})},
            one_second_coded_mbps=[sum(len(f) for f in frames[i:i+100])*8/1e6
                for i in range(0,len(frames)-99,100)],rows=rows)
        if args.gpu_raw_check:
            print('Separately checking GPU conversion/reuse',flush=True)
            report['gpu_raw']=gpu_raw_check(args,pattern)
        if args.save_generated_h264:
            args.save_generated_h264.parent.mkdir(parents=True,exist_ok=True)
            with args.save_generated_h264.open('xb') as output:
                for frame in frames:output.write(frame)
        report['status']='passed' if (not report['summary']['wrong_identity_count'] and
            not headers['frame_num_errors'] and not report['frames_exceeding_sdk_limit'] and
            not report.get('gpu_raw',{}).get('wrong_identity_count',0)) else 'failed'
        report['status_scope']='Integrity/order/frame-budget only; quality metrics have no arbitrary pass threshold'
        exit_code=0 if report['status']=='passed' else 1
    except (Exception,KeyboardInterrupt) as error:
        report['status']='failed';report['error']=f'{type(error).__name__}: {error}'
        print(report['error'],file=sys.stderr);exit_code=1
    finally:
        report['elapsed_seconds']=time.monotonic()-began
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as output:
            json.dump(report,output,indent=2,allow_nan=False);output.write('\n')
    print(f"{report['status']}: {args.output}",flush=True)
    return exit_code


if __name__=='__main__':raise SystemExit(main())
