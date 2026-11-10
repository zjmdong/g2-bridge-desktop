"""Exercise the frozen worker, using its real JSON pipe without any USB writes."""
import argparse
import json
from pathlib import Path
import queue
import subprocess
import threading


def run_worker(executable, request, timeout=45, stop_on=None):
    process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
    output = queue.Queue()
    def read():
        for line in process.stdout:
            output.put(line)
        output.put(None)
    threading.Thread(target=read, daemon=True).start()
    rows = []
    try:
        process.stdin.write(json.dumps(request)+'\n')
        process.stdin.flush()
        while True:
            line = output.get(timeout=timeout)
            if line is None:
                break
            row = json.loads(line)
            rows.append(row)
            if row['event'] == stop_on:
                process.stdin.write('{"command":"stop"}\n')
                process.stdin.flush()
        process.wait(timeout=5)
        errors = process.stderr.read()
        if process.returncode:
            raise RuntimeError(f'Worker failed: {rows!r}; {errors}')
        if not rows or rows[-1]['event'] != 'finished':
            raise RuntimeError('Worker did not finish cleanly')
        return rows
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    parser.add_argument('--assistant', type=Path)
    args = parser.parse_args()
    worker = args.folder/'GogglesWorker.exe'
    rows = run_worker(worker, dict(command='environment'))
    env = next(row for row in rows if row['event'] == 'environment')
    assert env['ffmpeg'], 'Bundled encoder not found'
    assert env['supported_os'], 'Windows x64 not recognized'
    print(json.dumps(dict(packaged_worker='passed', ffmpeg=env['ffmpeg'],
        encoder_ok=env['encoder_ok'], driver=env['driver']['status'])))
    assert env['encoder_ok'], 'Bundled H.264 encoder did not pass its probe'
    presence = run_worker(worker, dict(command='watch_usb'), stop_on='usb_presence')
    assert any(row['event'] == 'usb_presence' for row in presence), 'USB presence watcher failed'
    print('Packaged USB presence watcher emitted status and stopped cleanly.')
    if args.assistant:
        rows = run_worker(worker, dict(command='import_driver', path=str(args.assistant.resolve())), timeout=300)
        prepared = next(row for row in rows if row['event'] == 'driver_prepared')
        assert Path(prepared['path']).is_file()
        print('Pinned driver extracted and verified; no driver installation performed.')
