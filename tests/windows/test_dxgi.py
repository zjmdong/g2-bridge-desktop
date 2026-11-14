"""Offline COM fixtures for capture identity and read-only GPU diagnostics."""
import ctypes as C
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from goggles_bridge.app.windows import dxgi


class FakeDxgi:
    def __init__(self, fail=None):
        self.fail = fail
        self.released = []
        self.create = Mock(side_effect=self.create_factory)

    def create_factory(self, _iid, target):
        C.cast(target, C.POINTER(C.c_void_p))[0] = C.c_void_p(1)
        return 0

    def method(self, pointer, index, _result, *_arguments):
        identity = pointer.value
        if index == 2:
            return lambda _this: self.released.append(identity)
        if identity == 1 and index == 12:
            def enum_adapter(_this, number, target):
                if number:
                    return -2005270526  # DXGI_ERROR_NOT_FOUND
                C.cast(target, C.POINTER(C.c_void_p))[0] = C.c_void_p(10)
                return 0
            return enum_adapter
        if identity == 10 and index == 10:
            def get_adapter_desc(_this, target):
                if self.fail == 'adapter_desc':
                    return -1
                value = C.cast(target, C.POINTER(dxgi.ADAPTER_DESC1)).contents
                value.name = 'NVIDIA fixture'
                value.vendor = 0x10de
                value.dedicated_video = 8 * 1024**3
                value.luid.low, value.luid.high = 0xabcdef12, -1
                return 0
            return get_adapter_desc
        if identity == 10 and index == 7:
            def enum_output(_this, number, target):
                if number >= 3:
                    return -2005270526
                C.cast(target, C.POINTER(C.c_void_p))[0] = C.c_void_p(20 + number)
                return 0
            return enum_output
        if identity in (20, 21, 22) and index == 7:
            def get_output_desc(_this, target):
                if self.fail == 'output_desc':
                    return -1
                value = C.cast(target, C.POINTER(dxgi.OUTPUT_DESC)).contents
                value.name = rf'\\.\DISPLAY{identity - 19}'
                value.attached = identity != 22
                value.monitor = 100 + identity
                return 0
            return get_output_desc
        raise AssertionError(f'Unexpected COM method {identity}:{index}')

    def outputs(self):
        with patch.object(dxgi.C, 'WinDLL', return_value=SimpleNamespace(CreateDXGIFactory1=self.create), create=True), \
             patch.object(dxgi, 'method', side_effect=self.method):
            return dxgi.outputs()


class DxgiTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32' and C.sizeof(C.c_void_p) == 8, 'Windows x64 ABI')
    def test_adapter_descriptor_uses_windows_x64_layout(self):
        self.assertEqual(C.sizeof(C.c_void_p), 8)
        self.assertEqual(C.sizeof(dxgi.LUID), 8)
        self.assertEqual(dxgi.ADAPTER_DESC1.dedicated_video.offset, 272)
        self.assertEqual(dxgi.ADAPTER_DESC1.luid.offset, 296)
        self.assertEqual(dxgi.ADAPTER_DESC1.flags.offset, 304)
        self.assertEqual(C.sizeof(dxgi.ADAPTER_DESC1), 312)

    def test_attached_sources_keep_capture_indices_and_gpu_identity(self):
        fake = FakeDxgi()
        rows = fake.outputs()
        self.assertEqual(len(rows), 2)
        self.assertEqual([(r['device'], r['adapter'], r['output'], r['hmonitor']) for r in rows],
            [(r'\\.\DISPLAY1', 0, 0, 120), (r'\\.\DISPLAY2', 0, 1, 121)])
        for row in rows:
            self.assertEqual(row['gpu_name'], 'NVIDIA fixture')
            self.assertEqual(row['vendor_id'], 0x10de)
            self.assertEqual(row['adapter_luid'], 'ffffffff:abcdef12')
        self.assertEqual(fake.released, [20, 21, 22, 10, 1])

    def test_com_objects_are_released_when_metadata_read_fails(self):
        for failure, releases in [('adapter_desc', [10, 1]), ('output_desc', [20, 10, 1])]:
            with self.subTest(failure=failure):
                fake = FakeDxgi(failure)
                with self.assertRaises(RuntimeError):
                    fake.outputs()
                self.assertEqual(fake.released, releases)

    def test_gdi_identity_survives_output_and_adapter_reordering(self):
        primary = dict(device=r'\\.\DISPLAY1', adapter=0, output=0, hmonitor=1)
        virtual = dict(device=r'\\.\DISPLAY51', adapter=0, output=1, hmonitor=2)
        reordered = dict(virtual, adapter=2, output=0, hmonitor=3)
        with patch.object(dxgi, 'outputs', side_effect=[[primary, virtual], [reordered, primary]]):
            self.assertEqual(dxgi.select_output(virtual['device']), virtual)
            self.assertEqual(dxgi.select_output(virtual['device']), reordered)

    def test_missing_or_duplicate_gdi_identity_never_falls_back(self):
        virtual = dict(device=r'\\.\DISPLAY51', adapter=0, output=1, hmonitor=2)
        for rows in ([], [virtual, dict(virtual, adapter=1)]):
            with self.subTest(rows=rows), patch.object(dxgi, 'outputs', return_value=rows):
                with self.assertRaises(RuntimeError):
                    dxgi.select_output(virtual['device'])


if __name__ == '__main__':
    unittest.main()
