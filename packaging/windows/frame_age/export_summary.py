"""Export compact public timing evidence from private local research logs.

Only an explicit metric whitelist leaves the evidence directory. Absolute QPC,
process/window handles, device identities, original command paths and raw
per-frame records remain private. No GPU, capture or USB operation is performed.
"""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(path,data,correlation):
    fields=('status','seconds','warmup_seconds','frames','measured_frames','host_fps',
        'unique_host_fps','observed_source_present_fps','unique_present_values',
        'repeated_present_values','repeated_present_fraction','unknown_present_values',
        'capture_sequence_gaps','host_gaps_over_15ms','unique_source_gaps_over_15ms',
        'host_arrival_interval_ms','capture_sample_interval_ms','source_present_interval_ms',
        'source_age_all_frames_ms','source_age_unique_present_ms','source_to_sample_unique_ms',
        'stages','source_clock_summary','one_second_host_output')
    result={k:data[k] for k in fields if k in data}
    result.update(raw_file_sha256=digest(path),ffmpeg_sha256=data['ffmpeg_sha256'],
        video_saved=False,optical_latency='not measured',validation_errors=len(data['errors']))
    if data.get('analysis_revision'):
        result['summary_revision']=data['analysis_revision']['version']
        result['original_file_sha256']=data['analysis_revision']['original_sha256']
    graph=data['command'][data['command'].index('-filter_complex')+1].partition(',')[0]
    options=dict(pair.split('=',1) for pair in graph[len('ddagrab='):].split(':'))
    result['candidate']=dict(source_clock=int(options.get('source_clock',0)),
        source_guard_us=int(options.get('source_guard_us',2000)),
        defer_release=int(options.get('defer_release',0)),mmcss='-mmcss' in data['command'],
        async_encode=int(data['command'][data['command'].index('-async_encode')+1]))
    priority=data.get('gpu_priority_diagnostics')
    if priority:
        result['gpu_priority']=dict(mode=priority['mode'],requested=priority['requested_class'],
            before=(priority.get('before') or {}).get('priority_class'),
            after=(priority.get('after') or {}).get('priority_class'),
            set_succeeded=priority['set_succeeded'])
    else:
        result['gpu_priority']=dict(mode='historical SDK call' if data['gpu_priority'] else 'not set',
            sdk_call_reported_success=data['gpu_priority'])
    rows=[r for r in data['records'] if not r['warmup'] and
          r['arrival']<=data['start_qpc']+data['seconds']*data['frequency']]
    gaps=[(b['arrival']-a['arrival'])*1000/data['frequency'] for a,b in zip(rows,rows[1:])]
    result['host_interval_within_one_percent']=sum(abs(g-10)<=.1 for g in gaps)
    result['host_interval_one_percent_target_met']=bool(gaps) and all(abs(g-10)<=.1 for g in gaps)
    windows=data.get('one_second_host_output',[])
    result['encoded_bitrate_one_percent_target_met']=bool(windows) and all(abs(w['encoded_mbps']-20)<=.2 for w in windows)
    result['maximum_sdk_frame_bytes']=max((r['received_bytes'] for r in data['records']),default=0)
    result['sdk_frames_over_56000_bytes']=sum(r['received_bytes']>56000 for r in data['records'])
    if correlation:
        keep=('renderer_covers_window','renderer_frames','renderer_fps','renderer_gaps_over_15ms',
            'statistics_reported_present_rate','present_start_interval_ms','source_gaps_over_15ms',
            'source_gaps_overlapping_renderer_gaps','exact_generated_pattern_identity')
        result['source_correlation']={k:correlation[k] for k in keep if k in correlation}
    identity=data.get('pattern_identity')
    if identity:
        keep=('status','decoded_frames','measured_frames','unique_frame_ids','repeated_frame_ids',
            'skipped_renderer_ids','render_to_os_present_ms','render_to_capture_sample_ms',
            'render_to_host_arrival_ms','stored_video_artifacts')
        result['decoded_pattern_identity']={k:identity[k] for k in keep if k in identity}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=args.evidence_dir.resolve()
    if args.output.exists():parser.error('Choose a fresh output path')
    paths=[]
    for folder in ('motion-matrix-01','priority-matrix-02','phase-matrix-03','phase-matrix-04-v2','texture-confirmation-05'):
        paths.extend(sorted((root/folder).glob('*.json')))
    paths.extend(root/name for name in ('phase-v2-long-90.json','texture-identity-smoke-summary-v2.json','phase-v2-identity-final.json'))
    correlations={}
    for path in [*root.glob('renderer-correlation-*.json'),root/'texture-identity-exact-join-v2.json']:
        if path.exists():
            for run in json.loads(path.read_text(encoding='utf-8'))['runs']:
                correlations[str(Path(run['path']).resolve()).casefold()]=run
    runs=[]
    for path in paths:
        data=json.loads(path.read_text(encoding='utf-8'))
        runs.append(dict(name=path.relative_to(root).as_posix(),**summarize(path,data,
            correlations.get(str(path.resolve()).casefold()))))
    output=dict(schema=1,version='0.2.4',scope='Host-side generated-motion research; no optical latency measurement',
        configuration='1920x1080, 100 fps, 20 Mbps target, NVIDIA NVENC P4',
        hardware='NVIDIA GeForce RTX 4060 Laptop GPU; extended output already configured at 100 Hz',
        privacy='Public numeric summaries only; original traces/identifiers remain in ignored local work storage',
        caveats=['Only completed observed windows are characterized; zero observed repeats is not a universal guarantee.',
            'Renderer/source gaps are correlated by time window, not exact image identity except in explicit marker tests.',
            'Stable media PTS are not evidence of stable output intervals or picture freshness.',
            'The 1% host-interval and encoded-bitrate targets are reported directly, not inferred from nominal settings.'],runs=runs)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as handle:json.dump(output,handle,indent=2);handle.write('\n')
    print(f'Exported {len(runs)} sanitized run summaries')


if __name__=='__main__':main()
