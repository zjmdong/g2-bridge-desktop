"""Align completed renderer and host-probe logs by QPC window, without video.

This correlates time windows, not pixel/frame identities. Present calls and
DXGI statistics cannot prove which marker ID appears in a captured picture.
"""
import argparse
from bisect import bisect_left, bisect_right
import json
from pathlib import Path


def distribution(values):
    data=sorted(values)
    if not data:return None
    return dict(count=len(data),mean=sum(data)/len(data),**{
        name:data[int((len(data)-1)*p)] for name,p in
        [('min',0),('p01',.01),('p50',.5),('p95',.95),('p99',.99),('max',1)]})


def correlate(source,host):
    frequency=source['frequency']
    if host['frequency']!=frequency:raise ValueError('QPC frequency differs')
    if source.get('clock')!='QueryPerformanceCounter':raise ValueError('Renderer has no raw QPC clock')
    begin=host['start_qpc']+int(host['warmup_seconds']*frequency)
    end=host['start_qpc']+int(host['seconds']*frequency)
    rows=[r for r in source['records'] if begin<=r['render_start']<=end]
    native=[r for r in host['records'] if begin<=r['arrival']<=end]
    unique=[]
    for r in native:
        if r['present']>0 and (not unique or r['present']!=unique[-1]['present']):unique.append(r)
    def intervals(field):
        return distribution([(b[field]-a[field])*1000/frequency for a,b in zip(rows,rows[1:])])
    def stage(a,b):return distribution([(r[b]-r[a])*1000/frequency for r in rows])
    source_gaps=[(a['present'],b['present']) for a,b in zip(unique,unique[1:]) if b['present']-a['present']>.015*frequency]
    present_starts=[r['present_start'] for r in source['records']]
    render_gaps=[(a['present_start'],b['present_start']) for a,b in zip(source['records'],source['records'][1:]) if b['present_start']-a['present_start']>.015*frequency]
    related=[]
    for start,stop in source_gaps:
        calls=bisect_right(present_starts,stop)-bisect_right(present_starts,start)
        overlaps=sum(a<stop and b>start for a,b in render_gaps)
        related.append(dict(source_gap_ms=(stop-start)*1000/frequency,
            renderer_present_calls_in_same_interval=calls,
            overlapping_renderer_gaps_over_15ms=overlaps))
    stats=[r for r in rows if r['statistics_valid'] and r['statistics_present_count']>0]
    render_span=(rows[-1]['render_start']-rows[0]['render_start'])/frequency if len(rows)>1 else 0
    stats_rate=None
    if len(stats)>1:
        span=(stats[-1]['stats_end']-stats[0]['stats_end'])/frequency
        if span>0:stats_rate=(stats[-1]['statistics_present_count']-stats[0]['statistics_present_count'])/span
    # A nearby application's Present is only a timing relationship. The OS can
    # compose/present a different queued picture; do not label it a pixel age.
    previous_present_offsets=[]
    for r in native:
        i=bisect_right(present_starts,r['sample'])-1
        if i>=0:previous_present_offsets.append((r['sample']-present_starts[i])*1000/frequency)
    exact=None
    identity=host.get('pattern_identity')
    if identity and identity.get('status')=='completed':
        render_by_id={r['frame']:r for r in source['records']}
        checked=identity['records']
        unmatched=[]
        for marker in checked:
            candidate=render_by_id.get(marker['frame_id'])
            if candidate is None or candidate['render_start']!=marker['render_qpc']:
                unmatched.append(marker['index'])
        exact=dict(scope='Exact decoded marker ID/QPC tuple found in renderer log',
            count=len(checked),matched=len(checked)-len(unmatched),unmatched_indices=unmatched)
    return dict(scope='QPC-window correlation, not exact frame ID or optical measurement',
        renderer_covers_window=source['start_qpc']<=begin and source['finish_qpc']>=end,
        renderer_error=source['error'],renderer_frames=len(rows),
        exact_generated_pattern_identity=exact,
        renderer_fps=(len(rows)-1)/render_span if render_span else None,
        render_start_interval_ms=intervals('render_start'),
        present_start_interval_ms=intervals('present_start'),
        present_end_interval_ms=intervals('present_end'),
        render_cpu_submit_ms=stage('render_start','present_start'),
        present_api_block_ms=stage('present_start','present_end'),
        frame_statistics_query_ms=stage('present_end','stats_end'),
        statistics_valid_samples=len(stats),statistics_reported_present_rate=stats_rate,
        renderer_gaps_over_15ms=sum(b['present_start']-a['present_start']>.015*frequency for a,b in zip(rows,rows[1:])),
        sample_after_nearest_earlier_renderer_present_call_ms=distribution(previous_present_offsets),
        host_status=host['status'],host_frames=len(native),host_unique=len(unique),
        host_repeated_fraction=host['repeated_present_fraction'],
        source_gaps_over_15ms=len(source_gaps),
        source_gaps_overlapping_renderer_gaps=sum(r['overlapping_renderer_gaps_over_15ms']>0 for r in related),
        source_gap_details=related)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--renderer',type=Path,required=True)
    parser.add_argument('--runs',type=Path,nargs='+',required=True,help='Completed JSON files or directories')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('Choose a fresh output path')
    source=json.loads(args.renderer.read_text(encoding='utf-8'))
    paths=[]
    for entry in args.runs:paths.extend(sorted(entry.glob('*.json')) if entry.is_dir() else [entry])
    results=[]
    for path in paths:
        host=json.loads(path.read_text(encoding='utf-8'))
        results.append(dict(path=str(path.resolve()),**correlate(source,host)))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(dict(renderer=str(args.renderer.resolve()),runs=results),indent=2)+'\n',encoding='utf-8')
    for path,result in zip(paths,results):
        print(json.dumps(dict(run=path.name,**{k:result[k] for k in (
            'renderer_covers_window','renderer_fps','renderer_gaps_over_15ms',
            'source_gaps_over_15ms','source_gaps_overlapping_renderer_gaps','host_repeated_fraction')})))


if __name__=='__main__':main()
