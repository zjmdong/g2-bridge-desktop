import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pattern_identity import decode_marker,verify,summarize_markers,WIDTH,HEIGHT


def marker(frame,qpc):
    values=(frame,qpc&0xffffffff,qpc>>32)
    image=bytearray(WIDTH*HEIGHT)
    for row,value in enumerate(values):
        for bit in range(32):
            gray=235 if value>>bit&1 else 16
            for y in range(row*16,(row+1)*16):
                image[y*WIDTH+bit*16:y*WIDTH+(bit+1)*16]=bytes([gray])*16
    return bytes(image)


class PatternTests(unittest.TestCase):
    def test_limited_range_barcode_exact_64_bit_qpc(self):
        stamp=0x13579BDF2468ACE0
        r=decode_marker(marker(0xFEEDC0DE,stamp))
        self.assertEqual(r['frame_id'],0xFEEDC0DE)
        self.assertEqual(r['render_qpc'],stamp)
        self.assertEqual(r['uncertain_bits'],0)

    def test_ambiguous_cells_are_not_accepted(self):
        self.assertEqual(decode_marker(bytes([128])*(WIDTH*HEIGHT))['uncertain_bits'],96)

    def test_offline_pairing_reports_actual_repeats_and_host_age(self):
        records=[dict(sequence=i+1,present=1200,sample=1300+i*100,emit=1310+i*100,
            arrival=1500+i*100,warmup=False) for i in range(2)]
        with patch('pattern_identity.subprocess.run',return_value=SimpleNamespace(
            returncode=0,stdout=marker(77,1000)*2,stderr=b'')) as run:
            r=verify('ffmpeg.exe',[b'first',b'second'],records,10000)
            self.assertEqual(r['status'],'completed')
            self.assertEqual(r['unique_frame_ids'],1)
            self.assertEqual(r['repeated_frame_ids'],1)
            self.assertEqual(r['render_to_host_arrival_ms']['max'],60)
            args=run.call_args.args[0]
            self.assertEqual(args[args.index('-hwaccel')+1],'none')
            self.assertEqual(run.call_args.kwargs['input'],b'firstsecond')

    def test_identity_summary_excludes_drain_without_losing_records(self):
        rows=[dict(frame_id=10+i,render_qpc=1000+i*100,present=1100+i*100,
            sample=1200+i*100,arrival=1500+i*100,warmup=False) for i in range(3)]
        summary=summarize_markers(rows,10000,1600)
        self.assertEqual(len(rows),3)
        self.assertEqual(summary['measured_frames'],2)
        self.assertEqual(summary['unique_frame_ids'],2)
        self.assertEqual([r['included_in_summary'] for r in rows],[True,True,False])


if __name__=='__main__':unittest.main()
