"""Build real upstream commands without capturing or starting an encoder."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from goggles_bridge.engine import BridgeSettings, encoder_command
from goggles_bridge.app.windows import video


def settings(**options):
    return BridgeSettings(Path('unused.dll'), Path('unused.exe'),
                          **dict(capture='ddagrab', **options))


def option(command, name):
    return command[command.index(name)+1]


class VideoAdapterTests(unittest.TestCase):
    def test_upstream_periodic_keyframes_are_replaced_once_without_mutating_cli(self):
        original = encoder_command(settings())
        saved = list(original)
        self.assertIn('expr:', option(original, '-force_key_frames'))
        result = video.compatible_command(original)
        self.assertEqual(original, saved)
        self.assertEqual(result.count('-force_key_frames'), 1)
        self.assertEqual(option(result, '-force_key_frames'), '0,1,2')
        self.assertEqual(option(result, '-g'), '1000000')
        self.assertEqual(option(result, '-intra-refresh'), '0')
        self.assertEqual(option(result, '-single-slice-intra-refresh'), '0')

    def test_all_eight_modes_and_both_sources_share_one_gpu_capture_clock(self):
        for fps in (60, 75, 90, 100):
            for dimensions in ((1280, 720), (1920, 1080)):
                with self.subTest(fps=fps, dimensions=dimensions):
                    graphs = []
                    for output in (0, 1):
                        result = video.compatible_command(encoder_command(settings(fps=fps)),
                            dimensions=dimensions, output=dict(adapter=0, output=output, vendor_id=0x10de))
                        graph = option(result, '-filter_complex')
                        self.assertIn(f'framerate={fps}:', graph)
                        self.assertIn('source_clock=1:source_guard_us=3000', graph)
                        self.assertIn('fresh_wait_us=2000:delivery_delay_us=8000', graph)
                        self.assertIn('precise_clock=1:acquire_timeout=0', graph)
                        self.assertIn(f'width={dimensions[0]}:height={dimensions[1]}', graph)
                        self.assertNotIn('hwdownload', graph)
                        self.assertNotIn('select=', graph)
                        self.assertNotIn(',fps=', graph)
                        self.assertNotIn('-i', result)
                        self.assertEqual(option(result, '-latest_frame'), '1')
                        self.assertEqual(option(result, '-fps_mode'), 'passthrough')
                        self.assertEqual(option(result, '-thread_queue_size'), '1')
                        graphs.append(graph.replace(f'output_idx={output}', 'output_idx=TARGET'))
                    self.assertEqual(graphs[0], graphs[1])

    def test_preflight_and_stream_share_colour_and_nvenc_policy(self):
        graphs = []
        for frames in (0, 1):
            result = video.compatible_command(encoder_command(settings(), frames=frames))
            graph = option(result, '-filter_complex')
            graphs.append(graph)
            self.assertIn('format=nv12:desktop_sdr=1', graph)
            self.assertIn('range=limited', graph)
            self.assertIn('color_primaries=unknown:color_trc=unknown:colorspace=unknown', graph)
            for name, value in (('-c:v', 'h264_nvenc'), ('-profile:v', 'high'),
                                ('-coder', 'cabac'), ('-qp_cb_offset', '-4'),
                                ('-qp_cr_offset', '-4'), ('-bf', '0'), ('-tune', 'ull'),
                                ('-rc-lookahead', '0'), ('-multipass', 'qres'),
                                ('-async_encode', '1'), ('-refs', '1')):
                self.assertEqual(option(result, name), value)
            self.assertEqual('-latest_frame' in result, not frames)
            self.assertEqual(result[-3:], ['-f', 'null' if frames else 'avi', '-' if frames else 'pipe:1'])
        self.assertEqual(graphs[0], graphs[1])

    def test_upstream_bitrate_vbv_and_presets_survive_adaptation(self):
        for bitrate in (20, 32, 40):
            for preset in ('p1', 'p4'):
                with self.subTest(bitrate=bitrate, preset=preset):
                    original = encoder_command(settings(fps=100, bitrate_mbps=bitrate, preset=preset))
                    result = video.compatible_command(original)
                    for name in ('-b:v', '-maxrate', '-bufsize', '-preset'):
                        self.assertEqual(option(result, name), option(original, name))

    def test_desktop_advanced_options_change_the_real_native_command(self):
        for interval in (1, 3):
            for profile, coder in (('high', 'cabac'), ('baseline', 'cavlc')):
                original = encoder_command(settings(keyframe_seconds=interval, h264_profile=profile,
                                                     adaptive_quant=True, low_latency=False))
                result = video.compatible_command(original, startup_only=False)
                for name in ('-g', '-force_key_frames', '-spatial-aq', '-temporal-aq', '-profile:v'):
                    self.assertEqual(option(result, name), option(original, name))
                self.assertEqual(option(result, '-coder'), coder)
                self.assertEqual(result[-3:], ['-f', 'h264', 'pipe:1'])
                self.assertNotIn('-thread_queue_size', result)

    def test_wgc_preserves_upstream_encoder_choices_and_uses_stable_monitor(self):
        for profile in ('high', 'baseline'):
            original = encoder_command(BridgeSettings(None, Path('stock.exe'), capture='gfxcapture',
                h264_profile=profile, keyframe_seconds=1, adaptive_quant=True, low_latency=False))
            result = video.compatible_command(original, hmonitor=123, dimensions=(1280, 720), startup_only=False)
            source = option(result, '-i')
            self.assertIn('gfxcapture=hmonitor=123:', source)
            self.assertIn('width=1280:height=720', source)
            self.assertIn('display_border=0', source)
            self.assertNotIn('monitor_idx=', source)
            for name in ('-vf', '-g', '-force_key_frames', '-profile:v', '-spatial-aq', '-temporal-aq', '-intra-refresh'):
                self.assertEqual(option(result, name), option(original, name))
            for name in ('-latest_frame', '-async_encode', '-filter_complex'):
                self.assertNotIn(name, result)
            self.assertEqual(result[-3:], ['-f', 'h264', 'pipe:1'])
        startup = video.compatible_command(original, hmonitor=123, startup_only=True)
        self.assertEqual(option(startup, '-force_key_frames'), '0,1,2')
        self.assertEqual(option(startup, '-g'), '1000000')

    def test_non_nvidia_capture_explicitly_transfers_to_nvenc(self):
        result = video.compatible_command(encoder_command(settings()),
            output=dict(adapter=1, output=2, vendor_id=0x1002))
        graph = option(result, '-filter_complex')
        self.assertIn('d3d11va=cap:1', result)
        self.assertIn('cuda=enc:0', result)
        self.assertIn('output_idx=2', graph)
        self.assertIn('hwdownload,format=bgra', graph)
        self.assertIn('out_color_matrix=bt709:out_range=tv', graph)
        self.assertNotIn('scale_d3d11=', graph)
        self.assertEqual(option(result, '-c:v'), 'h264_nvenc')

    def test_upscaling_separates_rgb_resize_from_chroma_conversion(self):
        for dimensions, passes in (((1280, 720), 2), ((1920, 1080), 1), ((3440, 1440), 1)):
            result = video.compatible_command(encoder_command(settings()),
                output=dict(adapter=0, output=0, vendor_id=0x10de,
                            width=dimensions[0], height=dimensions[1]))
            graph = option(result, '-filter_complex')
            self.assertEqual(graph.count('scale_d3d11='), passes)
            self.assertNotIn('hwdownload', graph)

    def test_unknown_sources_and_software_encoder_are_rejected(self):
        wrong = encoder_command(settings())
        wrong[wrong.index('-c:v')+1] = 'libx264'
        for command, kwargs in (
            (wrong, {}),
            (encoder_command(BridgeSettings(None, Path('unused.exe'), capture='gfxcapture')), {}),
            (encoder_command(settings()), dict(hmonitor=123)),
            (encoder_command(settings()), dict(dimensions=(2560, 1440))),
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                video.compatible_command(command, **kwargs)

    def test_start_and_check_adapt_the_same_command_without_hardware_calls(self):
        command = encoder_command(settings())
        options = dict(output=dict(adapter=1, output=2), dimensions=(1280, 720))
        process = SimpleNamespace()
        with patch.object(video.subprocess, 'Popen', return_value=process) as start, \
             patch.object(video, 'configure_encoder_process', return_value={'status': 'fixture'}) as policy:
            self.assertIs(video.start_encoder(command, **options), process)
        policy.assert_called_once_with(process)
        self.assertEqual(process.desktop_scheduling, {'status': 'fixture'})
        with patch.object(video, 'run_cancellable', return_value='checked') as check:
            self.assertEqual(video.check_capture(command, stop='cancel', **options), 'checked')
        self.assertEqual(start.call_args.args[0], check.call_args.args[0])
        self.assertEqual(check.call_args.args[1], 'cancel')


if __name__ == '__main__':
    unittest.main()
