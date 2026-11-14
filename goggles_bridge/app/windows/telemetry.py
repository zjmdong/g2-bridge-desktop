"""Constant-work sender counters; sampled outside the USB/encoder thread."""
from collections import deque
import threading
import time


class SenderTelemetry:
    def __init__(self, emit, interval=.1, clock=time.perf_counter_ns):
        self.emit, self.interval, self.clock = emit, interval, clock
        self.snapshot = (0, 0, 0, 0)  # wire bytes, video frames, last USB duration, completion time
        self.stop = threading.Event()
        self.thread = None

    def record(self, size, video, started, ended):
        # One writer (SDK session thread), one atomic tuple publication under CPython.
        # No locks, disk access, formatting, per-frame IPC or history sorting here.
        wire, frames, elapsed, completed = self.snapshot
        self.snapshot = (wire + size, frames + int(video), ended-started if video else elapsed,
                         ended if video else completed)

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True, name='sender-statistics')
        self.thread.start()

    def run(self):
        history = deque([(self.clock(), 0, 0)], maxlen=12)
        while not self.stop.wait(self.interval):
            now = self.clock()
            wire, frames, elapsed, completed = self.snapshot
            history.append((now, wire, frames))
            while len(history) > 2 and history[1][0] <= now-1_000_000_000:
                history.popleft()
            start, old_wire, old_frames = history[0]
            seconds = max((now-start)/1e9, 1e-9)
            self.emit('live_stats', fps=round((frames-old_frames)/seconds, 2),
                      bandwidth_mbps=round((wire-old_wire)*8/seconds/1e6, 3),
                      send_ms=round(elapsed/1e6, 3) if now-completed < 1e9 else None,
                      frames=frames, wire_bytes=wire, interval_ms=round(self.interval*1000))

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)
