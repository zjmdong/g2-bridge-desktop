"""Pure CPU, tiny images only. No FFmpeg/GPU/process/window/device calls."""
import argparse
import io
import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch
import numpy as np
import check_motion_quality as q


class MotionQualityTests(unittest.TestCase):
    def test_deterministic_every_frame_new(self):
        p=q.Pattern(320,128,'overwrite',0)
        self.assertEqual(p.nv12(7),p.nv12(7))
        self.assertNotEqual(p.nv12(7),p.nv12(8))
        self.assertEqual(len(p.bgra(7)),320*128*4)

    def test_spatial_ids(self):
        p=q.Pattern(320,128,'fast-pan',0)
        for i in (0,1,17,300,999):
            ids=p.identity(p.planes(i)[0])
            self.assertEqual(ids['region_ids'],[i]*8)
            self.assertGreater(ids['minimum_cell_threshold_margin'],90)

    def test_torn_regions_detected(self):
        p=q.Pattern(320,128,'fast-pan',0)
        y=p.planes(50)[0];old=p.planes(49)[0]
        y[:,160:]=old[:,160:]
        ids=p.identity(y)
        self.assertFalse(ids['regions_agree'])
        self.assertEqual(set(ids['region_ids']),{49,50})

    def test_exact_roundtrip_and_metrics(self):
        p=q.Pattern(320,128,'fine',0)
        expected=p.planes(1)
        got=q.planes_from_nv12(p.nv12(1),320,128)
        for a,b in zip(got,expected):np.testing.assert_array_equal(a,b)
        m=q.quality(got,expected)
        self.assertIsNone(m['y_psnr_db'])
        self.assertEqual(m['block16_mse_max'],0)
        self.assertEqual(m['block16_boundary_residual_mae'],0)

    def test_block_metrics(self):
        expected=tuple(np.full(shape,100,dtype=np.uint8) for shape in ((128,320),(64,160),(64,160)))
        actual=tuple(x.copy() for x in expected)
        actual[0][16:32,16:32]+=20
        m=q.quality(actual,expected)
        self.assertEqual(m['block16_mse_max'],400)
        self.assertGreater(m['block16_boundary_residual_mae'],0)
        self.assertGreater(m['y_psnr_db'],30)

    def test_scene_phases(self):
        p=q.Pattern(320,128,'mixed',300)
        self.assertEqual([p.phase(n) for n in (299,300,360,420,480)],
                         ['bootstrap','fast-pan','cut','fine','overwrite'])
        for i in (299,300,360,420,480):
            self.assertEqual(p.identity(p.planes(i)[0])['region_ids'],[i]*8)

    def test_trace_qp_and_ref_chain(self):
        lines=[]
        def section(name,fields):
            lines.append('[trace_headers @ abc] '+name)
            lines.extend(f'[trace_headers @ abc] {n} {key} 010 = {value}'
                         for n,(key,value) in enumerate(fields.items()))
        section('Sequence Parameter Set',dict(seq_parameter_set_id=0,log2_max_frame_num_minus4=0))
        section('Picture Parameter Set',dict(pic_parameter_set_id=0,seq_parameter_set_id=0,pic_init_qp_minus26=0))
        for i in range(3):
            section('Slice Header',dict(nal_unit_type=5 if i==0 else 1,nal_ref_idc=3,
                first_mb_in_slice=0,pic_parameter_set_id=0,frame_num=i,slice_qp_delta=7+i))
            section('Access Unit Delimiter',dict(nal_ref_idc=0,nal_unit_type=9))
        got=q.parse_trace('\n'.join(lines))
        self.assertEqual(got['frame_num_errors'],[])
        self.assertEqual([x['initial_qp'] for x in got['pictures']],[33,34,35])
        bad=q.parse_trace('\n'.join(lines).replace('frame_num 010 = 2','frame_num 010 = 4'))
        self.assertEqual(len(bad['frame_num_errors']),1)

    def test_offline_command_never_captures(self):
        args=argparse.Namespace(template=Path(__file__).with_name('baseline-command-v024.json'),
            ffmpeg=Path('ffmpeg.exe'),adapter=0,frames=540,profile='high',preset='p4',spatial_aq=1,
            temporal_aq=0,aq_strength=8,refs=1,multipass='qres',async_encode=1,surfaces=None,buffer_bits=None)
        for path in ('cpu-nv12','gpu-upload'):
            args.path=path;c=q.commands(args)
            self.assertFalse(any('ddagrab=' in x or 'gfxcapture=' in x for x in c))
            self.assertNotIn('-latest_frame',c)
            self.assertEqual(c[c.index('-c:v')+1],'h264_nvenc')
            self.assertEqual(c[c.index('-profile:v')+1],'high')
            self.assertEqual(c[c.index('-b:v')+1],'20000000')
            self.assertEqual(c[c.index('-force_key_frames')+1],'0,1,2')
            graph=c[c.index('-filter_complex')+1]
            self.assertEqual('hwupload' in graph,path=='gpu-upload')
            self.assertEqual('scale_d3d11' in graph,path=='gpu-upload')

    def test_candidate_template_keeps_high_cabac_and_rejects_conflicting_profile(self):
        args=argparse.Namespace(template=Path(__file__).with_name('candidate-command-v025.json'),
            ffmpeg=Path('ffmpeg.exe'),adapter=0,frames=540,profile='high',preset='p4',spatial_aq=0,
            temporal_aq=0,aq_strength=8,refs=1,multipass='qres',async_encode=1,surfaces=None,
            buffer_bits=None,path='gpu-upload')
        command=q.commands(args)
        self.assertEqual(command[command.index('-profile:v')+1],'high')
        self.assertEqual(command[command.index('-coder')+1],'cabac')
        self.assertEqual(command[command.index('-multipass')+1],'qres')
        self.assertEqual(command[command.index('-qp_cb_offset')+1],'-4')
        self.assertEqual(command[command.index('-qp_cr_offset')+1],'-4')
        self.assertEqual(command[command.index('-spatial-aq')+1],'0')
        self.assertEqual(command[command.index('-temporal-aq')+1],'0')
        args.profile='baseline'
        with self.assertRaisesRegex(RuntimeError,'Baseline cannot use explicit CABAC'):
            q.commands(args)

    def test_candidate_and_intermediate_templates_preserve_the_baseline_history(self):
        folder=Path(__file__).parent
        baseline=json.loads((folder/'baseline-command-v024.json').read_text())
        middle=json.loads((folder/'candidate-high-only-v025.json').read_text())
        final=json.loads((folder/'candidate-command-v025.json').read_text())
        for command in (baseline,middle):
            self.assertNotIn('-qp_cb_offset',command)
            self.assertNotIn('-qp_cr_offset',command)
        self.assertEqual(baseline[baseline.index('-profile:v')+1],'baseline')
        self.assertEqual(middle[middle.index('-profile:v')+1],'high')
        stripped=list(final)
        for option in ('-qp_cb_offset','-qp_cr_offset'):
            self.assertEqual(stripped.count(option),1)
            at=stripped.index(option)
            self.assertEqual(stripped[at+1],'-4')
            del stripped[at:at+2]
        self.assertEqual(stripped,middle)

    def test_final_template_matches_production_options_without_starting_encoder(self):
        from goggles_bridge.engine import BridgeSettings,encoder_command
        from desktop_app.video import compatible_command
        settings=BridgeSettings(Path('unused.dll'),Path('ffmpeg.exe'),capture='ddagrab',
            fps=100,bitrate_mbps=20,preset='p4',h264_profile='high')
        production=compatible_command(encoder_command(settings),output=dict(adapter=0,
            output=1,vendor_id=0x10de,width=1920,height=1080))
        frozen=json.loads(Path(__file__).with_name('candidate-command-v025.json').read_text())
        def options(command):
            self.assertEqual(command[-1],'pipe:1')
            found={'output':command[-1]};at=1
            while at<len(command)-1:
                flag=command[at]
                self.assertTrue(flag.startswith('-'))
                self.assertNotIn(flag,found)
                if flag in ('-hide_banner','-nostdin','-nostats','-an'):
                    found[flag]=None;at+=1
                else:
                    self.assertLess(at+1,len(command)-1)
                    found[flag]=command[at+1];at+=2
            return found
        self.assertEqual(options(production),options(frozen))

    def test_receiver_failure_joins_input_writer_without_starting_a_process(self):
        killed=threading.Event()
        finished=threading.Event()
        class FakeProcess:
            def __init__(self):
                self.stdin=io.BytesIO()
                self.stdout=io.BytesIO(b'bad payload')
                self.returncode=None
            def poll(self):return self.returncode
            def kill(self):
                self.returncode=-9
                killed.set()
            def wait(self,timeout=None):return self.returncode
        process=FakeProcess()
        def source():
            self.assertTrue(killed.wait(2))
            time.sleep(.02)
            yield b'generated pixels'
            finished.set()
        def receive(_data):raise ValueError('bad output')
        with patch.object(q.subprocess,'Popen',return_value=process):
            with self.assertRaisesRegex(ValueError,'bad output'):
                q.run_stream(['unused.exe'],source(),receive,10)
        self.assertTrue(finished.is_set())
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)


if __name__=='__main__':unittest.main()
