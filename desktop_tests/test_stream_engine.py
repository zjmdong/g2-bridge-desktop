import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from desktop_app.stream_engine import AsyncSessionLog, DesktopBridgeEngine
from goggles_bridge.engine import BridgeSettings


class MemoryOutput:
    def __init__(self):
        self.parts = []
        self.closed = False

    def write(self, text):
        self.parts.append(text)

    def flush(self):
        pass

    def close(self):
        self.closed = True


class AsyncSessionLogTests(unittest.TestCase):
    def test_blocked_storage_does_not_block_sender_or_unbound_stop(self):
        entered, release = threading.Event(), threading.Event()

        class SlowOutput(MemoryOutput):
            def write(self, text):
                entered.set()
                release.wait(5)
                super().write(text)

        output = SlowOutput()
        log = AsyncSessionLog('unused', capacity=8, close_timeout=.03,
                              open_file=lambda _: output)
        log.enqueue(dict(event='starting'))
        self.assertTrue(entered.wait(1))
        try:
            started = time.perf_counter()
            for index in range(10_000):
                log.enqueue(dict(event='stats', frames=index))
                log.enqueue(dict(event='connected', attempt=index))
            log.enqueue(dict(event='error', message='device removed'))
            log.enqueue(dict(event='session_ended'))
            log.enqueue(dict(event='stopped'))
            self.assertLess(time.perf_counter()-started, 2)
            self.assertLessEqual(len(log.pending), 8)
            self.assertLessEqual(len(log.overflow), len(log.STATE_KINDS)+1)
            self.assertGreater(log.coalesced, 0)
            started = time.perf_counter()
            self.assertFalse(log.close())
            self.assertLess(time.perf_counter()-started, .5)
        finally:
            release.set()
            log.thread.join(timeout=2)
        self.assertFalse(log.thread.is_alive())
        self.assertTrue(output.closed)
        rows = [json.loads(text) for text in output.parts]
        self.assertEqual(rows[-1]['event'], 'stopped')
        self.assertIn('error', [r['event'] for r in rows])
        self.assertIn('session_ended', [r['event'] for r in rows])
        self.assertEqual([r for r in rows if r['event']=='stats'][-1]['frames'], 9999)


class DesktopBridgeEngineTests(unittest.TestCase):
    def settings(self):
        return BridgeSettings(dll=Path('unused.dll'), ffmpeg=Path('unused.exe'))

    def test_sdk_session_clock_and_file_lifetime_are_preserved(self):
        class SimulatedEngine(DesktopBridgeEngine):
            def _session(self, attempt):
                self.emit('control_send', hex='not-persisted')
                self.emit('control_receive', hex='not-persisted')
                self.emit('streaming', encoder_pid=123)
                self.emit('stats', frames=100)
                self.stop_event.set()

        callbacks = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'session.jsonl'
            engine = SimulatedEngine(self.settings(), path,
                on_event=lambda row: callbacks.append((threading.get_ident(), row)))
            engine.run()
            rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            self.assertTrue(engine.log.stream.closed)
            self.assertGreater(engine.log.started, 0)
            self.assertTrue(engine.log_complete)
            self.assertEqual([r['event'] for r in rows], ['starting','streaming','stats','stopped'])
            self.assertTrue(all(r['seconds'] >= 0 for r in rows))
            self.assertEqual(rows, [r for _, r in callbacks])
            self.assertTrue(all(t == threading.get_ident() for t, _ in callbacks))

    def test_sdk_exception_is_preserved_and_terminal_events_are_drained(self):
        class FailingEngine(DesktopBridgeEngine):
            def _session(self, attempt):
                raise RuntimeError('simulated encoder failure')

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'session.jsonl'
            engine = FailingEngine(self.settings(), path)
            with self.assertRaisesRegex(RuntimeError, 'simulated encoder failure'):
                engine.run()
            self.assertTrue(engine.log_complete)
            rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual([r['event'] for r in rows], ['starting','error','stopped'])
            self.assertEqual(rows[1]['message'], 'simulated encoder failure')

    def test_disk_failure_does_not_change_session_callbacks(self):
        class SimulatedEngine(DesktopBridgeEngine):
            def _session(self, attempt):
                self.emit('streaming', encoder_pid=123)
                self.stop_event.set()

        def fail_open(_):
            raise OSError('simulated disk failure')

        callbacks = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'session.jsonl'
            engine = SimulatedEngine(self.settings(), path, on_event=callbacks.append,
                log_factory=lambda p: AsyncSessionLog(p, open_file=fail_open))
            engine.run()
            self.assertFalse(engine.log_complete)
            self.assertIn('simulated disk failure', engine.journal.error)
            self.assertEqual([r['event'] for r in callbacks], ['starting','streaming','stopped'])
            self.assertTrue(engine.log.stream.closed)


if __name__ == '__main__':
    unittest.main()
