"""Bounded IPC writer; a slow GUI cannot back-pressure video transmission."""
import json
import queue
import threading


class EventWriter:
    def __init__(self, output):
        self.output = output
        self.events = queue.Queue(maxsize=128)
        self.latest_stats = None
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name='event-writer')
        self.thread.start()

    def emit(self, event, **fields):
        row = dict(event=event, **fields)
        if event == 'live_stats':
            self.latest_stats = row  # A newer sample replaces one the UI hasn't consumed.
        else:
            try:
                self.events.put_nowait(row)
            except queue.Full:
                # Backlog cannot stop a real-time stream. Retain the newest state.
                try:
                    self.events.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self.events.put_nowait(row)
                except queue.Full:
                    pass

    def run(self):
        try:
            while not self.done.is_set() or not self.events.empty():
                try:
                    row = self.events.get(timeout=.05)
                except queue.Empty:
                    row = self.latest_stats
                    self.latest_stats = None
                if row is not None:
                    self.output.write(json.dumps(row, ensure_ascii=False)+'\n')
                    self.output.flush()
        except (OSError, ValueError):
            pass  # Parent's stdin EOF independently stops and cleans up the session.

    def close(self):
        self.latest_stats = None
        self.done.set()
        self.thread.join(timeout=2)
