"""Measure host picture age through DDA provenance, not compact media timestamps.

Requires the isolated instrumented FFmpeg. Discards screen video in memory, uses
no USB, and emits numeric results. Present age on an unchanged/static desktop is
not latency; use moving generated content and inspect unique/repeat statistics.
"""
import argparse
from collections import deque
import ctypes as C
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from desktop_app.dxgi import outputs
from desktop_app.displays import inventory
from desktop_app.video import ENCODER_PRIORITY
from desktop_app.scheduling import configure_encoder_process
from goggles_bridge.engine import prioritize_gpu, NO_WINDOW

BASELINE_TEMPLATE=Path(__file__).with_name('baseline-command-v023.json')

KERNEL=C.WinDLL('kernel32',use_last_error=True)
for fn in ('QueryPerformanceCounter','QueryPerformanceFrequency'):
    getattr(KERNEL,fn).argtypes=[C.POINTER(C.c_int64)]
    getattr(KERNEL,fn).restype=C.c_int


def qpc():
    value=C.c_int64()
    if not KERNEL.QueryPerformanceCounter(C.byref(value)):
        raise C.WinError(C.get_last_error())
    return value.value


def distribution(values):
    data=sorted(values)
    if not data:
        return None
    return dict(count=len(data),mean=sum(data)/len(data),**{
        name: data[int((len(data)-1)*p)]
        for name,p in [('min',0),('p01',.01),('p50',.5),('p95',.95),('p99',.99),('max',1)]})


def set_option(command,key,value):
    if key in command:
        command[command.index(key)+1]=str(value)
    else:
        command[-3:-3]=[key,str(value)]


def native_source_options(ffmpeg):
    result=subprocess.run([str(ffmpeg),'-hide_banner','-h','filter=ddagrab'],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=NO_WINDOW,timeout=10)
    if result.returncode:raise ValueError('Could not query instrumented DDA options')
    return set(re.findall(r'^\s+(\w+)\s+<',result.stdout,re.M))


def frozen_baseline_command(ffmpeg,target,available_options=None):
    """Keep later application defaults out of historical 0.2.3 comparisons."""
    if target.get('vendor_id')!=0x10de:
        raise ValueError('Frozen hardware baseline requires an NVIDIA DXGI output')
    command=json.loads(BASELINE_TEMPLATE.read_text(encoding='utf-8'))['command']
    command[0]=str(ffmpeg)
    command[command.index('-init_hw_device')+1]=f"d3d11va=cap:{target['adapter']}"
    pos=command.index('-filter_complex')+1
    source,sep,filters=command[pos].partition(',')
    assert source.startswith('ddagrab=') and sep
    options=dict(item.split('=',1) for item in source[len('ddagrab='):].split(':'))
    options['output_idx']=str(target['output'])
    if available_options is None:available_options={'source_clock','source_guard_us','defer_release'}
    for key,value in (('source_clock','0'),('source_guard_us','2000'),('defer_release','0')):
        if key in available_options:options[key]=value
    command[pos]='ddagrab='+':'.join(f'{k}={v}' for k,v in options.items())+sep+filters
    return command


