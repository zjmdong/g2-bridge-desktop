"""Publish whitelisted release USB/codec metrics, never identities or raw traces."""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import time


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def extent(values):
    if not values:return None
    average=sum(values)/len(values)
    return dict(count=len(values),mean=average,min=min(values),max=max(values),
        maximum_deviation_from_mean_percent=max(abs(v-average) for v in values)/average*100 if average else None)


def source_context(renderer,data):
    # CPython on Windows uses raw QPC for perf_counter_ns. Check that clock
    # relationship here before correlating saved time windows from this boot.
    kernel=C.WinDLL('kernel32')
    for name in ('QueryPerformanceCounter','QueryPerformanceFrequency'):
        getattr(kernel,name).argtypes=[C.POINTER(C.c_int64)]
        getattr(kernel,name).restype=C.c_int
    f=C.c_int64();a=C.c_int64();b=C.c_int64()
    kernel.QueryPerformanceFrequency(C.byref(f))
    kernel.QueryPerformanceCounter(C.byref(a));stamp=time.perf_counter_ns();kernel.QueryPerformanceCounter(C.byref(b))
    mapped=stamp*f.value//1_000_000_000
    if f.value!=renderer['frequency'] or not a.value-1<=mapped<=b.value+1:
        return dict(available=False,reason='Perf-counter/QPC clock relationship was not established')
    video=[r for r in data['records'] if r['kind']=='video' and r['completed']]
    begin=(video[0]['after_ns']+int(data['warmup_seconds']*1e9))*f.value//1_000_000_000
    end=video[-1]['after_ns']*f.value//1_000_000_000
    rows=[r for r in renderer['records'] if begin<=r['render_start']<=end]
    gaps=[(b['render_start']-a['render_start'])*1000/f.value for a,b in zip(rows,rows[1:])]
    return dict(available=True,scope='Same-session QPC window correlation only, not exact picture identity',
        renderer_frames=len(rows),renderer_fps=1000/(sum(gaps)/len(gaps)) if gaps else None,
        renderer_gaps_over_15ms=sum(v>15 for v in gaps),renderer_maximum_interval_ms=max(gaps) if gaps else None,
        source_covers_window=renderer['start_qpc']<=begin and renderer['finish_qpc']>=end)


def usb_run(path,name,renderer=None):
    data=json.loads(path.read_text(encoding='utf-8'))
    intervals=data['steady_completion_interval_ms']
    bins=data['steady_full_second_bins']
    stream=next(e for e in data['events'] if e['event']=='streaming')
    stats=[e for e in data['events'] if e['event']=='stats']
    return dict(name=name,raw_file_sha256=digest(path),ffmpeg_sha256=data['ffmpeg_sha256'],
        scope=data['measurement_scope'],optical_latency='not measured',settings=data['settings'],
        source_dimensions=[data['source']['width'],data['source']['height']],
        duration_requested_seconds=data['duration_requested_seconds'],warmup_seconds=data['warmup_seconds'],
        completed_video_count=data['completed_video_count'],steady_video_count=data['steady_video_count'],
        failed_write_count=data['failed_write_count'],failure_reported=data['failure'] is not None,
        cleanup_errors_count=len(data['cleanup_errors']),all_transports_closed=all(data['transports_closed']),
        records_dropped=data['records_dropped'],gpu_priority_class=stream['gpu_priority_class'],
        gpu_priority_api_applied=stream['gpu_priority_applied'],
        completion_interval_ms=intervals,derived_completion_fps=1000/intervals['mean'],
        usb_api_write_ms=data['steady_usb_write_ms'],
        intervals_outside_one_percent=data['steady_intervals_outside_10ms_plus_minus_1pct'],
        interval_one_percent_target_met=data['steady_intervals_outside_10ms_plus_minus_1pct']==0,
        one_second_wire_mbps=extent([b['wire_mbps'] for b in bins]),
        one_second_encoded_mbps_estimate=extent([b['encoded_mbps_estimate'] for b in bins]),
        one_second_frame_counts=extent([b['frames'] for b in bins]),
        encoded_bytes_method=data['encoded_bytes_method'],
        maximum_reported_oversize_frames=max((s['oversize_frames'] for s in stats),default=0),
        maximum_reported_queue_ms_p95=max((s['queue_ms_p95'] for s in stats),default=0),
        maximum_reported_frame_bytes=max((s['frame_bytes_max'] for s in stats),default=0),
        source_context=source_context(renderer,data) if renderer else None)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();root=args.evidence_dir
    if args.output.exists():p.error('Choose a fresh output path')
    renderer=json.loads((root/'renderer-release-usb-05.json').read_text(encoding='utf-8'))
    gpu=json.loads((root/'release-gpu-pixels.json').read_text(encoding='utf-8'))
    modes=json.loads((root/'release-encoder-modes.json').read_text(encoding='utf-8'))
    binaries=json.loads((root/'release-binaries.json').read_text(encoding='utf-8'))
    output=dict(schema=1,version='0.2.4',scope='Actual release binary; USB completion is host API acceptance, not goggles presentation',
        release_binaries=binaries,
        usb=[usb_run(root/'usb-release-phase3-60.json','extended-generated-texture-60s',renderer),
             usb_run(root/'usb-release-primary-20.json','ultrawide-primary-desktop-20s')],
        correctness=dict(generated_pixels=dict(status=gpu['status'],raw_file_sha256=digest(root/'release-gpu-pixels.json'),
                frame_counts=gpu['validation_frame_counts'],raw_component_tolerance=gpu['raw_component_tolerance'],
                decoded_component_tolerance=gpu['decoded_component_tolerance']),
            codec_modes=dict(passed=modes['passed'],raw_file_sha256=digest(root/'release-encoder-modes.json'),
                modes=len(modes['modes']),encoded_frames=sum(m['frames'] for m in modes['modes']),
                decoded_frames=sum(m['decoded_frames'] for m in modes['modes']),
                maximum_frame_bytes=max(m['maximum_frame_bytes'] for m in modes['modes']))),
        caveats=['Host write completion does not establish USB wire timing, goggles decoding or optical presentation.',
            'The primary-desktop scene is not the generated texture; its low coded bitrate cannot be used as a quality comparison.',
            'Windows deliberately terminates the SDK encoder on stop; teardown status is assessed through explicit failure/cleanup fields.',
            'No source identity, process handle, device address, absolute counter or private filesystem path is published.'])
    with args.output.open('x',encoding='utf-8') as handle:json.dump(output,handle,indent=2);handle.write('\n')
    for run in output['usb']:print(run['name'],run['derived_completion_fps'],run['one_second_encoded_mbps_estimate'])


if __name__=='__main__':main()
