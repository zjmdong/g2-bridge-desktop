"""Offline compact identity/renderer comparison; never runs capture or GPU code."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def dist(values):
    x=sorted(values)
    if not x:return None
    return dict(count=len(x),mean=sum(x)/len(x),**{k:x[int((len(x)-1)*p)]
        for k,p in [('min',0),('p01',.01),('p50',.5),('p95',.95),('p99',.99),('max',1)]})


def read(path):
    raw=path.read_bytes()
    return json.loads(raw.decode('utf-8')),dict(file=path.name,sha256=hashlib.sha256(raw).hexdigest())


def summarize(host_path,renderer=None,renderer_provenance=None):
    host,provenance=read(host_path)
    f=host['frequency'];start=host['start_qpc'];begin=start+host['warmup_seconds']*f;end=start+host['seconds']*f
    identity=host.get('pattern_identity') or {}
    records=identity.get('records',[])
    def arrival(row):return row.get('arrival_qpc',row.get('arrival'))
    selected=[r for r in records if arrival(r) is not None and begin<=arrival(r)<=end]
    unique=[r for i,r in enumerate(selected) if not i or r['frame_id']!=selected[i-1]['frame_id']]
    gaps=[(arrival(b)-arrival(a))*1000/f for a,b in zip(selected,selected[1:])]
    ids=[r['frame_id'] for r in unique]
    increments=Counter(b['frame_id']-a['frame_id'] for a,b in zip(selected,selected[1:]))
    span=(arrival(selected[-1])-arrival(selected[0]))/f if len(selected)>1 else 0
    result=dict(source_report=provenance,status=host['status'],identity_status=identity.get('status'),
        identity_errors=identity.get('errors',[]),ffmpeg_sha256=host.get('ffmpeg_sha256'),
        command_sha256=host.get('command_sha256'),settings=host.get('settings'),
        native_probe_metadata=host.get('native_probe_metadata','records' in host),
        measured_frames=len(selected),unique_source_ids=len(unique),
        repeated_source_ids=len(selected)-len(unique),
        skipped_source_ids=sum(max(0,b-a-1) for a,b in zip(ids,ids[1:])),
        identity_increment_counts=dict(sorted(increments.items())),
        measured_au_fps=(len(selected)-1)/span if span else None,
        au_interval_ms=dist(gaps),intervals_over15ms=sum(v>15 for v in gaps),
        source_render_to_host_ms=dist([(arrival(r)-r['render_qpc'])*1000/f for r in selected]),
        unique_source_render_to_host_ms=dist([(arrival(r)-r['render_qpc'])*1000/f for r in unique]),
        maximum_frame_bytes=host.get('max_frame_bytes',max((r.get('bytes',0) for r in host.get('records',[])),default=0)),
        oversize_frames=host.get('oversize_frames'),
        repeated_native_present_values=host.get('repeated_present_values'),
        native_capture_sequence_gaps=host.get('capture_sequence_gaps'),
        native_source_clock=host.get('source_clock_summary'),
        native_summary_lines=host.get('native_summary_lines'),
        source_renderer=None)
    if renderer is None:return result
    if renderer['frequency']!=f:raise ValueError('Renderer/host QPC frequency differs')
    by_id={r['frame']:r for r in renderer['records']}
    if len(by_id)!=len(renderer['records']):raise ValueError('Duplicate renderer IDs')
    exact=[m for m in records if m['frame_id'] in by_id and by_id[m['frame_id']]['render_start']==m['render_qpc']]
    unmatched=[m['index'] for m in records if m['frame_id'] not in by_id or by_id[m['frame_id']]['render_start']!=m['render_qpc']]
    source=[r for r in renderer['records'] if begin<=r['render_start']<=end]
    source_intervals=[(b['render_start']-a['render_start'])*1000/f for a,b in zip(source,source[1:])]
    source_span=(source[-1]['render_start']-source[0]['render_start'])/f if len(source)>1 else 0
    missing=[]
    for left,right in zip(ids,ids[1:]):missing.extend(range(left+1,right))
    sampled_present_counts={r['statistics_present_count'] for r in renderer['records']
        if r.get('statistics_valid') and r['statistics_present_count']>0}
    source_id_bounds=(ids[0],ids[-1]) if ids else None
    missing_existing=[i for i in missing if i in by_id]
    observed_presented=[i for i in missing_existing if by_id[i]['last_present_count'] in sampled_present_counts]
    # Presentation statistics are sampled and can skip counter values. Lack of
    # an observed counter is not evidence that the compositor dropped a frame.
    source_details=dict(source_report=renderer_provenance,
        renderer_covers_host_window=renderer['start_qpc']<=begin and renderer['finish_qpc']>=end,
        renderer_error=renderer.get('error'),nominal_display_hz=renderer.get('display_refresh_hz'),
        source_swapchain=renderer.get('swapchain'),source_frames_in_host_window=len(source),
        actual_render_submit_fps=(len(source)-1)/source_span if source_span else None,
        render_interval_ms=dist(source_intervals),source_intervals_over15ms=sum(v>15 for v in source_intervals),
        excess_nominal_source_slots=sum(max(0,round(v/10)-1) for v in source_intervals),
        source_wait_ms=dist([(r['wait_end']-r['wait_start'])*1000/f for r in source]),
        exact_marker_tuples_checked=len(records),exact_marker_tuples_matched=len(exact),
        unmatched_marker_indices=unmatched[:30],unmatched_marker_count=len(unmatched),
        measured_marker_source_id_bounds=source_id_bounds,
        produced_ids_absent_between_received_markers=len(missing_existing),
        absent_ids_observed_in_DXGI_present_statistics=len(observed_presented),
        absent_ids_not_observed_in_sampled_statistics=len(missing_existing)-len(observed_presented),
        absent_produced_id_examples=missing_existing[:20],
        classification_limit='A generated ID absent from encoded output was lost between render submission and host AU. Present statistics narrow some misses but cannot isolate DWM, DDA readiness, mailbox admission or encoder without additional provenance. Source intervals>15ms separately measure irregular source submission; no optical claims.')
    result['source_renderer']=source_details
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs',type=Path,nargs='+',required=True)
    p.add_argument('--renderer',type=Path)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():p.error('Choose fresh summary output')
    renderer,provenance=read(args.renderer) if args.renderer else (None,None)
    runs=[summarize(path,renderer,provenance) for path in args.runs]
    report=dict(schema=1,scope='Compact offline production/research identity summaries; no capture or GPU activity',
        helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        age_scope='Exact decoded source render-start to host AU arrival; not capture-to-photon latency',
        caveats=['Nominal100Hz display mode does not establish100unique source pictures persecond.',
            'Statistics of native LastPresentTime can differ from actual generated marker identity.',
            'Produced-but-absent IDs must not automatically be called capture drops.',
            'All decoded markers including drain are exactly matched; summaries exclude warmup/drain.'],runs=runs)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    for r in runs:
        source=r['source_renderer'] or {}
        print(json.dumps(dict(file=r['source_report']['file'],status=r['status'],
            frames=r['measured_frames'],unique=r['unique_source_ids'],repeats=r['repeated_source_ids'],
            skipped_ids=r['skipped_source_ids'],au_p99_ms=(r['au_interval_ms'] or {}).get('p99'),
            au_max_ms=(r['au_interval_ms'] or {}).get('max'),age_p50_ms=(r['source_render_to_host_ms'] or {}).get('p50'),
            renderer_fps=source.get('actual_render_submit_fps'),source_gaps=source.get('source_intervals_over15ms'),
            unmatched=source.get('unmatched_marker_count'),produced_absent=source.get('produced_ids_absent_between_received_markers'),
            absent_but_observed_presented=source.get('absent_ids_observed_in_DXGI_present_statistics'))))


if __name__=='__main__':main()
