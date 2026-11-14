"""CPU-only checks; no device inventory, renderer, encoder or USB is opened."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import instrument_usb as probe


def sample_pair():
    samples = probe.ArrivalSamples()
    samples.parsers = 1
    with patch.object(probe.time, 'perf_counter_ns', return_value=1_000_000_000):
        samples.feed_result([b'abc'], 0)
    with patch.object(probe.time, 'perf_counter_ns', return_value=1_010_000_000):
        samples.feed_result([b'defg'], 0)
    records = [dict(kind='video', encoded_bytes_estimate=size,
                    before_ns=stamp+100_000, after_ns=stamp+900_000,
                    completed=True, duration_ms=.8)
               for size,stamp in [(3,1_000_000_000),(4,1_010_000_000)]]
    host = dict(records=records, events=[], warmup_seconds=0,
                events_dropped=0, records_dropped=0)
    return samples,host


class ArrivalTests(unittest.TestCase):
    def test_empty_feed_no_clock_or_batch(self):
        samples = probe.ArrivalSamples()
        with patch.object(probe.time,'perf_counter_ns') as clock:
            samples.feed_result([],0)
        clock.assert_not_called()
        self.assertEqual((samples.count,samples.batches),(0,0))

    def test_batch_keeps_same_time_and_exact_byte_references(self):
        samples = probe.ArrivalSamples(retain=True)
        first,second = bytes([1,2,3]),bytes([4,5])
        with patch.object(probe.time,'perf_counter_ns',return_value=1234) as clock:
            samples.feed_result([first,second],0)
        clock.assert_called_once()
        self.assertEqual(list(samples.time[:2]),[1234,1234])
        self.assertEqual(list(samples.batch[:2]),[0,0])
        self.assertIs(samples.frames[0],first)
        self.assertIs(samples.frames[1],second)
        self.assertEqual(samples.retained_bytes,5)

    def test_sample_and_retention_capacities_are_bounded(self):
        with patch.object(probe,'CAPACITY',2),patch.object(probe,'MAX_AUS',1),\
             patch.object(probe,'MAX_BYTES',3):
            samples=probe.ArrivalSamples(retain=True)
            samples.feed_result([b'ab',b'cd',b'ef'],0)
        self.assertEqual((samples.count,samples.overflow),(2,1))
        self.assertEqual((samples.retained_count,samples.retention_overflow),(1,1))
        self.assertEqual(len(samples.frames),1)

    def test_byte_budget_does_not_discard_arrival_metadata(self):
        with patch.object(probe,'MAX_BYTES',3):
            samples=probe.ArrivalSamples(retain=True)
            samples.feed_result([b'four'],0)
        self.assertEqual(samples.count,1)
        self.assertEqual((samples.retained_count,samples.retention_overflow),(0,1))

    def test_parser_decorator_preserves_feed_return_and_counts_instances(self):
        returned=[b'abc']
        class Original:
            def feed(self,data):
                self.input=data
                return returned
        samples=probe.ArrivalSamples()
        with patch.object(probe.engine,'AviPacketStream',Original):
            parser_type=probe.instrumented_parser(samples)
        parser=parser_type()
        self.assertIs(parser.feed(b'data'),returned)
        self.assertEqual(parser.input,b'data')
        self.assertEqual((samples.parsers,samples.count),(1,1))
        parser_type()
        self.assertEqual(samples.parsers,2)


class AlignmentTests(unittest.TestCase):
    def test_exact_prefix_and_shutdown_tail(self):
        samples,host=sample_pair()
        result=probe.correlate(samples,host)
        self.assertEqual(result['status'],'matched')
        self.assertEqual(result['matched_count'],2)
        self.assertEqual(result['unmatched_shutdown_tail_count'],0)
        host['records'].pop()
        result=probe.correlate(samples,host)
        self.assertEqual(result['status'],'matched')
        self.assertEqual(result['unmatched_shutdown_tail_count'],1)

    def test_no_forward_size_matching_after_mismatch(self):
        samples,host=sample_pair()
        host['records'][0]['encoded_bytes_estimate']=4
        result=probe.correlate(samples,host)
        self.assertEqual(result['status'],'unmatched')
        self.assertEqual(result['matched_records'],[])

    def test_failure_branches_never_claim_aligned(self):
        def before_arrival(s,h): h['records'][0]['before_ns']=1
        def extra_write(s,h): h['records'].append(dict(h['records'][-1]))
        def restart(s,h): h['events'].append({'event':'encoder_restart'})
        def discarded(s,h): h['events'].append({'event':'oversize_frame'})
        mutations=[lambda s,h:setattr(s,'overflow',1),
            lambda s,h:setattr(s,'parsers',2),
            lambda s,h:h.update(events_dropped=1),
            lambda s,h:h.update(records_dropped=1),
            lambda s,h:s.length.__setitem__(0,probe.engine.MAX_FRAME_BYTES+1),
            before_arrival,extra_write,restart,discarded]
        for mutate in mutations:
            samples,host=sample_pair()
            mutate(samples,host)
            result=probe.correlate(samples,host)
            with self.subTest(mutation=mutate):
                self.assertEqual(result['status'],'unmatched')
                self.assertTrue(result['errors'])
                self.assertEqual(result['matched_records'],[])

    def test_steady_cutoff_and_failed_writes_not_in_distribution(self):
        samples,host=sample_pair()
        host['warmup_seconds']=.001
        result=probe.correlate(samples,host)
        self.assertEqual(result['steady_count'],1)
        self.assertAlmostEqual(result['steady_arrival_to_write_begin_ms']['p50'],.1)
        host['records'][1]['completed']=False
        self.assertEqual(probe.correlate(samples,host)['steady_count'],0)


class InvocationTests(unittest.TestCase):
    def test_dry_run_never_calls_capture_or_patches_parser(self):
        args=SimpleNamespace(run=False,source=1,output=Path('example.json'))
        with patch.object(probe.bench,'arguments',return_value=args),\
             patch.object(probe.bench,'run') as run,\
             patch.object(probe,'instrumented_parser') as instrument,\
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(probe.main([]),0)
        run.assert_not_called()
        instrument.assert_not_called()

    def test_offline_decode_requires_successful_run_and_confirmed_cleanup(self):
        cases = [
            ('nonzero_run', 7, {}),
            ('incomplete_stop', 0, {'stop_reason':'timeout'}),
            ('host_failure', 0, {'failure':{'type':'RuntimeError','message':'failed'}}),
            ('cleanup_failed', 0, {'cleanup_errors':['reader did not stop']}),
        ]
        for label,result,changes in cases:
            with self.subTest(case=label),tempfile.TemporaryDirectory() as folder:
                output=Path(folder)/'probe.json'
                args=SimpleNamespace(run=True,source=1,adapter=0,output=output)
                samples=SimpleNamespace(retention_overflow=0,retained_count=1,
                    retained_bytes=3,count=1,parsers=1)
                host=dict(stop_reason='duration_reached',failure=None,cleanup_errors=[],
                    settings={},ffmpeg_sha256='test',command=[])
                host.update(changes)
                correlation=dict(status='matched',errors=[],arrival_count=1,write_count=1,
                    unmatched_shutdown_tail_count=0,steady_arrival_interval_ms={},
                    steady_send_begin_interval_ms={},steady_completion_interval_ms={},
                    steady_arrival_to_write_begin_ms={},steady_usb_write_ms={})
                decode=Mock()
                frequency=Mock()
                module=SimpleNamespace(decode_identities=decode,
                    KERNEL=SimpleNamespace(QueryPerformanceFrequency=frequency))
                def run(run_args):
                    run_args.output.write_text(json.dumps(host),encoding='utf-8')
                    return result
                with patch.object(probe.bench,'arguments',return_value=args),\
                     patch.object(probe.bench,'run',side_effect=run),\
                     patch.object(probe,'ArrivalSamples',return_value=samples),\
                     patch.object(probe,'correlate',return_value=correlation),\
                     patch('desktop_app.dxgi.outputs',return_value=[dict(adapter=0,output=1,
                         device='mock',width=1920,height=1080)]),\
                     patch('desktop_app.displays.inventory',return_value=[dict(device='mock',
                         primary=False,active=True,hz=100)]),\
                     patch.dict(sys.modules,{'production_identity':module}),\
                     contextlib.redirect_stdout(io.StringIO()):
                    status=probe.main(['--decode-synthetic-extended'])
                self.assertEqual(status,result or 2)
                report=json.loads(output.read_text(encoding='utf-8'))
                self.assertEqual(report['pattern_identity']['status'],'not_decoded')
                self.assertIn('cleanup',report['pattern_identity']['error'])
                decode.assert_not_called()
                frequency.assert_not_called()


if __name__=='__main__':
    unittest.main()
