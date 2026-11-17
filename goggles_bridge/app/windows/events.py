"""Bounded background journal and IPC; storage or UI stalls cannot stop video."""
import json
import queue
import threading


class EventWriter:
    def __init__(self, output, log):
        self.output, self.log = output, log
        self.events = queue.Queue(maxsize=128)
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def emit(self, event, **fields):
        row = dict(event=event, **fields)
        try:
            self.events.put_nowait(row)
        except queue.Full:
            # Keep the newest events, including shutdown, without blocking USB.
            try:
                self.events.get_nowait()
            except queue.Empty:
                pass
            self.events.put_nowait(row)

    def run(self):
        journal = None
        log_failed = False
        try:
            while not self.done.is_set() or not self.events.empty():
                try:
                    row = self.events.get(timeout=.05)
                except queue.Empty:
                    continue
                line = json.dumps(row, ensure_ascii=False)+'\n'
                if not log_failed:
                    try:
                        # BridgeEngine creates the journal before its first event.
                        if journal is None:
                            journal = self.log.open('a', encoding='utf-8')
                        journal.write(line)
                        journal.flush()
                    except OSError:
                        log_failed = True
                self.output.write(line)
                self.output.flush()
        except (OSError, ValueError):
            pass  # Parent stdin EOF independently cancels the stream.
        finally:
            if journal is not None:
                try:
                    journal.close()
                except OSError:
                    pass

    def close(self):
        self.done.set()
        self.thread.join(timeout=2)
