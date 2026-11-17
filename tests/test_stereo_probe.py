import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from goggles_bridge.control import V1Packet, heartbeat
from goggles_bridge.engine import BridgeSettings, encoder_command
from tools.research import stereo_probe

# defaults follow the host's GPU, so these tests pin detection to NVENC
DETECTION = mock.patch('goggles_bridge.engine.default_windows_encoder', return_value='nvenc')
setUpModule, tearDownModule = DETECTION.start, DETECTION.stop


class StereoProbeTests(unittest.TestCase):
    def test_command_keeps_bridge_encoder_and_replaces_source(self):
        settings = BridgeSettings(Path('dll'), Path('ffmpeg'), fps=60)
        bridge = encoder_command(settings)
        for layout, size in (('sbs', '960x1080'), ('fsbs', '1920x1080'), ('ftb', '1920x1080')):
            with self.subTest(layout=layout):
                command = stereo_probe.probe_command(settings, layout)
                source = command[command.index('-i')+1]
                self.assertIn(f'testsrc2=size={size}:rate=60', source)
                self.assertIn('vstack' if layout == 'ftb' else 'hstack', source)
                self.assertEqual(command[command.index('-level:v')+1], '5.1')
                self.assertEqual(command[-3:], bridge[-3:])
                self.assertEqual(len(command), len(bridge))

    def test_stereo_metadata_matches_layout_and_keeps_sei(self):
        settings = BridgeSettings(Path('dll'), Path('ffmpeg'), fps=60)
        for layout, packing in (('sbs', 3), ('fsbs', 3), ('ftb', 4)):
            with self.subTest(layout=layout):
                command = stereo_probe.probe_command(settings, layout, stereo_sei=True)
                self.assertEqual(command[command.index('-c:v')+1], 'libx264')
                self.assertEqual(command[command.index('-x264-params')+1],
                                 f'frame-packing={packing}:repeat-headers=1:aud=1')
                self.assertEqual(command[command.index('-bsf:v')+1], 'filter_units=remove_types=12')
                self.assertEqual(command[-3:], ['-f', 'avi', 'pipe:1'])
                self.assertNotIn('-rc', command)

    def test_inbound_summary_reassembles_split_reads(self):
        push = V1Packet(0x09, 0x43, 14, 0, 10, 1, 0, 0, 7, b'\x03').serialize()
        reply = V1Packet(0, 0, 28, 0, 10, 1, 1, 0, 1, bytes(7)).serialize()
        rows = [{'event': 'control_send', 'hex': heartbeat(1).serialize().hex()},
                {'event': 'control_receive', 'hex': (push + reply[:5]).hex()},
                {'event': 'control_receive', 'hex': (reply[5:] + push).hex()}]
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'log.jsonl'
            log.write_text(''.join(json.dumps(row)+'\n' for row in rows), encoding='utf-8')
            self.assertEqual(stereo_probe.inbound_summary(log), {(9, 0x43, 14, 0): 2, (0, 0, 28, 0): 1})


if __name__ == '__main__':
    unittest.main()
