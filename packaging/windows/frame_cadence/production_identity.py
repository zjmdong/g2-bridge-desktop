"""Bounded generated-pattern identity check using an actual release binary.

No native probe metadata, USB or live decode. While capturing, retain only AUs,
arrival QPC and bounded stderr in RAM. Decode markers after graceful drain.
"""
import argparse
import ctypes as C
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import threading

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from desktop_app.dxgi import outputs
from desktop_app.displays import inventory
from desktop_app.video import compatible_command, ENCODER_PRIORITY
from desktop_app.scheduling import configure_encoder_process, STREAM_GPU_PRIORITY_CLASS
from goggles_bridge.engine import BridgeSettings, encoder_command, prioritize_gpu, NO_WINDOW
from goggles_bridge.avi import AviPacketStream
from pattern_identity import decode_marker, FRAME_BYTES

MAX_FRAMES = 6500
MAX_ENCODED_BYTES = 256 * 1024 * 1024
MAX_LOG_BYTES = 4 * 1024 * 1024
KERNEL = C.WinDLL('kernel32', use_last_error=True)
for function in ('QueryPerformanceCounter', 'QueryPerformanceFrequency'):
    getattr(KERNEL, function).argtypes = [C.POINTER(C.c_int64)]
    getattr(KERNEL, function).restype = C.c_int


def qpc():
    value = C.c_int64()
    if not KERNEL.QueryPerformanceCounter(C.byref(value)):
        raise C.WinError(C.get_last_error())
    return value.value


def distribution(values):
    data = sorted(values)
    if not data:
        return None
    return dict(count=len(data), mean=sum(data)/len(data), **{
        name: data[int((len(data)-1)*fraction)]
        for name, fraction in [('min',0),('p01',.01),('p50',.5),('p95',.95),('p99',.99),('max',1)]})


def capabilities(ffmpeg):
    # These help requests happen before the timed run and do not open a GPU.
    def query(name):
        result = subprocess.run([str(ffmpeg), '-hide_banner', '-h', 'filter='+name],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=NO_WINDOW, timeout=15)
        text = result.stdout + result.stderr
        if result.returncode or not re.search(r'^Filter '+re.escape(name)+r'\b', text, re.M):
            raise ValueError('Binary is missing required filter: '+name)
        return text
    text = query('ddagrab')
    query('crop')
    return set(re.findall(r'^\s+(\w+)\s+<', text, re.M))


def make_command(ffmpeg, target, preset, fresh_wait_us, delivery_delay_us, available):
    for key, value in [('fresh_wait_us', fresh_wait_us), ('delivery_delay_us', delivery_delay_us)]:
        if value and key not in available:
            raise ValueError('Requested native option is unavailable: '+key)
    settings = BridgeSettings(dll=Path('unused.dll'), ffmpeg=ffmpeg, capture='ddagrab',
        fps=100, bitrate_mbps=20, preset=preset, display_index=target['output'])
    command = compatible_command(encoder_command(settings), output=target, dimensions=(1920,1080))
    if '-nostdin' in command:
        command.remove('-nostdin')
    command[command.index('-loglevel')+1] = 'info'
    position = command.index('-filter_complex')+1
    source, separator, filters = command[position].partition(',')
    if not source.startswith('ddagrab=') or not separator:
        raise ValueError('Expected direct DDA production graph')
    options = dict(item.split('=',1) for item in source[len('ddagrab='):].split(':'))
    for key, value in [('fresh_wait_us',fresh_wait_us), ('delivery_delay_us',delivery_delay_us)]:
        options.pop(key, None)
        # Zero means the historical binary's disabled default; never pass an
        # unsupported flag to the reference binary or inherit future defaults.
        if value:
            options[key] = str(value)
    command[position] = 'ddagrab='+':'.join(f'{k}={v}' for k,v in options.items())+separator+filters
    if options.get('framerate') != '100' or command[command.index('-r')+1] != '100':
        raise ValueError('Production command changed fixed 100 fps policy')
    for key, expected in [('-c:v','h264_nvenc'),('-profile:v','high'),('-coder','cabac'),
        ('-qp_cb_offset','-4'),('-qp_cr_offset','-4'),('-b:v','20000000'),('-maxrate','20000000'),
        ('-bufsize','400000'),('-bf','0'),('-rc-lookahead','0'),('-multipass','qres')]:
        if command[command.index(key)+1] != expected:
            raise ValueError('Production command differs from frozen 0.2.5 quality policy: '+key)
    return command


