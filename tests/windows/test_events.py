"""A stalled UI pipe cannot block the stream worker's event producer."""
import io
import threading
import time
import unittest

from goggles_bridge.app.windows.events import EventWriter


class EventWriterTests(unittest.TestCase):
    def test_slow_consumer_keeps_sender_nonblocking_and_backlog_bounded(self):
        entered, release = threading.Event(), threading.Event()
        class SlowOutput(io.StringIO):
            def write(self, value):
                entered.set()
                release.wait(3)
                return super().write(value)
        output = SlowOutput()
        writer = EventWriter(output)
        writer.emit('starting')
        self.assertTrue(entered.wait(1))
        try:
            started = time.perf_counter()
            for index in range(5000):
                writer.emit('stats', frames=index)
            writer.emit('stopped')
            self.assertLess(time.perf_counter()-started, 1)
            self.assertLessEqual(writer.events.qsize(), 128)
        finally:
            release.set()
            writer.close()
        self.assertFalse(writer.thread.is_alive())
        self.assertIn('"event": "stopped"', output.getvalue())


if __name__ == '__main__':
    unittest.main()
