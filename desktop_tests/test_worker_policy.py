"""Check actual worker metadata without opening displays, encoders or USB."""
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from desktop_app.settings import Settings
from desktop_app.video import FRESH_WAIT_US, DELIVERY_DELAY_US
from desktop_app.worker import stream


class WorkerPolicyTests(unittest.TestCase):
    def test_capture_and_starting_events_report_native_and_sdk_pacing_separately(self):
        for fps in (60, 75, 90, 100):
            for resolution in ('720p', '1080p'):
                with self.subTest(fps=fps, resolution=resolution), tempfile.TemporaryDirectory() as directory:
                    settings = Settings(fps=fps, resolution=resolution)
                    rows, journal_rows = [], []
                    telemetry = Mock()

                    def emit(event, **fields):
                        rows.append(dict(event=event, **fields))

                    def engine_factory(bridge, log, **kwargs):
                        engine = Mock()
                        def run():
                            row = dict(event='starting', **asdict(bridge))
                            kwargs['on_event'](row)
                            # The real desktop engine journals after its callback.
                            journal_rows.append(dict(row))
                        engine.run.side_effect = run
                        return engine

                    target = dict(device='test-output', width=1920, height=1080, hz=fps)
                    output = dict(adapter=0, output=1, vendor_id=0x10de)
                    with patch('desktop_app.worker.probe', return_value={'compatibility': {'allowed': True}}), \
                         patch('desktop_app.display_session.capture_target', return_value=nullcontext(target)), \
                         patch('desktop_app.dxgi.select_output', return_value=output), \
                         patch('desktop_app.settings.find_dll', return_value=Path('unused.dll')), \
                         patch('desktop_app.settings.ffmpeg_path', return_value=Path('unused.exe')), \
                         patch('desktop_app.worker.check_encoder', return_value=None), \
                         patch('desktop_app.worker.data_dir', return_value=Path(directory)), \
                         patch('desktop_app.telemetry.SenderTelemetry', return_value=telemetry), \
                         patch('desktop_app.worker.DesktopBridgeEngine', side_effect=engine_factory), \
                         patch('desktop_app.worker.start_encoder') as start_encoder:
                        self.assertEqual(stream(settings, threading.Event(), emit), 0)
                    start_encoder.assert_not_called()
                    telemetry.start.assert_called_once_with()
                    telemetry.close.assert_called_once_with()
                    capture = next(row for row in rows if row['event'] == 'capture_source')
                    starting = next(row for row in rows if row['event'] == 'starting')
                    self.assertEqual(journal_rows, [starting])
                    self.assertEqual(capture['capture_sampling_fps'], fps)
                    self.assertEqual(starting['capture_fps'], fps)
                    self.assertEqual(starting['adapter'], 'desktop-native-latest-v6')
                    for row in (capture, starting):
                        self.assertEqual(row['encoder'], 'h264_nvenc')
                        self.assertEqual(row['capture_fresh_wait_us'], FRESH_WAIT_US)
                        self.assertEqual(row['native_delivery_pacing'], 'capture_deadline')
                        self.assertEqual(row['delivery_delay_us'], DELIVERY_DELAY_US)
                        self.assertEqual(row['delivery_wait_policy'], 'remaining only; late frames immediate')
                        self.assertFalse(row['sender_pacing'])
                        self.assertEqual(row['sdk_sender_mode'], 'immediate')


if __name__ == '__main__':
    unittest.main()
