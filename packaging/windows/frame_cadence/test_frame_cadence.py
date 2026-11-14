"""CPU-only checks: no encoder, GPU, display, device or renderer is opened."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import production_identity as probe
import measure_usb_host as usb_probe
from pattern_identity import decode_marker,FRAME_BYTES,WIDTH,HEIGHT


def marker(frame,qpc):
    image=bytearray(FRAME_BYTES)
    for row,value in enumerate((frame,qpc&0xffffffff,qpc>>32)):
        for bit in range(32):
            shade=235 if value>>bit&1 else 16
            for y in range(row*16,(row+1)*16):
                image[y*WIDTH+bit*16:y*WIDTH+(bit+1)*16]=bytes([shade])*16
    return bytes(image)


class CommandTests(unittest.TestCase):
    target=dict(adapter=0,output=1,vendor_id=0x10de,width=1920,height=1080)

    def test_reference_removes_optional_flags_and_preserves_quality(self):
        for preset in ('p1','p4'):
            command=probe.make_command(Path('unused.exe'),self.target,preset,0,0,set())
            expected={'-c:v':'h264_nvenc','-profile:v':'high','-coder':'cabac',
                '-qp_cb_offset':'-4','-qp_cr_offset':'-4','-multipass':'qres',
                '-bf':'0','-rc-lookahead':'0','-preset':preset,'-b:v':'20000000',
                '-maxrate':'20000000','-bufsize':'400000','-r':'100'}
            for key,value in expected.items():
                self.assertEqual(command.count(key),1)
                self.assertEqual(command[command.index(key)+1],value)
            graph=command[command.index('-filter_complex')+1]
            self.assertNotIn('fresh_wait_us',graph)
            self.assertNotIn('delivery_delay_us',graph)
            self.assertNotIn('-nostdin',command)

    def test_candidate_requires_capability_and_sets_requested_values(self):
        with self.assertRaisesRegex(ValueError,'unavailable'):
            probe.make_command(Path('unused.exe'),self.target,'p4',2000,8000,set())
        command=probe.make_command(Path('unused.exe'),self.target,'p4',2000,8000,
            {'fresh_wait_us','delivery_delay_us'})
        graph=command[command.index('-filter_complex')+1]
        self.assertEqual(graph.count('fresh_wait_us=2000'),1)
        self.assertEqual(graph.count('delivery_delay_us=8000'),1)

    def test_invalid_arguments_fail_before_device_or_process_access(self):
        with tempfile.TemporaryDirectory() as folder:
            output=str(Path(folder)/'new.json')
            for extra in (['--seconds','61'],['--seconds','0'],['--warmup','20'],
                          ['--fresh-wait-us','5000'],['--delivery-delay-us','9000']):
                with self.subTest(extra=extra),patch.object(sys,'argv',['probe','--output',output,*extra]),\
                    patch.object(probe,'outputs') as outputs,\
                    patch.object(probe.subprocess,'Popen') as process,\
                    patch.object(probe,'capabilities') as capabilities,\
                    contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as caught:probe.main()
                    self.assertEqual(caught.exception.code,2)
                    outputs.assert_not_called();process.assert_not_called();capabilities.assert_not_called()


class MarkerTests(unittest.TestCase):
    def test_exact_identity_and_uncertain_cells(self):
        stamp=0x13579BDF2468ACE0
        result=decode_marker(marker(0xFEEDC0DE,stamp))
        self.assertEqual((result['frame_id'],result['render_qpc'],result['uncertain_bits']),
                         (0xFEEDC0DE,stamp,0))
        self.assertEqual(decode_marker(bytes([128])*FRAME_BYTES)['uncertain_bits'],96)

    def test_primary_and_extended_crop_repeat_and_real_age(self):
        arrivals=[dict(arrival_qpc=1500,encoded_bytes=5),dict(arrival_qpc=1600,encoded_bytes=6)]
        for primary,y in ((False,8),(True,146)):
            with self.subTest(primary=primary),patch.object(probe.subprocess,'run',return_value=
                SimpleNamespace(returncode=0,stdout=marker(77,1000)*2,stderr=b'')) as run:
                result=probe.decode_identities('unused.exe',[b'first',b'second'],arrivals,
                    10000,1000,0,1,primary)
                self.assertEqual(result['status'],'completed')
                self.assertEqual(result['repeated_source_ids'],1)
                self.assertEqual(result['source_render_to_host_ms']['max'],60)
                command=run.call_args.args[0]
                self.assertEqual(command[command.index('-vf')+1],f'crop=512:48:16:{y},format=gray')
                self.assertEqual(command[command.index('-hwaccel')+1],'none')
                self.assertEqual(run.call_args.kwargs['timeout'],180)
                self.assertNotIn('capture_sample',result['records'][0])

    def test_decoder_errors_and_backward_ids_are_not_accepted(self):
        arrivals=[dict(arrival_qpc=1500,encoded_bytes=5),dict(arrival_qpc=1600,encoded_bytes=6)]
        with patch.object(probe.subprocess,'run',return_value=SimpleNamespace(returncode=0,
            stdout=marker(78,1000)+marker(77,1100),stderr=b'')):
            self.assertEqual(probe.decode_identities('unused.exe',[b'a',b'b'],arrivals,
                10000,1000,0,1,False)['status'],'failed')
        with patch.object(probe.subprocess,'run',return_value=SimpleNamespace(returncode=0,
            stdout=marker(77,1000)*2,stderr=b'error-level decoder diagnostic')):
            self.assertEqual(probe.decode_identities('unused.exe',[b'a',b'b'],arrivals,
                10000,1000,0,1,False)['status'],'failed')


class USBTimingTests(unittest.TestCase):
    def test_dry_run_never_opens_usb_or_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            executable=Path(folder)/'fake.exe'
            executable.write_bytes(b'not executable')
            output=Path(folder)/'new.json'
            argv=['--source','1','--ffmpeg',str(executable),'--output',str(output)]
            with patch.object(usb_probe,'run') as run,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(usb_probe.main(argv),0)
                run.assert_not_called()
            self.assertFalse(output.exists())
            with patch.object(usb_probe,'run') as run,contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):usb_probe.main([*argv,'--duration','61'])
                run.assert_not_called()

    def test_full_wire_payload_accounting(self):
        for payload in (1,977,978,979,25000,56000):
            fragments=(payload+usb_probe.MAX_PC_VIDEO_CHUNK-1)//usb_probe.MAX_PC_VIDEO_CHUNK
            wire=payload+fragments*(usb_probe.V1_OVERHEAD+usb_probe.VIDEO_HEADER_SIZE)
            self.assertEqual(usb_probe.wire_estimate(wire),(payload,fragments))
        with self.assertRaises(ValueError):usb_probe.wire_estimate(1)


if __name__=='__main__':unittest.main()
