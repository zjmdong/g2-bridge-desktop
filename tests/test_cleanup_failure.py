"""Stopping a stream must not turn a failed virtual-display cleanup into success."""
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from goggles_bridge.app import backend
from goggles_bridge.app.windows import events, runtime, worker
from goggles_bridge.app.windows.system import Cancelled
from goggles_bridge.engine import BridgeSettings


class CleanupFailureTests(unittest.TestCase):
    def test_worker_reports_real_cleanup_failure_even_after_stop(self):
        stop = threading.Event()
        stop.set()
        writer = Mock()
        stdin = SimpleNamespace(reconfigure=Mock(), readline=lambda: '{}\n')
        stdout = SimpleNamespace(reconfigure=Mock())
        with patch.object(worker.sys, 'argv', ['worker']), \
             patch.object(worker.sys, 'stdin', stdin), patch.object(worker.sys, 'stdout', stdout), \
             patch.object(worker.threading, 'Event', return_value=stop), \
             patch.object(worker.threading, 'Thread'), \
             patch.object(events, 'EventWriter', return_value=writer), \
             patch.object(worker, 'stream', side_effect=RuntimeError('virtual display cleanup failed')):
            result = worker.main()
        self.assertEqual(result, 1)
        writer.emit.assert_called_once_with('error', message='virtual display cleanup failed')
        writer.close.assert_called_once()

    def test_explicit_cancellation_remains_a_normal_exit(self):
        stop = threading.Event()
        stop.set()
        writer = Mock()
        stdin = SimpleNamespace(reconfigure=Mock(), readline=lambda: '{}\n')
        stdout = SimpleNamespace(reconfigure=Mock())
        with patch.object(worker.sys, 'argv', ['worker']), \
             patch.object(worker.sys, 'stdin', stdin), patch.object(worker.sys, 'stdout', stdout), \
             patch.object(worker.threading, 'Event', return_value=stop), \
             patch.object(worker.threading, 'Thread'), \
             patch.object(events, 'EventWriter', return_value=writer), \
             patch.object(worker, 'stream', side_effect=Cancelled()):
            result = worker.main()
        self.assertEqual(result, 0)
        writer.emit.assert_not_called()
        writer.close.assert_called_once()

    def process(self, rows=(), code=1):
        process = Mock()
        process.stdin = io.StringIO()
        process.stdout = io.StringIO(''.join(json.dumps(row)+'\n' for row in rows))
        process.wait.return_value = process.poll.return_value = code
        return process

    def test_parent_preserves_worker_failure_while_cancellation_is_requested(self):
        stop = threading.Event()
        stop.set()
        rows = [dict(event='releasing_display'), dict(event='error', message='virtual display cleanup failed')]
        process = self.process(rows)
        seen = []
        settings = BridgeSettings(None, None, capture='ddagrab')
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(runtime, 'worker_command', return_value=('worker.exe', [])), \
             patch.object(runtime.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, 'virtual display cleanup failed'):
                runtime.WindowsRuntime().run(settings, dict(source='virtual'), Path(folder)/'log.jsonl', stop, seen.append)
        self.assertEqual(seen, rows)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)

    def test_parent_reports_unexplained_nonzero_exit_even_after_stop(self):
        stop = threading.Event()
        stop.set()
        process = self.process(code=7)
        settings = BridgeSettings(None, None, capture='ddagrab')
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(runtime, 'worker_command', return_value=('worker.exe', [])), \
             patch.object(runtime.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, r'worker stopped \(7\)'):
                runtime.WindowsRuntime().run(settings, dict(source='virtual'), Path(folder)/'log.jsonl', stop, Mock())

    def test_backend_error_survives_later_display_release_notification(self):
        # A state assertion only: constructing a real Desktop would start platform discovery.
        app = object.__new__(backend.Desktop)
        app._lock = threading.Lock()
        app._state = dict(phase='streaming', problem=None, stats=None, oversize=0, log=None)
        app._event(dict(event='error', message='virtual display cleanup failed'))
        app._event(dict(event='releasing_display'))
        self.assertEqual(app._state['phase'], 'error')
        self.assertEqual(app._state['problem']['message'], 'virtual display cleanup failed')


if __name__ == '__main__':
    unittest.main()
