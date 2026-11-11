"""Pure CPU validation of provenance pairing and static-source interpretation."""
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import sys
from check_frame_age import ROOT, analyze, measured_avi_reader, gpu_priority_policy, frozen_baseline_command
sys.path.insert(0,str(ROOT/'tests'))
from avi_fixture import stream
import goggles_bridge.avi as production_avi


def samples(presents=(1000,1100,1200)):
    records=[]
    arrivals=[]
    for i,present in enumerate(presents):
        sample=1005+i*100
        r=dict(index=i,frequency=10000,sequence=10+i,present=present,
            sample=sample,acquire_start=sample+1,acquire_end=sample+2,
            emit=sample+3,filter_out=sample+4,dequeue=sample+5,
            encode_start=sample+6,packet_ready=sample+10,mux_start=sample+11,
            mux_end=sample+14,accumulated=1,mouse=0,flags=1,
            pts=i,bytes=25000,result=0,output=0,stream=0)
        records.append(r)
        # Reading pipe data before producer write returns is possible.
        arrivals.append(dict(qpc=sample+12,bytes=24994,raw_bytes=25000))
    return records,arrivals


class AgeTests(unittest.TestCase):
    def test_frozen_baseline_does_not_inherit_live_application_defaults(self):
        target=dict(vendor_id=0x10de,adapter=2,output=3)
        command=frozen_baseline_command('probe.exe',target)
        graph=command[command.index('-filter_complex')+1]
        self.assertIn('output_idx=3:',graph)
        self.assertIn('source_clock=0:',graph)
        self.assertIn('source_guard_us=2000:',graph)
        self.assertIn('defer_release=0',graph)
        self.assertEqual(command[command.index('-b:v')+1],'20000000')
        self.assertEqual(command[command.index('-preset')+1],'p4')
        self.assertEqual(command[command.index('-init_hw_device')+1],'d3d11va=cap:2')
        historical=frozen_baseline_command('old-probe.exe',target,set())
        self.assertNotIn('source_clock=',historical[historical.index('-filter_complex')+1])

    def test_gpu_priority_only_uses_child_and_records_actual_class(self):
        state={'class':2}
        def get(handle,target):
            self.assertEqual(handle,123)
            target._obj.value=state['class']
            return 0
        def set_class(handle,value):
            self.assertEqual(handle,123)
            state['class']=value
            return 0
        gdi=SimpleNamespace(D3DKMTGetProcessSchedulingPriorityClass=Mock(side_effect=get),
            D3DKMTSetProcessSchedulingPriorityClass=Mock(side_effect=set_class))
        child=SimpleNamespace(_handle=123)
        with patch('check_frame_age.C.WinDLL',return_value=gdi),patch('check_frame_age.prioritize_gpu') as sdk:
            ok,result=gpu_priority_policy(child,4)
            self.assertTrue(ok)
            self.assertEqual(result['before']['priority_class'],2)
            self.assertEqual(result['after']['priority_class'],4)
            sdk.assert_not_called()
            gdi.D3DKMTSetProcessSchedulingPriorityClass.reset_mock()
            ok,result=gpu_priority_policy(child,skip=True)
            self.assertFalse(ok)
            self.assertEqual(result['before'],result['after'])
            gdi.D3DKMTSetProcessSchedulingPriorityClass.assert_not_called()

    def test_raw_size_observer_preserves_sdk_parser_and_module(self):
        aud=b'\0\0\0\1\x09\xf0'
        packets=[aud+b'\0\0\1\x65idr',aud+b'\0\0\1\x41pframe']
        payload=stream(packets)
        original_strip=production_avi.strip_aud
        for cut in range(len(payload)+1):
            reader,sizes=measured_avi_reader()
            frames=reader.feed(payload[:cut])+reader.feed(payload[cut:])
            reader.finish()
            self.assertEqual(list(sizes),list(map(len,packets)))
            self.assertEqual(frames,[original_strip(p) for p in packets])
            self.assertIs(production_avi.strip_aud,original_strip)

    def test_complete_ordered_access_units(self):
        native,arrivals=samples()
        r=analyze(native,arrivals,10000,0,0)
        self.assertEqual(r['errors'],[])
        self.assertEqual(r['unique_present_values'],3)
        self.assertEqual(r['source_age_unique_present_ms']['p50'],1.7)
        self.assertEqual(r['host_arrival_interval_ms']['p50'],10)

    def test_static_age_and_repeated_images_remain_visible(self):
        native,arrivals=samples((1000,1000,1000))
        r=analyze(native,arrivals,10000,0,0)
        self.assertEqual(r['errors'],[])
        self.assertEqual(r['unique_present_values'],1)
        self.assertEqual(r['repeated_present_values'],2)
        self.assertIsNone(r['source_present_interval_ms'])
        self.assertGreater(r['source_age_all_frames_ms']['max'],20)

    def test_compact_pts_cannot_hide_source_age(self):
        native,arrivals=samples()
        native[-1]['present']=1050
        r=analyze(native,arrivals,10000,0,0)
        self.assertEqual(r['host_arrival_interval_ms']['p50'],10)
        self.assertGreater(r['source_age_all_frames_ms']['max'],15)

    def test_count_size_and_sequence_errors_fail_pairing(self):
        native,arrivals=samples()
        arrivals[1]['raw_bytes']=123
        native[2]['sequence']=native[1]['sequence']
        r=analyze(native,arrivals,10000,0,0)
        self.assertEqual(len(r['errors']),2)
        self.assertTrue(analyze(native,arrivals[:-1],10000,0,0)['errors'])

    def test_source_can_present_during_acquire(self):
        native,arrivals=samples()
        native[1]['present']=native[1]['sample']+1
        self.assertEqual(analyze(native,arrivals,10000,0,0)['errors'],[])

    def test_bad_timestamp_fails(self):
        native,arrivals=samples()
        native[1]['packet_ready']=native[1]['sample']
        self.assertTrue(analyze(native,arrivals,10000,0,0)['errors'])

    def test_warmup_and_drain_do_not_pollute_full_second_windows(self):
        native,arrivals=samples(tuple(1000+i*100 for i in range(420)))
        r=analyze(native,arrivals,10000,0,3,4)
        self.assertEqual(r['errors'],[])
        self.assertEqual(len(r['one_second_host_output']),1)
        self.assertEqual(r['one_second_host_output'][0]['frames'],100)
        self.assertEqual(r['one_second_host_output'][0]['encoded_mbps'],20)
        self.assertEqual(r['measured_frames'],100)
        self.assertEqual(r['unique_host_fps'],100)
        self.assertEqual(r['repeated_present_fraction'],0)


if __name__=='__main__':unittest.main()
