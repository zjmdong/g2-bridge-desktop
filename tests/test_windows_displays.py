"""Display contracts tested with fake inventories; never change host displays."""
import ctypes
from contextlib import nullcontext
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from goggles_bridge.app.windows import display_config, display_session, displays


def screen(device='physical', virtual=False, **fields):
    row = dict(device=device, id=device, name=device,
               hardware_id='Root\\MttVDD' if virtual else 'PCI\\GPU',
               monitor_id='MONITOR\\TEST', primary=not virtual, active=True,
               hmonitor=123, width=1920 if virtual else 3440, height=1080,
               x=3440 if virtual else 0, y=0, hz=100)
    row.update(fields)
    return row


class DisplayTests(unittest.TestCase):
    def setUp(self):
        ownership = patch.object(displays, '_require_owned_driver')
        ownership.start()
        self.addCleanup(ownership.stop)

    def test_selected_display_disappears_without_falling_back_to_primary(self):
        with patch.object(displays, 'inventory', return_value=[screen()]):
            self.assertEqual(displays.select_source('display')['device'], 'physical')
            with self.assertRaises(displays.DisplayError):
                displays.select_source('display', device='missing')
            with self.assertRaises(displays.DisplayError):
                displays.select_source('virtual')
            with self.assertRaises(displays.DisplayError):
                displays.select_source('unsupported')

    def test_all_eight_modes_preserve_primary_layout(self):
        for width, height in ((1280, 720), (1920, 1080)):
            for fps in (60, 75, 90, 100):
                with self.subTest(width=width, fps=fps):
                    physical = screen()
                    virtual = screen('virtual', True, width=width, height=height, hz=fps)
                    mode = displays.DEVMODE(dmSize=ctypes.sizeof(displays.DEVMODE),
                        dmPelsWidth=width, dmPelsHeight=height, dmDisplayFrequency=fps)
                    api = Mock()
                    api.ChangeDisplaySettingsExW.return_value = 0
                    with patch.object(displays, 'inventory', return_value=[physical, virtual]), \
                         patch.object(displays, 'mode', return_value=mode), \
                         patch.object(displays, 'api', return_value=api):
                        result = displays.enable_extended(width, height, fps)
                    self.assertEqual(result, virtual)
                    self.assertEqual((mode.x, mode.y), (3440, 0))
                    for call in api.ChangeDisplaySettingsExW.call_args_list:
                        self.assertEqual(call.args[0], 'virtual')
                        self.assertFalse(call.args[3] & 0x10)  # Never CDS_SET_PRIMARY.

    def test_primary_or_ambiguous_virtual_display_is_never_detached(self):
        for rows in ([screen('virtual', True, primary=True)],
                     [screen(), screen('v1', True), screen('v2', True)]):
            with patch.object(displays, 'inventory', return_value=rows), \
                 patch.object(displays, 'api') as api:
                with self.assertRaises(displays.DisplayError):
                    displays.disable_extended()
                api.assert_not_called()

    def test_cleanup_does_not_detach_a_replacement_device(self):
        with patch.object(displays, 'inventory', return_value=[screen(), screen('new', True)]), \
             patch.object(displays, 'api') as api:
            with self.assertRaises(displays.DisplayError):
                displays.disable_extended(expected=screen('old', True))
            api.assert_not_called()

    def test_cleanup_handles_already_removed_monitor(self):
        with patch.object(displays, 'inventory', return_value=[screen()]), \
             patch.object(displays, 'api') as api:
            displays.disable_extended(expected=screen('virtual', True))
            api.assert_not_called()

    def test_failed_attach_rolls_back_changed_physical_refresh(self):
        physical = screen()
        virtual = screen('virtual', True, active=False, hmonitor=None)
        changed = dict(physical, hz=60)
        mode = displays.DEVMODE(dmSize=ctypes.sizeof(displays.DEVMODE),
            dmPelsWidth=1920, dmPelsHeight=1080, dmDisplayFrequency=100)
        rollback = Mock()
        with patch.object(displays, 'inventory', side_effect=[[physical, virtual], [changed, virtual]]), \
             patch.object(displays, 'mode', return_value=mode), \
             patch.object(display_config, 'attach', return_value=rollback):
            with self.assertRaises(displays.DisplayError):
                displays.enable_extended(1920, 1080, 100)
        rollback.assert_called_once_with()

    def test_gpu_diagnostics_do_not_claim_game_render_gpu(self):
        direct = displays.capture_diagnostics(screen(), dict(vendor_id=0x10de,
                    gpu_name='NVIDIA', adapter_luid='same-device'))
        self.assertFalse(direct['cross_adapter_transfer'])
        self.assertFalse(direct['render_gpu_verified'])
        foreign = displays.capture_diagnostics(screen(), dict(vendor_id=0x1002))
        self.assertTrue(foreign['cross_adapter_transfer'])
        self.assertTrue(foreign['warning'])
        self.assertIsNone(displays.capture_diagnostics(screen(), {})['cross_adapter_transfer'])