def measured_avi_reader():
    # Load an isolated copy of the existing parser so the probe can record AVI
    # chunk length before its normal AUD removal, without modifying SDK code or
    # monkeypatching the SDK module used by any other consumer. Payload handling
    # and bound checks remain exactly the production parser implementation.
    spec=importlib.util.spec_from_file_location('goggles_bridge._probe_avi',ROOT/'goggles_bridge/avi.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raw_sizes=deque()
    strip_aud=module.strip_aud
    def measured_strip_aud(data):
        frame=strip_aud(data)
        raw_sizes.append(len(data))
        return frame
    module.strip_aud=measured_strip_aud
    return module.AviPacketStream(),raw_sizes


def gpu_priority_policy(process,requested=None,skip=False):
    """Query/set only our owned child, once it has created a graphics context."""
    result=dict(mode='unchanged' if skip else 'sdk_realtime' if requested is None else 'explicit',
        requested_class=None if skip else 5 if requested is None else requested,
        before=None,after=None,set_succeeded=False)
    handle=getattr(process,'_handle',None)
    if handle is None:
        result['error']='Owned child has no process handle'
        return False,result
    try:
        gdi=C.WinDLL('gdi32.dll',winmode=0x800) # LOAD_LIBRARY_SEARCH_SYSTEM32
    except OSError as exc:
        result['error']=str(exc)
        return False,result
    try:
        get_class=gdi.D3DKMTGetProcessSchedulingPriorityClass
        get_class.argtypes=[C.c_void_p,C.POINTER(C.c_int)]
        get_class.restype=C.c_int32
    except AttributeError:
        get_class=None
    def query():
        if get_class is None: return dict(supported=False)
        value=C.c_int(-1)
        status=int(get_class(int(handle),C.byref(value)))
        return dict(supported=True,status=status,priority_class=value.value if status==0 else None)
    result['before']=query()
    if not skip:
        try:
            if requested is None:
                # Preserve the original SDK call for the default baseline.
                result['set_succeeded']=bool(prioritize_gpu(process))
            else:
                set_class=gdi.D3DKMTSetProcessSchedulingPriorityClass
                set_class.argtypes=[C.c_void_p,C.c_int]
                set_class.restype=C.c_int32
                result['set_status']=int(set_class(int(handle),requested))
                result['set_succeeded']=result['set_status']==0
        except (AttributeError,OSError) as exc:
            result['set_error']=str(exc)
    result['after']=query()
    return result['set_succeeded'],result


def analyze(native,arrivals,frequency,started,warmup,seconds=None):
    errors=[]
    if len(native)!=len(arrivals):
        errors.append(f'Native/AVI frame count differs: {len(native)} != {len(arrivals)}')
    rows=[]
    for i,(record,arrival) in enumerate(zip(native,arrivals)):
        r=dict(record,arrival=arrival['qpc'],received_bytes=arrival['bytes'],
            avi_bytes=arrival['raw_bytes'])
        if r['index']!=i or r['frequency']!=frequency or r['output']!=0 or r['stream']!=0:
            errors.append(f'Invalid stream/index/clock at {i}')
        if i and r['sequence']<=native[i-1]['sequence']:
            errors.append(f'Non-increasing provenance ID at {i}')
        stamps=['sample','emit','filter_out','dequeue','encode_start','packet_ready','mux_start','mux_end']
        if any(r[key]<=0 for key in stamps) or any(r[b]<r[a]-1 for a,b in zip(stamps,stamps[1:])):
            errors.append(f'Invalid timestamp order at {i}')
        if r['result']<0:
            errors.append(f'Mux error {r["result"]} at {i}')
        if r['bytes']!=r['avi_bytes']:
            errors.append(f'Native/AVI access-unit size differs at {i}')
        # The consumer may observe pipe data before the producer's write API
        # returns. Do not require arrival >= mux_end or call it a network delay.
        if r['arrival'] < r['mux_start']-1:
            errors.append(f'Arrival precedes write start at {i}')
        r['warmup']=(r['arrival']-started)/frequency<warmup
        rows.append(r)
    selected=[r for r in rows if not r['warmup'] and
              (seconds is None or r['arrival']<=started+seconds*frequency)]
    unique=[]
    previous=None
    for r in selected:
        if r['present']>0 and r['present']!=previous:
            unique.append(r)
        previous=r['present']
    def delta(a,b,subset=selected):
        return distribution([(r[b]-r[a])*1000/frequency for r in subset if r[a]>0 and r[b]>0])
    def intervals(field,subset=selected):
        return distribution([(b[field]-a[field])*1000/frequency for a,b in zip(subset,subset[1:])])
    def fps(field,subset):
        span=(subset[-1][field]-subset[0][field])/frequency if len(subset)>1 else 0
        return (len(subset)-1)/span if span>0 else None
    host_gaps=[(b['arrival']-a['arrival'])*1000/frequency for a,b in zip(selected,selected[1:])]
    source_gaps=[(b['present']-a['present'])*1000/frequency for a,b in zip(unique,unique[1:])]
    bins=[]
    end=seconds if seconds is not None else (rows[-1]['arrival']-started)/frequency if rows else 0
    for second in range(math.ceil(warmup),math.floor(end)):
        window=[r for r in selected if second*frequency<=r['arrival']-started<(second+1)*frequency]
        bins.append(dict(start_seconds=second,frames=len(window),
            unique_present_values=len({r['present'] for r in window if r['present']>0}),
            encoded_mbps=sum(r['bytes'] for r in window)*8/1_000_000,
            sdk_payload_mbps=sum(r['received_bytes'] for r in window)*8/1_000_000))
    stages={f'{a}_to_{b}_ms':delta(a,b) for a,b in [
        ('sample','emit'),('acquire_start','acquire_end'),('emit','filter_out'),
        ('filter_out','dequeue'),('dequeue','encode_start'),('encode_start','packet_ready'),
        ('packet_ready','mux_start'),('mux_start','mux_end'),('sample','arrival'),('emit','arrival'),
        ('present','acquire_end')]}
    unknown=sum(r['present']<=0 for r in selected)
    repeated=len(selected)-unknown-len(unique)
    return dict(errors=errors[:30],frames=len(rows),measured_frames=len(selected),
        unique_present_values=len(unique), repeated_present_values=repeated,
        unknown_present_values=unknown,repeated_present_fraction=repeated/(len(selected)-unknown) if len(selected)>unknown else None,
        host_fps=fps('arrival',selected),unique_host_fps=fps('arrival',unique),
        observed_source_present_fps=fps('present',unique),
        host_gaps_over_15ms=sum(x>15 for x in host_gaps),
        unique_source_gaps_over_15ms=sum(x>15 for x in source_gaps),
        source_to_arrival_p99_ms=delta('present','arrival')['p99'] if selected and not unknown else None,
        one_second_host_output=bins,
        capture_sequence_gaps=sum(max(0,b['sequence']-a['sequence']-1) for a,b in zip(selected,selected[1:])),
        source_present_interval_ms=intervals('present',unique),
        capture_sample_interval_ms=intervals('sample'),packet_ready_interval_ms=intervals('packet_ready'),
        host_arrival_interval_ms=intervals('arrival'),
        source_age_all_frames_ms=delta('present','arrival'),
        source_age_unique_present_ms=delta('present','arrival',unique),
        source_to_sample_unique_ms=delta('present','sample',unique),
        stages=stages, records=rows)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ffmpeg',type=Path,default=ROOT/'work/frame-age-probe/build/ffmpeg.exe')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--adapter',type=int,default=0)
    p.add_argument('--output-index',type=int,default=1)
    p.add_argument('--seconds',type=float,default=20)
    p.add_argument('--warmup',type=float,default=3)
    p.add_argument('--fifo',action='store_true')
    p.add_argument('--defer-release',action='store_true')
    p.add_argument('--vp-speed',action='store_true')
    p.add_argument('--vp-rate',action='store_true')
    p.add_argument('--legacy-clock',action='store_true')
    p.add_argument('--mmcss',action='store_true')
    gpu_group=p.add_mutually_exclusive_group()
    gpu_group.add_argument('--no-gpu-priority',action='store_true')
    gpu_group.add_argument('--gpu-priority-class',type=int,choices=(2,3,4,5))
    p.add_argument('--synchronous',action='store_true')
    p.add_argument('--verify-pattern',action='store_true',help='At most 6 seconds of generated native pattern; decode marker offline, no video files')
    p.add_argument('--source-clock',action='store_true')
    p.add_argument('--source-guard-us',type=int,default=None)
    args=p.parse_args()
    if args.output.exists(): p.error('Choose a fresh output file')
    if not 0<=args.warmup<args.seconds<=120: p.error('Require 0<=warmup<seconds<=120')
    if args.verify_pattern and args.seconds>6:p.error('Generated-pattern identity checks are limited to 6 seconds')
    if args.source_guard_us is not None and (not args.source_clock or not 0<=args.source_guard_us<=5000):
        p.error('--source-guard-us requires --source-clock and range 0..5000')
    if args.source_clock and args.legacy_clock:p.error('--source-clock requires the precise clock')
    target=next((x for x in outputs() if x['adapter']==args.adapter and x['output']==args.output_index),None)
    if target is None: p.error('Requested DXGI output is not attached')
    if args.verify_pattern and (target.get('width'),target.get('height'))!=(1920,1080):
        p.error('Generated-pattern verification requires a native 1920x1080 source')
    display=next((x for x in inventory() if x['device']==target['device']),None)
    ffmpeg=args.ffmpeg.resolve(strict=True)
    try:available_options=native_source_options(ffmpeg)
    except (ValueError,OSError,subprocess.TimeoutExpired) as exc:p.error(str(exc))
    if 'frame_age_probe' not in available_options:p.error('Use an instrumented FFmpeg with frame_age_probe support')
    if args.source_clock and 'source_clock' not in available_options:p.error('This historical FFmpeg predates source_clock')
    if args.defer_release and 'defer_release' not in available_options:p.error('This instrumented build has no deferred-release candidate')
    command=frozen_baseline_command(ffmpeg,target,available_options)
    set_option(command,'-loglevel','info')
    if args.mmcss: command[1:1]=['-mmcss','1']
    if args.synchronous: set_option(command,'-async_encode','0')
    pos=command.index('-filter_complex')+1
    source,sep,filters=command[pos].partition(',')
    assert source.startswith('ddagrab=') and sep
    source+=':frame_age_probe=1'
    if args.source_clock:
        source=source.replace('source_clock=0','source_clock=1')
        if args.source_guard_us is not None:source=source.replace('source_guard_us=2000',f'source_guard_us={args.source_guard_us}')
    if args.defer_release: source=source.replace('defer_release=0','defer_release=1')
    if args.legacy_clock: source=source.replace('precise_clock=1','precise_clock=0').replace('acquire_timeout=0','acquire_timeout=-1')
    extra=('vp_usage=speed' if args.vp_speed else '')+(':' if args.vp_speed and args.vp_rate else '')+('vp_framerate=100/1' if args.vp_rate else '')
    if extra:
        filters=re.sub(r'(scale_d3d11=[^,;\[]+)',lambda m:m.group(1)+':'+extra,filters)
    command[pos]=source+','+filters
    if args.fifo:
        pos=command.index('-latest_frame');del command[pos:pos+2]
        set_option(command,'-fps_mode','cfr')
    freq=C.c_int64();assert KERNEL.QueryPerformanceFrequency(C.byref(freq));frequency=freq.value
    arrivals=[];reader,raw_sizes=measured_avi_reader();timed_out=False
    pattern_frames=[];pattern_bytes=0;pattern_error=None
    started=qpc()
    with tempfile.TemporaryFile() as log:
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=log,stdin=subprocess.PIPE,
            bufsize=0,creationflags=NO_WINDOW|ENCODER_PRIORITY)
        qos=configure_encoder_process(process)
        def stop():
            try:process.stdin.write(b'q\n');process.stdin.flush()
            except (OSError,ValueError):pass
        def kill():
            nonlocal timed_out
            if process.poll() is None:timed_out=True;process.kill()
        timer=threading.Timer(args.seconds,stop);watchdog=threading.Timer(args.seconds+15,kill)
        timer.start();watchdog.start();priority=False;priority_diagnostics=None;parse_error=None
        try:
            while data:=process.stdout.read(16384):
                for frame in reader.feed(data):
                    stamp=qpc()
                    if not arrivals:
                        priority,priority_diagnostics=gpu_priority_policy(process,args.gpu_priority_class,args.no_gpu_priority)
                    arrivals.append(dict(qpc=stamp,bytes=len(frame),raw_bytes=raw_sizes.popleft()))
                    if args.verify_pattern and pattern_error is None:
                        if len(pattern_frames)>=800 or pattern_bytes+len(frame)>48*1024*1024:
                            pattern_error='Generated-pattern memory bound exceeded'
                            stop()
                        else:
                            pattern_frames.append(frame)
                            pattern_bytes+=len(frame)
            process.wait(timeout=5)
            try:reader.finish()
            except ValueError as exc:parse_error=str(exc)
            log.seek(0);diagnostics=log.read().decode(errors='replace')
        finally:
            timer.cancel();watchdog.cancel()
            if process.poll() is None:process.kill();process.wait()
            process.stdin.close();process.stdout.close()
    native=[];header=None;end=None;source_clock_summary=None
    for line in diagnostics.splitlines():
        if 'DDA_SOURCE_CLOCK ' in line:
            source_clock_summary={k:int(v) for k,v in re.findall(r'(\w+)=(-?\d+)',line.partition('DDA_SOURCE_CLOCK ')[2])}
        if line.startswith(('G2AGE_HEADER ','G2AGE_RECORD ','G2AGE_END ')):
            record={k:int(v) for k,v in re.findall(r'(\w+)=(-?\d+)',line)}
            if line.startswith('G2AGE_RECORD '):native.append(record)
            elif line.startswith('G2AGE_HEADER '):header=record
            else:end=record
    summary=analyze(native,arrivals,frequency,started,args.warmup,args.seconds)
    if (not header or not end or header.get('dropped') or
        header.get('records')!=len(native) or end.get('records')!=len(native)):
        summary['errors'].append('Missing/truncated/bounded-out native provenance log')
    if parse_error:summary['errors'].append(parse_error)
    identity=None
    if args.verify_pattern:
        if pattern_error or summary['errors']:
            identity=dict(status='failed',errors=[pattern_error or 'Invalid host provenance; no identity matching attempted'])
        else:
            from pattern_identity import verify
            try:identity=verify(ffmpeg,pattern_frames,summary['records'],frequency,started+int(args.seconds*frequency))
            except (ValueError,OSError,subprocess.TimeoutExpired) as exc:
                identity=dict(status='failed',errors=[str(exc)])
        if identity['status']!='completed':summary['errors'].append('Generated-pattern identity verification failed')
    pattern_frames.clear()
    result=dict(measurement='DDA desktop-present/capture-to-host-picture age; not optical latency',
        status='completed' if process.returncode==0 and not timed_out and native and not summary['errors'] else 'failed',
        source=target,source_refresh_hz=display['hz'] if display else None,
        expected_source_note='Static desktop last-present age is not queue latency; use moving content',
        frequency=frequency,start_qpc=started,seconds=args.seconds,warmup_seconds=args.warmup,
        source_capture=True,usb_access=False,video_saved=False,command=command,
        baseline_command_template_sha256=hashlib.sha256(BASELINE_TEMPLATE.read_bytes()).hexdigest(),
        ffmpeg_sha256=hashlib.sha256(ffmpeg.read_bytes()).hexdigest(),qos=qos,gpu_priority=priority,
        gpu_priority_diagnostics=priority_diagnostics,
        pattern_identity=identity,
        source_clock_summary=source_clock_summary,
        returncode=process.returncode,timed_out=timed_out,header=header,**summary)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    args.output.with_suffix('.log').write_text(diagnostics,encoding='utf-8')
    printable={k:v for k,v in result.items() if k not in ('records','command')}
    if identity:printable['pattern_identity']={k:v for k,v in identity.items() if k!='records'}
    print(json.dumps(printable,ensure_ascii=False,indent=2))
    return 0 if result['status']=='completed' else 1


if __name__=='__main__':raise SystemExit(main())
