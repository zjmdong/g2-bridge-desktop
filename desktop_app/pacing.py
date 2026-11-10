"""Bounded frame pacing at the SDK transport boundary; never drops references."""
import time


class FramePacer:
    def __init__(self, fps, clock=time.perf_counter, sleep=time.sleep):
        self.period = 1 / fps
        self.clock, self.sleep = clock, sleep
        self.deadline = None

    def wait(self):
        now = self.clock()
        if self.deadline is None:
            # Absorb capture scheduling jitter with at most 20 ms of initial lead.
            self.deadline = now + min(.02, self.period * 2)
        delay = self.deadline - now
        if delay > 0:
            # Python 3.11 uses a high-resolution Windows waitable timer. No spin.
            self.sleep(delay)
        now = self.clock()
        # A delayed capture must not trigger a burst of backlogged video frames.
        self.deadline = max(self.deadline + self.period, now + self.period / 2)