def decode_identities(ffmpeg, frames, arrivals, frequency, started, warmup, seconds, primary):
    if len(frames)>MAX_FRAMES or sum(map(len, frames))>MAX_ENCODED_BYTES:
        raise ValueError('Encoded memory limit exceeded before offline decode')
    crop_y = 146 if primary else 8
    command = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-nostdin',
        '-hwaccel', 'none', '-threads', '1', '-c:v', 'h264', '-f', 'h264', '-i', 'pipe:0',
        '-vf', f'crop=512:48:16:{crop_y},format=gray', '-an', '-fps_mode', 'passthrough',
        '-threads', '1', '-f', 'rawvideo', 'pipe:1']
    decoded = subprocess.run(command, input=b''.join(frames), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, creationflags=NO_WINDOW, timeout=180)
    errors = []
    decoder_errors = decoded.stderr.decode(errors='replace')
    if decoded.returncode or decoder_errors.strip():
        errors.append('Offline decoder returned an error or emitted error-level diagnostics')
    if len(decoded.stdout)%FRAME_BYTES:
        errors.append('Partial cropped luma frame')
    count = len(decoded.stdout)//FRAME_BYTES
    if count != len(frames) or count != len(arrivals):
        errors.append('Decoded/AU/arrival counts differ')
    rows = []
    for index in range(min(count, len(arrivals))):
        marker = decode_marker(memoryview(decoded.stdout)[index*FRAME_BYTES:(index+1)*FRAME_BYTES])
        row = dict(index=index, **marker, **arrivals[index])
        row['included_in_summary'] = started+warmup*frequency <= row['arrival_qpc'] <= started+seconds*frequency
        if marker['uncertain_bits']:
            errors.append(f'Uncertain marker cells at frame {index}')
        if not 0 < marker['render_qpc'] <= row['arrival_qpc']:
            errors.append(f'Noncausal renderer QPC at frame {index}')
        if rows:
            old = rows[-1]
            if row['frame_id'] < old['frame_id'] or row['render_qpc'] < old['render_qpc']:
                errors.append(f'Backward identity/QPC at frame {index}')
            if (row['frame_id']==old['frame_id']) != (row['render_qpc']==old['render_qpc']):
                errors.append(f'Inconsistent repeated identity/QPC at frame {index}')
        rows.append(row)
    chosen = [r for r in rows if r['included_in_summary']]
    if not chosen:
        errors.append('No identity frames within requested measurement window')
    unique = [r for i,r in enumerate(chosen) if not i or r['frame_id'] != chosen[i-1]['frame_id']]
    gaps = [(b['arrival_qpc']-a['arrival_qpc'])*1000/frequency for a,b in zip(chosen,chosen[1:])]
    id_deltas = [b['frame_id']-a['frame_id'] for a,b in zip(chosen,chosen[1:])]
    bins = []
    for second in range(math.ceil(warmup),math.floor(seconds)):
        window = [r for r in chosen if second*frequency <= r['arrival_qpc']-started < (second+1)*frequency]
        bins.append(dict(start_seconds=second,encoded_frames=len(window),
            unique_source_ids=len({r['frame_id'] for r in window}),
            encoded_mbps=sum(r['encoded_bytes'] for r in window)*8/1_000_000))
    span = (chosen[-1]['arrival_qpc']-chosen[0]['arrival_qpc'])/frequency if len(chosen)>1 else 0
    return dict(status='completed' if rows and not errors else 'failed',
        errors=errors[:30], error_count=len(errors), decoder_returncode=decoded.returncode,
        decoder_errors=decoder_errors[:8000], decoded_frames=count, measured_frames=len(chosen),
        unique_source_ids=len(unique), repeated_source_ids=len(chosen)-len(unique),
        skipped_source_ids=sum(max(0,v-1) for v in id_deltas),
        measured_au_fps=(len(chosen)-1)/span if span else None,
        source_render_to_host_ms=distribution([(r['arrival_qpc']-r['render_qpc'])*1000/frequency for r in chosen]),
        unique_source_render_to_host_ms=distribution([(r['arrival_qpc']-r['render_qpc'])*1000/frequency for r in unique]),
        au_interval_ms=distribution(gaps), intervals_over15ms=sum(v>15 for v in gaps),
        intervals_within_one_percent=sum(abs(v-10)<=.1 for v in gaps),
        min_marker_margin=min((r['min_threshold_margin'] for r in rows),default=None),
        one_second_output=bins, records=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg',type=Path,default=ROOT/'vendor/ffmpeg/ffmpeg.exe')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--adapter',type=int,default=0)
    parser.add_argument('--output-index',type=int,choices=(0,1),default=1)
    parser.add_argument('--seconds',type=float,default=20)
    parser.add_argument('--warmup',type=float,default=3)
    parser.add_argument('--primary',action='store_true')
    parser.add_argument('--preset',choices=('p1','p4'),default='p4')
    parser.add_argument('--fresh-wait-us',type=int,choices=(0,2000),default=0)
    parser.add_argument('--delivery-delay-us',type=int,choices=(0,8000),default=0)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a fresh output report')
    if not 0<=args.warmup<args.seconds<=60:
        parser.error('Require0<=warmup<seconds<=60')
    ffmpeg = args.ffmpeg.resolve(strict=True)
    try:
        available = capabilities(ffmpeg)
        target = next((r for r in outputs() if r['adapter']==args.adapter and r['output']==args.output_index),None)
        if target is None or target.get('vendor_id')!=0x10de:
            raise ValueError('Requested attached NVIDIA output unavailable')
        display = next((r for r in inventory() if r['device']==target['device']),None)
        dims = (3440,1440) if args.primary else (1920,1080)
        if not display or not display['active'] or bool(display['primary']) != args.primary or display['hz']!=100 or (target['width'],target['height'])!=dims:
            raise ValueError('Synthetic source requires matching primary/extended geometry and nominal100Hz')
        if args.primary and (display['x'],display['y']) != (0,0):
            raise ValueError('Primary synthetic source must begin at0,0')
        command = make_command(ffmpeg,target,args.preset,args.fresh_wait_us,args.delivery_delay_us,available)
    except (ValueError,OSError,subprocess.TimeoutExpired) as exc:
        parser.error(str(exc))
    canonical_command = json.dumps(command,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    ffmpeg_sha = hashlib.sha256(ffmpeg.read_bytes()).hexdigest()
    adapter_sha = hashlib.sha256((ROOT/'desktop_app/video.py').read_bytes()).hexdigest()
    frequency = C.c_int64()
    if not KERNEL.QueryPerformanceFrequency(C.byref(frequency)):
        raise C.WinError(C.get_last_error())
    frequency = frequency.value
    frames, arrivals, stderr_chunks = [], [], []
    encoded_bytes = 0
    errors = []
    interrupted = threading.Event()
    stderr_overflow = threading.Event()
    reader = AviPacketStream()
    started = qpc()
    process = subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        bufsize=0,creationflags=NO_WINDOW|ENCODER_PRIORITY)
    qos = configure_encoder_process(process)
    def finish():
        try:
            process.stdin.write(b'q\n')
            process.stdin.flush()
        except (OSError,ValueError):
            pass
    def kill():
        if process.poll() is None:
            interrupted.set()
            process.kill()
    def stderr_reader():
        total = 0
        while chunk := process.stderr.read(65536):
            if total+len(chunk)<=MAX_LOG_BYTES:
                stderr_chunks.append(chunk)
                total += len(chunk)
            else:
                stderr_overflow.set()
                finish()
    log_thread = threading.Thread(target=stderr_reader,daemon=True)
    stop = threading.Timer(args.seconds,finish)
    watchdog = threading.Timer(args.seconds+15,kill)
    log_thread.start(); stop.start(); watchdog.start()
    priority = None
    parse_error = None
    memory_full = False
    try:
        while data := process.stdout.read(16384):
            if parse_error:
                continue  # Drain owned child's pipe after requesting graceful stop.
            try:
                packets = reader.feed(data)
            except ValueError as exc:
                parse_error = str(exc); finish(); continue
            for frame in packets:
                stamp = qpc()
                if priority is None:
                    priority = prioritize_gpu(process,STREAM_GPU_PRIORITY_CLASS)
                if len(frames)>=MAX_FRAMES or encoded_bytes+len(frame)>MAX_ENCODED_BYTES:
                    memory_full=True; finish(); continue
                encoded_bytes += len(frame)
                frames.append(frame)
                arrivals.append(dict(arrival_qpc=stamp,encoded_bytes=len(frame)))
        process.wait(timeout=5)
        if not parse_error:
            try:
                reader.finish()
            except ValueError as exc:
                parse_error=str(exc)
    finally:
        stop.cancel(); watchdog.cancel()
        if process.poll() is None:
            process.kill(); process.wait()
        log_thread.join(timeout=5)
        process.stdin.close(); process.stdout.close(); process.stderr.close()
    capture_finished = qpc()
    diagnostics = b''.join(stderr_chunks).decode(errors='replace')
    if process.returncode or interrupted.is_set():errors.append('Encoder did not complete graceful drain')
    if parse_error:errors.append(parse_error)
    if memory_full:errors.append('Bounded AU memory exceeded')
    if stderr_overflow.is_set() or log_thread.is_alive():errors.append('Bounded stderr capture failed')
    if not frames:errors.append('No complete AUs')
    identity = None
    if not errors:
        try:
            identity = decode_identities(ffmpeg,frames,arrivals,frequency,started,args.warmup,args.seconds,args.primary)
            if identity['status']!='completed':errors.append('Generated source identity check failed')
        except (ValueError,OSError,subprocess.TimeoutExpired) as exc:
            errors.append(str(exc))
    frames.clear()
    oversize = sum(r['encoded_bytes']>56000 for r in arrivals)
    if oversize:errors.append('AU exceeds actual SDK56000byte frame guard')
    result = dict(schema=1,status='completed' if not errors else 'failed',errors=errors,
        scope='Real releasebinary AU arrival and decoded generated source identity; not capturetimestamp/USB/optical latency',
        native_probe_metadata=False,screen_video_saved=False,usb_access=False,software_encoding=False,
        settings=dict(width=1920,height=1080,fps=100,bitrate_mbps=20,preset=args.preset,
            fresh_wait_us=args.fresh_wait_us,delivery_delay_us=args.delivery_delay_us),
        source=target,primary=args.primary,nominal_source_refresh_hz=display['hz'],
        marker_crop=[16,146 if args.primary else 8,512,48],
        ffmpeg_sha256=ffmpeg_sha,production_adapter_sha256=adapter_sha,
        helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        marker_helper_sha256=hashlib.sha256((HERE/'pattern_identity.py').read_bytes()).hexdigest(),
        command=command,command_sha256=hashlib.sha256(canonical_command).hexdigest(),
        native_source_options=sorted(available),frequency=frequency,start_qpc=started,
        capture_finished_qpc=capture_finished,seconds=args.seconds,warmup_seconds=args.warmup,
        process_returncode=process.returncode,qos=qos,gpu_priority=priority,
        requested_gpu_priority_class=STREAM_GPU_PRIORITY_CLASS,
        total_frames=len(arrivals),captured_payload_bytes=encoded_bytes,
        max_frame_bytes=max((r['encoded_bytes'] for r in arrivals),default=0),
        oversize_frames=oversize,frame_budget_target_met=bool(arrivals) and not oversize,
        pattern_identity=identity,arrival_records=arrivals,
        native_summary_lines=[line for line in diagnostics.splitlines() if re.search(r'latest|replac|DDA_SOURCE_CLOCK|delivery',line,re.I)])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    args.output.with_suffix('.log').write_text(diagnostics,encoding='utf-8')
    printable={k:v for k,v in result.items() if k not in ('command','pattern_identity','arrival_records','native_source_options')}
    if identity:printable['pattern_identity']={k:v for k,v in identity.items() if k not in ('records','one_second_output')}
    print(json.dumps(printable,ensure_ascii=False,indent=2))
    return 0 if result['status']=='completed' else 1


if __name__=='__main__':
    raise SystemExit(main())
