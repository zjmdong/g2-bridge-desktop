"""Optional bounded USB timing experiment: complete AU arrival vs host writes.

No live decode, per-frame disk I/O, sleeps, queue changes or USB protocol changes.
Only --run starts the underlying production USB tool. Optional retention/decode
requires an explicitly supplied synthetic extended-display source.
"""
from __future__ import annotations
import argparse
from array import array
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
import measure_usb_host as bench
import goggles_bridge.engine as engine

CAPACITY = 20000
MAX_AUS = 6500
MAX_BYTES = 256 * 1024 * 1024


class ArrivalSamples:
    def __init__(self, retain=False):
        self.time = array('Q', [0]) * CAPACITY
        self.length = array('I', [0]) * CAPACITY
        self.batch = array('I', [0]) * CAPACITY
        self.parser = array('I', [0]) * CAPACITY
        self.count = self.overflow = self.batches = self.parsers = 0
        self.retain = retain
        self.frames = [None] * MAX_AUS if retain else None
        self.retained_count = self.retained_bytes = self.retention_overflow = 0

    def feed_result(self, packets, parser):
        if not packets:
            return
        now = time.perf_counter_ns()
        batch = self.batches
        self.batches += 1
        for frame in packets:
            i = self.count
            if i >= CAPACITY:
                self.overflow += 1
                continue
            self.time[i], self.length[i] = now, len(frame)
            self.batch[i], self.parser[i] = batch, parser
            self.count = i + 1
            if self.retain:
                if self.retained_count < MAX_AUS and self.retained_bytes + len(frame) <= MAX_BYTES:
                    # Keep the existing immutable bytes object, never copy it.
                    self.frames[self.retained_count] = frame
                    self.retained_count += 1
                    self.retained_bytes += len(frame)
                else:
                    self.retention_overflow += 1


