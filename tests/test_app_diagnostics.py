"""Diagnostics must describe the selected FFmpeg build, without running either binary."""
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from goggles_bridge.app import backend


class AppDiagnosticsTests(unittest.TestCase):
    def test_wgc_and_native_reports_identify_the_effective_encoder_binary(self):
        with tempfile.TemporaryDirectory() as folder:
            native, stock = Path(folder)/'native.exe', Path(folder)/'stock.exe'
            native.touch()
            stock.touch()
            for source, capture, expected in (
                    ('display', 'gfxcapture', stock), ('display', 'ddagrab', native),
                    ('virtual', 'gfxcapture', native)):
                with self.subTest(source=source, capture=capture):
                    app = object.__new__(backend.Desktop)
                    app._lock = threading.Lock()
                    app._state = dict(phase='idle', problem=None, log=None)
                    app._options = dict(source=source, capture=capture)
                    app._runtime = Mock()
                    app._ffmpeg, app._stock_ffmpeg = native, stock
                    app._display_path = app._device = None
                    app._preflight = lambda: {}
                    with patch.object(backend, 'WINDOWS', False), patch.object(backend, 'MAC', False), \
                         patch.object(backend.subprocess, 'run', return_value=SimpleNamespace(stdout='test build\n')) as run:
                        report = app.diagnostics()
                    self.assertIn(f'FFmpeg: {expected}', report)
                    self.assertEqual(run.call_args.args[0][0], str(expected))


if __name__ == '__main__':
    unittest.main()