class DisplayLeaseTests(unittest.TestCase):
    def setUp(self):
        self.target = screen('virtual', True)
        for module, name, value in (
            (display_session.virtual_driver, 'status', dict(owned=True, config_current=True)),
            (displays, 'enable_extended', self.target),
            (displays, 'disable_extended', None),
            (displays, 'select_source', self.target),
            (display_session, 'active_refresh', dict(numerator=100, denominator=1, hz=100)),
        ):
            patcher = patch.object(module, name, return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        mutex = patch.object(display_session, '_process_lease', side_effect=nullcontext)
        mutex.start()
        self.addCleanup(mutex.stop)

    def test_normal_and_failed_stream_both_release_the_leased_identity(self):
        for fail in (False, True):
            self.disable_extended.reset_mock()
            try:
                with display_session.lease('virtual', fps=100) as target:
                    self.assertEqual(target['refresh_rate']['hz'], 100)
                    if fail:
                        raise ValueError('stream failed')
            except ValueError:
                self.assertTrue(fail)
            self.disable_extended.assert_called_once_with(expected=self.target)

    def test_callback_failure_after_enable_still_releases(self):
        def emit(event, **_):
            if event in ('display_status', 'releasing_display'):
                raise ValueError('observer failed')
        with self.assertRaisesRegex(ValueError, 'observer failed'):
            with display_session.lease('virtual', emit=emit):
                self.fail('unreachable')
        self.disable_extended.assert_called_once_with(expected=self.target)

    def test_selection_failure_after_enable_still_releases(self):
        self.select_source.side_effect = ValueError('selection failed')
        with self.assertRaisesRegex(ValueError, 'selection failed'):
            with display_session.lease('virtual'):
                self.fail('unreachable')
        self.disable_extended.assert_called_once()

    def test_enable_failure_does_not_detach_an_unleased_display(self):
        self.enable_extended.side_effect = RuntimeError('rolled back inside enable')
        with self.assertRaises(RuntimeError):
            with display_session.lease('virtual'):
                self.fail('unreachable')
        self.disable_extended.assert_not_called()

    def test_cleanup_error_preserves_original_stream_error(self):
        self.disable_extended.side_effect = RuntimeError('display was replaced')
        with self.assertRaisesRegex(ValueError, 'stream failed'):
            with display_session.lease('virtual'):
                raise ValueError('stream failed')
        # Failed teardown must release the guard so a subsequent repair can run.
        self.disable_extended.side_effect = None
        with display_session.lease('virtual'):
            pass

    def test_physical_settings_pass_explicit_device_without_virtual_mutation(self):
        settings = SimpleNamespace(source='display', dimensions=(1920,1080),
                                   fps=100, display_device='chosen')
        with display_session.capture_target(settings):
            pass
        self.enable_extended.assert_not_called()
        self.disable_extended.assert_not_called()
        self.select_source.assert_called_once_with('display',1920,1080,100,device='chosen')

    def test_existing_third_party_driver_is_not_leased(self):
        self.status.return_value = dict(owned=False, config_current=True)
        with self.assertRaises(displays.DisplayError):
            with display_session.lease('virtual'):
                self.fail('unreachable')
        self.enable_extended.assert_not_called()


class DisplayConfigTests(unittest.TestCase):
    def test_exact_paths_and_timings_survive_attach_and_rollback(self):
        primary, virtual, unrelated = display_config.PATH(flags=1), display_config.PATH(), display_config.PATH()
        primary.sourceInfo.id = 2
        primary.sourceInfo.modeInfoIdx = 0
        primary.targetInfo.modeInfoIdx = 1
        virtual.targetInfo.targetAvailable = unrelated.targetInfo.targetAvailable = True
        virtual.sourceInfo.id, unrelated.sourceInfo.id = 7, 9
        modes = [display_config.MODE(infoType=1), display_config.MODE(infoType=2)]
        modes[0].sourceMode.width = 3440
        modes[1].raw[0] = 123456789
        with patch.object(display_config, 'query', return_value=([primary,virtual,unrelated],modes)), \
             patch.object(display_config, 'source_name', side_effect=lambda p: str(p.sourceInfo.id)), \
             patch.object(display_config, 'configure') as configure:
            rollback = display_config.attach('7',1920,1080,100,3440,0)
            proposed, new_modes, flags = configure.call_args.args
            self.assertEqual(len(proposed),2)
            self.assertEqual(bytes(proposed[0]),bytes(primary))
            self.assertEqual([bytes(m) for m in new_modes[:2]],[bytes(m) for m in modes])
            self.assertEqual((proposed[1].targetInfo.refreshRate.Numerator,
                              proposed[1].targetInfo.refreshRate.Denominator),(100,1))
            self.assertFalse(flags & 0x400)
            rollback()
            self.assertEqual(configure.call_args.args[0],[primary])

    def test_active_refresh_retains_fractional_rate(self):
        active = display_config.PATH(flags=1)
        active.targetInfo.refreshRate = display_config.RATIO(99950,1000)
        with patch.object(display_config,'query',return_value=([active],[])), \
             patch.object(display_config,'source_name',return_value='chosen'):
            result=display_config.active_refresh('chosen')
            self.assertEqual(result,dict(numerator=99950,denominator=1000,hz=99.95))

    @unittest.skipUnless(os.name == 'nt', 'Windows ABI')
    def test_windows_structure_sizes(self):
        self.assertEqual(ctypes.sizeof(display_config.PATH),72)
        self.assertEqual(ctypes.sizeof(display_config.MODE),64)


class DisplayMutexTests(unittest.TestCase):
    def test_cross_process_contention_never_releases_other_owners_mutex(self):
        kernel = Mock()
        kernel.CreateMutexW.return_value = 456
        kernel.WaitForSingleObject.return_value = 258
        with patch.object(display_session, '_lease_api', return_value=kernel):
            with self.assertRaises(displays.DisplayError):
                with display_session._process_lease():
                    self.fail('unreachable')
        kernel.WaitForSingleObject.assert_called_once_with(456,0)
        kernel.ReleaseMutex.assert_not_called()
        kernel.CloseHandle.assert_called_once_with(456)

    def test_owned_or_abandoned_mutex_releases_after_stream_error(self):
        for result in (0,0x80):
            with self.subTest(wait_result=result):
                kernel = Mock()
                kernel.CreateMutexW.return_value = 456
                kernel.WaitForSingleObject.return_value = result
                with patch.object(display_session, '_lease_api', return_value=kernel):
                    with self.assertRaisesRegex(ValueError,'stream failure'):
                        with display_session._process_lease():
                            raise ValueError('stream failure')
                kernel.ReleaseMutex.assert_called_once_with(456)
                kernel.CloseHandle.assert_called_once_with(456)


if __name__ == '__main__':
    unittest.main()
