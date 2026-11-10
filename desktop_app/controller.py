"""Qt process controller, bounded events and child-process ownership."""
import ctypes
from ctypes import wintypes
import json
import os
import subprocess

from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from .paths import worker_command


class WorkerJob:
    def __init__(self, pid):
        self.handle = None
        if os.name != 'nt':
            return
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        # JOBOBJECT_EXTENDED_LIMIT_INFORMATION layout on Windows x64.
        class BASIC(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', wintypes.DWORD), ('min_ws', ctypes.c_size_t),
                        ('max_ws', ctypes.c_size_t), ('active', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                        ('scheduling', wintypes.DWORD)]
        class EXTENDED(ctypes.Structure):
            _fields_ = [('basic', BASIC), ('io', ctypes.c_uint64*6),
                        ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        job = kernel.CreateJobObjectW(None, None)
        process = kernel.OpenProcess(0x0100 | 0x0001, False, pid)
        limits = EXTENDED()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            if job and process and kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)) and kernel.AssignProcessToJobObject(job, process):
                self.handle = job
            elif job:
                kernel.CloseHandle(job)
        finally:
            if process:
                kernel.CloseHandle(process)

    def close(self):
        if self.handle:
            close = ctypes.WinDLL('kernel32').CloseHandle
            close.argtypes = [wintypes.HANDLE]
            close(self.handle)
            self.handle = None


class Controller(QObject):
    event = Signal(dict)
    ended = Signal(str, int)
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.task = None
        self.buffer = bytearray()
        self.job = None
        self.stopping = False
        self.stop_timer = QTimer(self)
        self.stop_timer.setSingleShot(True)
        self.stop_timer.timeout.connect(self.force_stop)

    @property
    def busy(self):
        return self.process is not None

    def start(self, task, **payload):
        if self.busy:
            return False
        self.task, self.stopping = task, False
        self.buffer.clear()
        process = QProcess(self)
        self.process = process
        program, args = worker_command()
        process.setProgram(program)
        process.setArguments(args)
        process.readyReadStandardOutput.connect(self.read_output)
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())
        process.errorOccurred.connect(self.process_error)
        process.finished.connect(self.finished)

        def started():
            self.job = WorkerJob(int(process.processId()))
            process.write((json.dumps(dict(command=task, **payload))+'\n').encode('utf-8'))
            if self.stopping:
                process.write(b'{"command":"stop"}\n')

        process.started.connect(started)
        self.busy_changed.emit(True)
        process.start()
        return True

    def read_output(self):
        if not self.process:
            return
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        if len(self.buffer) > 1024*1024:
            self.event.emit(dict(event='problem', code='ipc', message='后台事件超过大小限制，已停止。'))
            self.force_stop()
            return
        while b'\n' in self.buffer:
            line, _, rest = self.buffer.partition(b'\n')
            self.buffer[:] = rest
            try:
                row = json.loads(line)
                if isinstance(row, dict) and isinstance(row.get('event'), str):
                    self.event.emit(row)
            except (ValueError, UnicodeError):
                self.event.emit(dict(event='problem', code='ipc', message='无法读取后台状态，请重启客户端。'))

    def stop(self):
        if self.process:
            self.stopping = True
            self.process.write(b'{"command":"stop"}\n')
            self.stop_timer.start(8000)

    def force_stop(self):
        if not self.process:
            return
        if self.job and self.job.handle:
            self.job.close()
        elif self.process.processId():
            try:
                subprocess.run(['taskkill', '/PID', str(int(self.process.processId())), '/T', '/F'],
                               capture_output=True, timeout=5, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except (OSError, subprocess.TimeoutExpired):
                pass
        self.process.kill()

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.event.emit(dict(event='problem', code='launch', message='无法启动后台服务，请重新安装客户端。'))
            self.finished(-1)

    def finished(self, code, *_):
        if not self.process:
            return
        self.read_output()
        process, task = self.process, self.task
        self.process = None
        self.task = None
        self.stop_timer.stop()
        if self.job:
            self.job.close()
            self.job = None
        process.deleteLater()
        self.busy_changed.emit(False)
        self.ended.emit(task, code)
