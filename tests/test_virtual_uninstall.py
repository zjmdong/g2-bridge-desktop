"""GUI lifetime/uninstall handshake, including real non-elevated Windows processes."""
import ctypes as C
from pathlib import Path
import queue
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch
import uuid

from goggles_bridge.app import backend


class UninstallTests(unittest.TestCase):
    def setUp(self):
        self.kernel = Mock()
        self.kernel.CreateMutexW.side_effect = [10, 11]
        self.kernel.WaitForSingleObject.return_value = 0
        self.enterContext(patch.object(backend, 'app_mutex_name', return_value='Global\\GogglesBridge.Test'))
        self.enterContext(patch.object(backend.C, 'WinDLL', return_value=self.kernel, create=True))
        self.register = self.enterContext(patch.object(backend.atexit, 'register'))

    def test_marker_is_held_until_process_exit_and_startup_gate_is_released(self):
        backend.hold_app_lifetime()
        self.assertEqual([call.args[2] for call in self.kernel.CreateMutexW.call_args_list],
                         ['Global\\GogglesBridge.Test.Uninstall', 'Global\\GogglesBridge.Test.Running'])
        self.kernel.ReleaseMutex.assert_called_once_with(10)
        self.kernel.CloseHandle.assert_called_once_with(10)
        self.register.assert_called_once_with(self.kernel.CloseHandle, 11)

    def test_busy_uninstaller_rejects_startup_without_waiting_or_creating_marker(self):
        self.kernel.WaitForSingleObject.return_value = 258
        with self.assertRaisesRegex(SystemExit, 'being uninstalled'):
            backend.hold_app_lifetime()
        self.kernel.WaitForSingleObject.assert_called_once_with(10, 0)
        self.assertEqual(self.kernel.CreateMutexW.call_count, 1)
        self.register.assert_not_called()
        self.kernel.ReleaseMutex.assert_not_called()
        self.kernel.CloseHandle.assert_called_once_with(10)

    def test_abandoned_gate_can_be_recovered(self):
        self.kernel.WaitForSingleObject.return_value = 0x80
        backend.hold_app_lifetime()
        self.register.assert_called_once_with(self.kernel.CloseHandle, 11)

    def test_main_registers_lifetime_before_creating_backend(self):
        with patch.object(backend, 'WINDOWS', True), \
             patch.object(backend, 'hold_app_lifetime', side_effect=SystemExit('uninstalling')), \
             patch.object(backend, 'Desktop') as desktop:
            with self.assertRaises(SystemExit):
                backend.main()
        desktop.assert_not_called()

    def test_native_uninstaller_uses_the_same_identity_and_releases_gate_on_exit(self):
        script = (Path(__file__).resolve().parents[1]/'packaging/installer.iss').read_text(encoding='utf-8')
        self.assertIn("'Global\\GogglesBridge.' + Result", script)
        self.assertIn("Name + '.Uninstall'", script)
        self.assertIn("CheckForMutexes(Name + '.Running')", script)
        self.assertIn('procedure DeinitializeUninstall;', script)
        self.assertNotIn('AppMutex=', script)  # Silent updates start before the old GUI exits.


@unittest.skipUnless(sys.platform == 'win32', 'Windows named objects')
class WindowsLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.name = backend.app_mutex_name() + '.Test.' + uuid.uuid4().hex
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [C.c_void_p, C.c_int, C.c_wchar_p]
        self.kernel.CreateMutexW.restype = C.c_void_p
        self.kernel.OpenMutexW.argtypes = [C.c_ulong, C.c_int, C.c_wchar_p]
        self.kernel.OpenMutexW.restype = C.c_void_p
        self.kernel.WaitForSingleObject.argtypes = [C.c_void_p, C.c_ulong]
        self.kernel.ReleaseMutex.argtypes = [C.c_void_p]
        self.kernel.CloseHandle.argtypes = [C.c_void_p]

    def launch(self):
        code = ('import sys\nfrom goggles_bridge.app import backend\n'
                'backend.app_mutex_name = lambda: sys.argv[1]\n'
                'backend.hold_app_lifetime()\nprint("ready", flush=True)\nsys.stdin.readline()\n')
        process = subprocess.Popen([sys.executable, '-c', code, self.name],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.addCleanup(self.stop, process)
        return process

    def stop(self, process):
        if process.poll() is None:
            try:
                process.communicate('\n', timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()

    def ready(self, process):
        output = queue.Queue()
        threading.Thread(target=lambda: output.put(process.stdout.readline()), daemon=True).start()
        self.assertEqual(output.get(timeout=10), 'ready\n')

    def marker_exists(self):
        handle = self.kernel.OpenMutexW(0x100000, False, self.name + '.Running')
        if handle:
            self.kernel.CloseHandle(handle)
        return bool(handle)

    def test_multiple_guis_share_marker_until_last_process_exits(self):
        self.assertRegex(self.name, r'^Global\\GogglesBridge\.S-1-')
        # Startup takes the same short-lived gate as uninstall. Complete each
        # launch before starting another; this test checks the shared lifetime
        # marker, not which simultaneous launch wins that gate.
        first = self.launch()
        self.ready(first)
        second = self.launch()
        self.ready(second)
        self.assertTrue(self.marker_exists())
        self.stop(first)
        self.assertTrue(self.marker_exists())
        self.stop(second)
        self.assertFalse(self.marker_exists())

    def test_held_uninstall_gate_rejects_new_gui_immediately(self):
        gate = self.kernel.CreateMutexW(None, False, self.name + '.Uninstall')
        self.assertTrue(gate)
        try:
            self.assertEqual(self.kernel.WaitForSingleObject(gate, 0), 0)
            process = self.launch()
            out, err = process.communicate(timeout=5)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(out, '')
            self.assertIn('being uninstalled', err)
            self.assertFalse(self.marker_exists())
        finally:
            self.kernel.ReleaseMutex(gate)
            self.kernel.CloseHandle(gate)


if __name__ == '__main__':
    unittest.main()
