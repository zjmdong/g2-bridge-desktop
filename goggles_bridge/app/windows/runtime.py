"""Keep Python USB sending independent of WebView/GIL activity in the window."""
from dataclasses import asdict
import json
import subprocess
import threading

from .paths import worker_command


class WindowsRuntime:
    def __init__(self):
        self._process = None

    def busy(self):
        return self._process is not None and self._process.poll() is None

    def run(self, settings, options, log, stop, on_event):
        if self.busy():
            raise RuntimeError('The previous worker is still releasing the device')
        program, arguments = worker_command()
        arguments = [a for a in arguments if a != '--windows-maintenance']
        request = dict(settings={k: str(v) if k in ('dll', 'ffmpeg') and v is not None else v
                                 for k, v in asdict(settings).items()}, options=options, log=str(log))
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.with_suffix('.worker.log').open('w', encoding='utf-8') as errors:
            process = subprocess.Popen([program, *arguments], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=errors, text=True, encoding='utf-8', bufsize=1,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self._process = process
            ended = threading.Event()

            def cancellation():
                while not ended.wait(.1):
                    if stop.is_set():
                        try:
                            process.stdin.write('{"command":"stop"}\n')
                            process.stdin.flush()
                        except (OSError, ValueError):
                            pass
                        return

            monitor = threading.Thread(target=cancellation, daemon=True)
            failure = None
            last_error = None
            try:
                process.stdin.write(json.dumps(request)+'\n')
                process.stdin.flush()
                monitor.start()
                for line in process.stdout:
                    row = json.loads(line)
                    if row.get('event') == 'error':
                        last_error = row.get('message')
                    on_event(row)
                code = process.wait(timeout=10)
                if code and not stop.is_set():
                    raise RuntimeError(last_error or f'The stream worker stopped ({code}). See {log.with_suffix(".worker.log")}')
            except BaseException as exc:
                failure = exc
                raise
            finally:
                ended.set()
                if monitor.ident is not None:
                    monitor.join(timeout=1)
                # EOF asks the worker to release its virtual screen even after malformed IPC.
                for pipe in (process.stdin, process.stdout):
                    try:
                        pipe.close()
                    except (OSError, ValueError):
                        pass
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    if failure is None:
                        raise RuntimeError('The worker is still releasing the device; do not start another stream')
