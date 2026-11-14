from dataclasses import replace
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from goggles_bridge.control import V1Stream
from goggles_bridge.engine import (BridgeEngine, BridgeSettings, MAX_FRAME_BYTES, MAX_VBV_BITS, check_encoder,
                                   encoder_command, prioritize_gpu)
from goggles_bridge.mac_capture import helper_path, supported
from goggles_bridge.session import SessionError
from goggles_bridge.usb_transport import DeviceNotFoundError, UsbTransportError
from avi_fixture import stream as avi_stream


AUD = b'\0\0\0\1\x09\xf0'


class EncoderOutput:
    def __init__(self, stopped, eof=False, framed=False, packets=(AUD + b'\0\0\0\1\x65test-picture',)):
        self.stopped = stopped
        self.first = True
        self.eof = eof
        self.framed = framed
        self.packets = list(packets)

    def read(self, _size):
        if self.eof:
            return b''
        if self.first:
            self.first = False
            return avi_stream(self.packets) if self.framed else b''.join(self.packets)*3
        self.stopped.wait(2)
        return b''

    def close(self):
        pass


class FakeEncoder:
    pid = 123

    def __init__(self, eof=False, framed=False, **output):
        self.stopped = threading.Event()
        self.stdout = EncoderOutput(self.stopped, eof, framed, **output)
        self.terminated = False

    def poll(self):
        return 0 if self.stopped.is_set() else None

    def terminate(self):
        self.terminated = True
        self.stopped.set()

    def wait(self, timeout):
        return 0


class FakeUsb:
    def __init__(self, stop, *, wrong_model=False, disconnect=False):
        self.stop = stop
        self.wrong_model = wrong_model
        self.disconnect = disconnect
        self.incoming = queue.Queue()
        self.decoder = V1Stream()
        self.video = []
        self.mode = False
        self.closed = False

    def write(self, data):
        for request in self.decoder.feed(data):
            command = request.command_set, request.command_id
            if command == (11, 83):
                if not self.mode:
                    raise AssertionError('Video arrived before simulator acknowledgement')
                if self.disconnect:
                    raise UsbTransportError('Unplugged during video')
                self.video.append(request)
                self.stop.set()
                continue
            payload = b'\0'
            if command == (0, 255):
                payload += b'E3T ZV902' if self.wrong_model else b'E3T ZV900 AC'
            if command == (11, 26):
                self.mode = True
            response = replace(request, sender_type=request.receiver_type, sender_id=request.receiver_id,
                receiver_type=request.sender_type, receiver_id=request.sender_id, is_response=1, ack=2, payload=payload)
            self.incoming.put(response.serialize())

    def read(self, timeout_ms):
        try:
            return self.incoming.get(timeout=timeout_ms/1000)
        except queue.Empty:
            return b''

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True


