"""Keep diagnostic disk I/O out of the unchanged SDK's session thread."""
from collections import deque
import json
import math
from pathlib import Path
import threading
import time

from goggles_bridge.engine import BridgeEngine


class AsyncSessionLog:
    """Bounded, best-effort diagnostics with a finite shutdown wait.

    Ordinary rows retain their order. If storage stalls and the queue fills,
    retain the most recent row of each SDK state kind instead of blocking the
    session. In particular, error/session_ended/stopped have separate slots.
    The condition protects only small in-memory operations, never file I/O.
    """
    STATE_KINDS = frozenset(('starting', 'connected', 'ready', 'streaming',
        'waiting', 'oversize_frame', 'encoder_restart', 'stats', 'error',
        'session_ended', 'stopped'))

    def __init__(self, path, *, capacity=128, close_timeout=2., open_file=None):
        if type(capacity) is not int or capacity < 1:
            raise ValueError('Invalid session log capacity')
        if not math.isfinite(close_timeout) or close_timeout < 0:
            raise ValueError('Invalid session log close timeout')
        self.path = Path(path)
        self.capacity = capacity
        self.close_timeout = close_timeout
        self.open_file = open_file or (lambda path: path.open('a', encoding='utf-8'))
        self.pending = deque()
        self.overflow = {}
        self.condition = threading.Condition()
        self.sequence = 0
        self.closing = False
        self.coalesced = 0
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True, name='session-log')
        self.thread.start()

    def enqueue(self, row):
        with self.condition:
            if self.closing:
                return
            record = (self.sequence, dict(row))
            self.sequence += 1
            if len(self.pending) < self.capacity:
                self.pending.append(record)
            else:
                kind = row['event'] if row['event'] in self.STATE_KINDS else 'other'
                if kind in self.overflow:
                    self.coalesced += 1
                self.overflow[kind] = record
            self.condition.notify()

    def _run(self):
        output = None
        try:
            while True:
                with self.condition:
                    while not self.pending and not self.overflow and not self.closing:
                        self.condition.wait()
                    if not self.pending and not self.overflow:
                        break
                    batch = list(self.pending) + list(self.overflow.values())
                    self.pending.clear()
                    self.overflow.clear()
                # SDK run() creates the path in exclusive mode before its first
                # emit. Open append only after that row, never in __init__.
                if output is None:
                    output = self.open_file(self.path)
                for _, row in sorted(batch, key=lambda item: item[0]):
                    output.write(json.dumps(row, ensure_ascii=False)+'\n')
                output.flush()
        except (OSError, ValueError, TypeError) as exc:
            self.error = str(exc)
        finally:
            if output is not None:
                try:
                    output.close()
                except (OSError, ValueError) as exc:
                    self.error = str(exc)

    def close(self):
        with self.condition:
            self.closing = True
            self.condition.notify()
        self.thread.join(timeout=self.close_timeout)
        return not self.thread.is_alive()


class DesktopBridgeEngine(BridgeEngine):
    """Use SDK framing/session/recovery intact, with asynchronous event logging.

    The SDK's EventLog still creates the path, owns its original clock and closes
    its unused handle. Its __call__ is bypassed, so only the background append
    handle writes records. The wrapper drains after SDK run() closes its handle.
    A blocked disk can lose diagnostic history on process exit, never block video
    or postpone device cleanup indefinitely. State callbacks stay on the caller.
    """
    def __init__(self, *args, log_factory=AsyncSessionLog, **kwargs):
        super().__init__(*args, **kwargs)
        self.log_factory = log_factory
        self.journal = None
        self.log_complete = False

    def emit(self, event, **fields):
        if event in ('control_send', 'control_receive'):
            return
        row = dict(seconds=round(time.perf_counter()-self.log.started, 6),
                   event=event, **fields)
        self.on_event(row)
        self.journal.enqueue(row)

    def run(self):
        self.journal = self.log_factory(self.log_path)
        try:
            return super().run()
        finally:
            self.log_complete = self.journal.close() and self.journal.error is None
