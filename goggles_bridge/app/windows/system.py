"""Cancellable encoder preflight without device or system configuration changes."""
import subprocess
import time

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class Cancelled(Exception):
    pass


def run_cancellable(command, stop, timeout=30, **kwargs):
    kwargs.pop('capture_output', None)
    kwargs.pop('text', None)
    kwargs.pop('errors', None)
    kwargs.setdefault('creationflags', NO_WINDOW)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    deadline = time.monotonic()+timeout
    try:
        while True:
            if stop.is_set():
                raise Cancelled()
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                out, err = process.communicate(timeout=.1)
                return subprocess.CompletedProcess(command, process.returncode,
                    out.decode('utf-8', errors='replace'), err.decode('utf-8', errors='replace'))
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()