class EngineTests(unittest.TestCase):
    def settings(self, **kwargs):
        return BridgeSettings(Path('driver.dll'), Path('ffmpeg.exe'), **kwargs)

    def run_case(self, factory, stop, *, encoder_factory=None, settings=None):
        events, encoders = [], []
        def create_encoder(*args, **kwargs):
            encoder = encoder_factory() if encoder_factory else FakeEncoder(framed=args[0][-2]=='avi')
            encoders.append(encoder)
            return encoder
        with tempfile.TemporaryDirectory() as folder:
            engine = BridgeEngine(settings or self.settings(), Path(folder)/'run.jsonl', stop_event=stop,
                on_event=events.append, transport_factory=factory, process_factory=create_encoder,
                retry_delay=.001, duration=2)
            engine.run()
        return events, encoders

    def test_handshake_video_and_stop_release_owned_resources(self):
        stop = threading.Event()
        usb = FakeUsb(stop)
        events, encoders = self.run_case(lambda _: usb, stop)
        self.assertTrue(usb.closed)
        self.assertTrue(usb.video)
        self.assertTrue(encoders[0].terminated)
        names = [r['event'] for r in events]
        self.assertLess(names.index('ready'), names.index('streaming'))
        self.assertEqual(names[-1], 'stopped')

    def test_disconnect_restarts_both_handshake_and_encoder(self):
        stop = threading.Event()
        devices = [FakeUsb(stop, disconnect=True), FakeUsb(stop)]
        calls = []
        def factory(_):
            result = devices[len(calls)]
            calls.append(result)
            return result
        events, encoders = self.run_case(factory, stop)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(d.closed for d in devices))
        self.assertTrue(all(p.terminated for p in encoders))
        self.assertEqual(sum(e['event']=='ready' for e in events), 2)
        self.assertTrue(any(e['event']=='waiting' for e in events))

    def test_low_latency_sends_one_complete_picture_before_any_next_frame(self):
        stop = threading.Event()
        usb = FakeUsb(stop)
        events, encoders = self.run_case(lambda _: usb, stop, settings=self.settings(low_latency=True))
        self.assertEqual(b''.join(p.payload[32:] for p in usb.video), b'\0\0\0\1\x65test-picture')
        self.assertTrue(usb.closed)
        self.assertTrue(encoders[0].terminated)
        self.assertTrue(any(e['event']=='streaming' for e in events))

    def test_gpu_priority_is_best_effort(self):
        self.assertFalse(prioritize_gpu(FakeEncoder()))
        if sys.platform != 'win32':
            return
        # The kernel accepts the call only after the process touches the graphics stack, as FFmpeg has by its first frame
        # A Windows venv's python.exe can be a forwarding launcher: its Popen
        # handle then belongs to a different process from the graphics caller.
        interpreter = getattr(sys, '_base_executable', sys.executable)
        process = subprocess.Popen([interpreter, '-c', "import ctypes; ctypes.WinDLL('user32').GetDesktopWindow()"
                                    "; print('ready', flush=True); import time; time.sleep(5)"],
                                   stdout=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            self.assertEqual(process.stdout.readline().strip(), b'ready')
            self.assertTrue(prioritize_gpu(process))
        finally:
            process.kill()
            process.wait(timeout=5)
            process.stdout.close()

    def test_absent_device_can_be_stopped_while_waiting(self):
        stop = threading.Event()
        def missing(_):
            stop.set()
            raise DeviceNotFoundError('No goggles')
        events, encoders = self.run_case(missing, stop)
        self.assertEqual(encoders, [])
        self.assertEqual(events[-1]['event'], 'stopped')

    def test_wrong_model_is_fatal_and_never_starts_encoder(self):
        stop = threading.Event()
        usb = FakeUsb(stop, wrong_model=True)
        with self.assertRaises(SessionError):
            self.run_case(lambda _: usb, stop, encoder_factory=lambda: self.fail('Must not encode'))
        self.assertTrue(usb.closed)
        self.assertFalse(usb.video)

    def test_failed_handshake_leaves_no_encoder_log(self):
        stop = threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            engine = BridgeEngine(self.settings(), Path(folder)/'run.jsonl', stop_event=stop,
                                  transport_factory=lambda _: FakeUsb(stop, wrong_model=True))
            with self.assertRaises(SessionError):
                engine.run()
            self.assertEqual([path.name for path in Path(folder).iterdir()], ['run.jsonl'])

    def test_encoder_eof_is_fatal_and_releases_usb(self):
        stop = threading.Event()
        usb = FakeUsb(stop)
        with self.assertRaisesRegex(RuntimeError, 'Capture ended'):
            self.run_case(lambda _: usb, stop, encoder_factory=lambda: FakeEncoder(eof=True))
        self.assertTrue(usb.closed)

    def test_gpu_capture_preserves_verified_encoder_contract(self):
        command = encoder_command(self.settings())
        source = command[command.index('-i')+1]
        self.assertIn('scale_aspect', source)
        self.assertIn('max_framerate=1000:', source)
        self.assertNotIn('hwdownload', command[command.index('-vf')+1])
        self.assertIn('strip_fps=1', command[command.index('-vf')+1])
        for key, value in (('-r','100'), ('-level:v','5.1'), ('-bf','0'), ('-aud','1'), ('-bufsize','400000')):
            self.assertEqual(command[command.index(key)+1], value)
        command = encoder_command(self.settings(fps=60, capture='ddagrab'))
        self.assertEqual(command[command.index('-level:v')+1], '4.2')
        self.assertIn('force_original_aspect_ratio=decrease', command[command.index('-vf')+1])

    def test_capture_ceiling_defaults_and_explicit_override(self):
        for capture in ('ddagrab', 'avfoundation', 'screencapturekit'):
            with self.subTest(capture=capture):
                self.assertEqual(self.settings(capture=capture).capture_fps, 240)
        settings = self.settings(capture_fps=144)
        command = encoder_command(settings)
        self.assertIn('max_framerate=144:', command[command.index('-i')+1])

    def test_frame_rates_reach_every_capture_backend(self):
        for fps in (60, 75, 90, 100):
            for capture in ('gfxcapture', 'ddagrab', 'avfoundation', 'screencapturekit'):
                with self.subTest(fps=fps, capture=capture):
                    command = encoder_command(self.settings(fps=fps, capture=capture))
                    if capture == 'screencapturekit':
                        self.assertEqual(command[command.index('--fps')+1], str(fps))
                        continue
                    if capture == 'ddagrab':
                        self.assertIn(f'framerate={fps}:', command[command.index('-i')+1])
                    else:
                        self.assertEqual(command[command.index('-r')+1], str(fps))
                    bufsize = 40_000_000//fps if capture == 'avfoundation' else min(40_000_000//fps, MAX_VBV_BITS)
                    for key, value in (('-g', str(fps*3)), ('-bufsize', str(bufsize)),
                                       ('-level:v', '4.2' if fps == 60 else '5.1'), ('-bf', '0')):
                        self.assertEqual(command[command.index(key)+1], value)
        for fps in (0, 65, 120):
            with self.assertRaises(ValueError):
                self.settings(fps=fps)
        with self.assertRaises(ValueError):
            self.settings(fps=90, capture_fps=75)

    def test_mac_capture_keeps_stream_contract_and_adds_delimiters(self):
        for low_latency, tail in ((True, ['-f', 'avi', 'pipe:1']), (False, ['-f', 'h264', 'pipe:1'])):
            with self.subTest(low_latency=low_latency):
                command = encoder_command(self.settings(capture='avfoundation', display_index=1,
                                                        low_latency=low_latency))
                self.assertEqual(command[command.index('-i')+1], 'Capture screen 1:none')
                self.assertIn('pad=1920:1080', command[command.index('-vf')+1])
                for key, value in (('-c:v','h264_videotoolbox'), ('-flags','+low_delay'), ('-r','100'),
                                   ('-level:v','5.1'), ('-bf','0'), ('-bufsize','400000'),
                                   ('-bsf:v','h264_metadata=aud=insert')):
                    self.assertEqual(command[command.index(key)+1], value)
                self.assertEqual(command[-3:], tail)
        command = encoder_command(self.settings(capture='avfoundation', h264_profile='baseline'))
        self.assertEqual(command[command.index('-profile:v')+1], 'constrained_baseline')
        settings = self.settings(capture='avfoundation')
        fail = lambda stderr: lambda command, **_: subprocess.CompletedProcess(command, 1, '', stderr)
        self.assertIn('brew upgrade ffmpeg', check_encoder(settings, fail('Error opening output files: Filter not found')))
        self.assertIn('screen recording', check_encoder(settings, fail('Error opening input files: Input/output error')))

    def test_windows_default_keeps_buffer_small_and_repeats_idr(self):
        settings = self.settings()
        command = encoder_command(settings)
        for flag, expected in (('-preset', 'p1'), ('-b:v', '32000000'), ('-maxrate', '32000000'),
                               ('-bufsize', '400000'), ('-bf', '0'), ('-delay', '0'), ('-r', '100'),
                               ('-multipass', 'qres'), ('-intra-refresh', '1'),
                               ('-single-slice-intra-refresh', '0'), ('-forced-idr', '1'),
                               ('-force_key_frames', 'expr:not(mod(n,300))+lt(n,300)*not(mod(n,10))')):
            self.assertEqual(command[command.index(flag)+1], expected)
        command = encoder_command(self.settings(fps=75, keyframe_seconds=1))
        self.assertEqual(command[command.index('-force_key_frames')+1], 'expr:not(mod(n,75))+lt(n,75)*not(mod(n,7))')
        self.assertEqual(command[-3:], ['-f', 'avi', 'pipe:1'])
        for capture in ('gfxcapture', 'ddagrab'):
            for fps in (60, 75, 90, 100):
                for bitrate in (8, 20, 24, 32):
                    with self.subTest(capture=capture, fps=fps, bitrate=bitrate):
                        if bitrate*1_000_000 > fps*8*50_000:
                            with self.assertRaises(ValueError):
                                self.settings(capture=capture, fps=fps, bitrate_mbps=bitrate)
                            continue
                        command = encoder_command(self.settings(capture=capture, fps=fps, bitrate_mbps=bitrate))
                        self.assertEqual(command[command.index('-bufsize')+1], str(min(min(bitrate, 20)*2_000_000//fps, MAX_VBV_BITS)))
                        self.assertEqual(command[command.index('-intra-refresh')+1], '1')
                        self.assertEqual(command[command.index('-single-slice-intra-refresh')+1], '0')
        for capture in ('avfoundation', 'screencapturekit'):
            settings_mac = self.settings(capture=capture)
            self.assertEqual(settings_mac.bitrate_mbps, 20)
            self.assertNotIn('-intra-refresh', encoder_command(settings_mac))
        stop = threading.Event()
        events, _ = self.run_case(lambda _: FakeUsb(stop), stop, settings=settings)
        self.assertTrue(events[0]['intra_refresh'])
        self.assertEqual(events[0]['multipass'], 'qres')
        self.assertEqual(events[0]['bitrate_mbps'], 32)

    def test_screencapturekit_helper_gets_stream_settings(self):
        command = encoder_command(BridgeSettings(None, None, capture='screencapturekit', display_index=1,
                                                 show_cursor=False, low_latency=False))
        self.assertEqual(Path(command[0]), helper_path())
        for key, value in (('--display', '1'), ('--fps', '100'), ('--capture-fps', '240'), ('--bitrate', '20000000'),
                           ('--keyframe-seconds', '3'), ('--profile', 'high'), ('--format', 'h264')):
            self.assertEqual(command[command.index(key)+1], value)
        self.assertEqual(command[-1], '--hide-cursor')
        for version, expected in (('11.7.10', False), ('12.2', False), ('12.3', True), ('12.3.1', True), ('27.0', True)):
            self.assertIs(supported(version), expected, version)

    def test_low_latency_only_changes_local_framing_and_padding(self):
        command = encoder_command(self.settings(low_latency=True))
        for key, value in (('-r','100'), ('-b:v','32000000'), ('-preset','p1'), ('-bf','0'),
                           ('-bufsize','400000'), ('-bsf:v','filter_units=remove_types=12'),
                           ('-thread_queue_size','1')):
            self.assertEqual(command[command.index(key)+1], value)
        self.assertEqual(command[-3:], ['-f', 'avi', 'pipe:1'])

    def test_quality_profile_keeps_latency_and_capture_settings(self):
        for low_latency in (False, True):
            with self.subTest(low_latency=low_latency):
                baseline = encoder_command(self.settings(low_latency=low_latency))
                candidate = encoder_command(self.settings(low_latency=low_latency, h264_profile='high'))
                baseline[baseline.index('-profile:v')+1] = 'high'
                self.assertEqual(candidate, baseline)
        with self.assertRaises(ValueError):
            self.settings(h264_profile='unsupported')

    def test_frame_limit_caps_the_buffer_and_bitrate(self):
        default = encoder_command(self.settings())
        self.assertEqual(default[default.index('-bufsize')+1], '400000')
        # Two frames at 60 fps would exceed the goggles' frame limit
        for capture in ('gfxcapture', 'ddagrab'):
            with self.subTest(capture=capture):
                command = encoder_command(self.settings(capture=capture, fps=60))
                self.assertEqual(command[command.index('-bufsize')+1], str(MAX_VBV_BITS))
        with self.assertRaisesRegex(ValueError, 'At 60 fps, use at most 24 Mbps'):
            self.settings(fps=60, bitrate_mbps=30)
        with self.assertRaisesRegex(ValueError, 'At 90 fps, use at most 32 Mbps'):
            self.settings(fps=90, bitrate_mbps=40)
        self.settings(fps=100, bitrate_mbps=40)
        for capture in ('avfoundation', 'screencapturekit'):
            with self.subTest(capture=capture), self.assertRaisesRegex(ValueError, 'macOS'):
                self.settings(capture=capture, bitrate_mbps=30)

    def test_adaptive_quantization_is_opt_in_and_only_adds_its_options(self):
        default = encoder_command(self.settings())
        self.assertNotIn('-spatial-aq', default)
        command = encoder_command(self.settings(adaptive_quant=True))
        at = command.index('-spatial-aq')
        self.assertEqual(command[at:at+4], ['-spatial-aq', '1', '-temporal-aq', '1'])
        self.assertEqual(command[:at] + command[at+4:], default)
        for bad in (dict(adaptive_quant=1), dict(adaptive_quant=True, capture='avfoundation')):
            with self.subTest(**bad), self.assertRaises(ValueError):
                self.settings(**bad)

    def test_oversize_frame_restarts_only_the_windows_encoder(self):
        idr, inter = AUD + b'\0\0\0\1\x65', AUD + b'\0\0\0\1\x41'
        packets = [idr + bytes(MAX_FRAME_BYTES), inter + b'lost', idr + b'next']
        # The guard covers only the verified NVENC cap, so macOS frames are sent unchanged
        for capture in ('gfxcapture', 'screencapturekit'):
            with self.subTest(capture=capture):
                stop = threading.Event()
                usb = FakeUsb(stop)
                encoders = iter([FakeEncoder(framed=True, packets=packets),
                                 FakeEncoder(framed=True, packets=[idr+b'next'])])
                events, _ = self.run_case(lambda _: usb, stop, settings=self.settings(capture=capture),
                                          encoder_factory=lambda: next(encoders))
                self.assertEqual(b'next' in usb.video[0].payload, capture == 'gfxcapture')
                self.assertFalse(any(b'lost' in packet.payload for packet in usb.video))
                dropped = [e for e in events if e['event'] == 'oversize_frame']
                self.assertEqual(len(dropped), capture == 'gfxcapture')
                self.assertTrue(all(e['limit'] == MAX_FRAME_BYTES for e in dropped))

    def test_silent_capture_restarts_the_encoder_unless_it_never_sent_a_picture(self):
        stop = threading.Event()
        usb = FakeUsb(threading.Event())
        started = []
        def encoder():
            started.append(1)
            if len(started) == 3:
                stop.set()
            return FakeEncoder(framed=True)
        with mock.patch('goggles_bridge.engine.SILENT_SECONDS', .05):
            events, encoders = self.run_case(lambda _: usb, stop, encoder_factory=encoder)
            self.assertEqual(len(usb.video), 2)
            self.assertEqual([e['event'] for e in events].count('capture_restart'), 2)
            self.assertTrue(all(e.terminated for e in encoders))
            with self.assertRaisesRegex(RuntimeError, 'No video from display'):
                self.run_case(lambda _: FakeUsb(threading.Event()), threading.Event(),
                              encoder_factory=lambda: FakeEncoder(framed=True, packets=()))

    def test_encoder_check_runs_one_frame_and_explains_missing_features(self):
        calls = []
        def run(stderr, code=1):
            def fake(command, **_):
                calls.append(command)
                return subprocess.CompletedProcess(command, code, '', stderr)
            return fake
        settings = self.settings()
        self.assertIsNone(check_encoder(settings, run('', 0)))
        self.assertEqual(calls[0][:-5], encoder_command(settings)[:-3])
        self.assertEqual(calls[0][-5:], ['-frames:v', '1', '-f', 'null', '-'])
        self.assertIn('--capture ddagrab', check_encoder(settings, run('Error opening input files: Filter not found')))
        self.assertIn('NVIDIA encoder', check_encoder(settings, run('Error opening output files: Encoder not found')))
        self.assertIn('OpenEncodeSessionEx failed', check_encoder(settings, run('a\nb\nOpenEncodeSessionEx failed')))