def instrumented_parser(samples):
    original = engine.AviPacketStream

    class ArrivalParser(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.timing_parser = samples.parsers
            samples.parsers += 1

        def feed(self, data):
            packets = super().feed(data)
            samples.feed_result(packets, self.timing_parser)
            return packets
    return ArrivalParser


def describe(values):
    result = bench.describe(values)
    if values:
        result['over15ms'] = sum(v > 15 for v in values)
    return result


def correlate(samples, host):
    writes = [r for r in host['records'] if r['kind'] == 'video']
    errors = []
    if samples.overflow:
        errors.append('Arrival sample capacity exceeded')
    if samples.parsers != 1:
        errors.append('Requires exactly one encoder parser; no cross-restart alignment')
    if any(r['event'] in ('encoder_restart', 'oversize_frame') for r in host.get('events', [])):
        errors.append('SDK discarded/restarted encoded references; alignment deliberately unavailable')
    if any(samples.length[i] > engine.MAX_FRAME_BYTES for i in range(samples.count)):
        errors.append('Oversize AU may have been discarded; alignment deliberately unavailable')
    if host.get('events_dropped') or host.get('records_dropped'):
        errors.append('Host instrumentation overflow prevents strict alignment')
    if len(writes) > samples.count:
        errors.append('More video writes than complete AUs')
    for i, w in enumerate(writes[:samples.count]):
        if samples.length[i] != w['encoded_bytes_estimate']:
            errors.append(f'AU/write length mismatch at sequence {i}')
            break
        if samples.time[i] > w['before_ns']:
            errors.append(f'Write precedes matched AU arrival at sequence {i}')
            break
    # Current SDK sends every nonoversize AU after ready, unless an encoder
    # restart initiates resync. With those branches excluded and exact prefix
    # lengths/times validated, only end-of-run queued arrivals may be unwritten.
    # Do not search forward by size: equal sizes cannot establish identity.
    trailing = samples.count-len(writes)
    if trailing > 0 and writes and samples.time[len(writes)] < samples.time[len(writes)-1]:
        errors.append('Unwritten tail is not chronological')
    matched = []
    if not errors:
        for i, w in enumerate(writes):
            matched.append(dict(sequence=i, arrival_ns=samples.time[i],
                feed_batch=samples.batch[i], encoded_bytes=samples.length[i],
                write_before_ns=w['before_ns'], write_after_ns=w['after_ns'],
                completed=w['completed'], arrival_to_write_begin_ms=(w['before_ns']-samples.time[i])/1e6,
                usb_write_ms=w['duration_ms']))
    first_completed = next((w['after_ns'] for w in writes if w['completed']), None)
    cutoff = first_completed + round(host['warmup_seconds']*1e9) if first_completed else 0
    steady = [r for r in matched if r['write_before_ns'] >= cutoff and r['completed']]
    def intervals(key):
        return [(b[key]-a[key])/1e6 for a,b in zip(steady,steady[1:])]
    arrival_rows = [dict(sequence=i, arrival_ns=samples.time[i], encoded_bytes=samples.length[i],
                         feed_batch=samples.batch[i], parser=samples.parser[i]) for i in range(samples.count)]
    return dict(status='matched' if not errors else 'unmatched', errors=errors,
        matching_policy='Single parser, no restart/resync/oversize, exact sequential prefix lengths and causal timestamps; never search or force-match skipped frames',
        clock='Python perf_counter_ns, Windows QPC-derived nanoseconds; same clock as transport writes',
        arrival_definition='Timestamp immediately after AviPacketStream.feed returns complete AUs; includes native stdout/OS read/parser delay, not native encode completion',
        batch_note='AUs returned by the same feed call share one arrival timestamp; preexisting reader batching is retained',
        gap_definition='arrival_to_write_begin includes SDK queue/control-loop work and PC video packetization; it does not isolate these two components',
        parser_count=samples.parsers, arrival_count=samples.count, write_count=len(writes),
        unmatched_shutdown_tail_count=max(trailing, 0), arrival_overflow=samples.overflow,
        matched_count=len(matched), steady_count=len(steady),
        steady_arrival_interval_ms=describe(intervals('arrival_ns')),
        steady_send_begin_interval_ms=describe(intervals('write_before_ns')),
        steady_completion_interval_ms=describe(intervals('write_after_ns')),
        steady_arrival_to_write_begin_ms=describe([r['arrival_to_write_begin_ms'] for r in steady]),
        steady_usb_write_ms=describe([r['usb_write_ms'] for r in steady]),
        arrival_records=arrival_rows, matched_records=matched)


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--decode-synthetic-extended', action='store_true')
    extra, remaining = parser.parse_known_args(argv)
    args = bench.arguments(remaining)
    if not args.run:
        print(json.dumps(dict(dry_run=True, source=args.source, output=str(args.output),
            next='Add --run for real USB; optional --decode-synthetic-extended retains only a manually provided 1920x1080/100Hz synthetic source in bounded RAM'), indent=2))
        return 0
    if extra.decode_synthetic_extended:
        from desktop_app.dxgi import outputs
        from desktop_app.displays import inventory
        out = next((r for r in outputs() if r['adapter']==args.adapter and r['output']==args.source), None)
        display = next((r for r in inventory() if out and r['device']==out['device']), None)
        if not out or not display or display['primary'] or not display['active'] or display['hz']!=100 or (out['width'],out['height'])!=(1920,1080):
            raise ValueError('Explicit synthetic decode requires an already active nonprimary 1920x1080/100Hz source; no display was changed')
    final_output = args.output
    host_output = final_output.with_name(final_output.stem+'-host.json')
    if host_output.exists():
        raise FileExistsError('Choose a new output: companion host report already exists')
    args.output = host_output
    samples = ArrivalSamples(extra.decode_synthetic_extended)
    with patch.object(engine, 'AviPacketStream', instrumented_parser(samples)):
        result = bench.run(args)
    host = json.loads(host_output.read_text(encoding='utf-8'))
    correlation = correlate(samples, host)
    completed_cleanly = (result == 0 and host.get('stop_reason') == 'duration_reached'
                         and not host.get('failure') and not host.get('cleanup_errors'))
    identity = None
    if extra.decode_synthetic_extended:
        if not completed_cleanly:
            # A cleanup failure may leave an owned encoder/reader alive. Never
            # start offline decoding until the underlying run confirms cleanup.
            identity = dict(status='not_decoded', error='USB run did not finish with confirmed successful cleanup')
        elif samples.retention_overflow or samples.retained_count!=samples.count or samples.parsers!=1:
            identity = dict(status='not_decoded', error='Retention overflow, incomplete AU set or encoder restart')
        else:
            # Offline only, after bench.run stopped and joined its workers.
            import production_identity as probe
            import ctypes as C
            frequency = C.c_int64()
            if not probe.KERNEL.QueryPerformanceFrequency(C.byref(frequency)):
                raise C.WinError(C.get_last_error())
            f = frequency.value
            arrivals = [dict(arrival_qpc=(samples.time[i]*f)//1_000_000_000,
                             encoded_bytes=samples.length[i]) for i in range(samples.count)]
            start = arrivals[0]['arrival_qpc'] if arrivals else 0
            try:
                identity = probe.decode_identities(args.ffmpeg,samples.frames[:samples.retained_count],
                    arrivals,f,start,args.warmup,args.duration,False)
            except Exception as exc:
                identity = dict(status='failed', error=f'{type(exc).__name__}: {exc}')
    report = dict(schema=1, scope='Production USB arrival/write research instrumentation; host timing only, no optical claims',
        helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        host_helper_sha256=hashlib.sha256(Path(bench.__file__).read_bytes()).hexdigest(),
        host_report=dict(file=host_output.name,sha256=hashlib.sha256(host_output.read_bytes()).hexdigest()),
        host_status=dict(stop_reason=host['stop_reason'],failure=host['failure'],cleanup_errors=host['cleanup_errors']),
        settings=host['settings'],ffmpeg_sha256=host['ffmpeg_sha256'],command=host['command'],
        screen_video_saved=False, software_encoding=False,
        retained_au_count=samples.retained_count,retained_bytes=samples.retained_bytes,
        retention_overflow=samples.retention_overflow,pattern_identity=identity,**correlation)
    final_output.parent.mkdir(parents=True,exist_ok=True)
    with final_output.open('x',encoding='utf-8') as output:
        json.dump(report,output,indent=2);output.write('\n')
    print(json.dumps({k:report[k] for k in ('status','errors','arrival_count','write_count',
        'unmatched_shutdown_tail_count','steady_arrival_interval_ms','steady_send_begin_interval_ms',
        'steady_completion_interval_ms','steady_arrival_to_write_begin_ms','steady_usb_write_ms')},indent=2))
    return result or (0 if completed_cleanly and correlation['status']=='matched' and
                      (identity is None or identity['status']=='completed') else 2)


if __name__=='__main__':
    raise SystemExit(main())
