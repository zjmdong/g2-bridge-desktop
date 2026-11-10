import ctypes
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from goggles_bridge.engine import encoder_command
from desktop_app.settings import Settings
from desktop_app.video import compatible_command, frame_selection
from desktop_app.displays import DEVMODE, DisplayError, select_source, enable_extended, disable_extended
from desktop_app.virtual_driver import verify_package


def screen(device='physical', virtual=False, **fields):
    return dict(device=device, hardware_id='Root\\MttVDD' if virtual else 'PCI\\GPU',
        monitor_id='MONITOR\\TEST', adapter='Virtual Display Driver' if virtual else 'NVIDIA',
        primary=not virtual, active=True, hmonitor=123 if virtual else 456,
        width=1920 if virtual else 3440, height=1080 if virtual else 1440,
        x=3440 if virtual else 0,y=0,hz=60, **fields)


class VideoTests(unittest.TestCase):
    def test_hardware_presets_are_retained_and_software_input_is_rejected(self):
        for preset in ('p1', 'p4'):
            command = encoder_command(Settings(preset=preset).bridge())
            adapted = compatible_command(command)
            self.assertEqual(adapted[adapted.index('-preset')+1], preset)
            command[command.index('-c:v')+1] = 'libx264'
            with self.assertRaises(ValueError):
                compatible_command(command)

    def test_capture_check_and_stream_use_same_conversion(self):
        for capture in ('gfxcapture','ddagrab'):
            settings=Settings(capture=capture).bridge()
            for frames in (0,1):
                command=compatible_command(encoder_command(settings,frames=frames))
                vf=command[command.index('-filter_complex')+1]
                self.assertIn('format=nv12',vf)
                self.assertIn('out_color_matrix=bt709:out_range=tv',vf)
                self.assertIn('setsar=1',vf)
                self.assertIn('color_trc=unknown',vf)
                self.assertEqual(command[command.index('-intra-refresh')+1], '0')
                self.assertEqual(command[command.index('-c:v')+1], 'h264_nvenc')
                self.assertEqual(command[command.index('-tune')+1], 'ull')
                self.assertEqual(command[command.index('-rc-lookahead')+1], '0')
                self.assertEqual(command[command.index('-multipass')+1], 'qres')
                self.assertNotIn('-x264-params', command)
                self.assertNotIn('-i', command)  # No lavfi demux/decoder queues.
                self.assertEqual(command[command.index('-map')+1], '[desktop]')
                self.assertEqual(command[command.index('-force_key_frames')+1], '0,1,2')
                self.assertEqual(command[command.index('-g')+1], '1000000')
                self.assertEqual(command[-3:], ['-f','null' if frames else 'avi','-' if frames else 'pipe:1'])

    def test_monitor_handle_replaces_index_without_mutating_sdk_command(self):
        original=encoder_command(Settings(capture='gfxcapture').bridge())
        adapted=compatible_command(original,hmonitor=9876)
        self.assertIn('monitor_idx=0',original[original.index('-i')+1])
        source=adapted[adapted.index('-filter_complex')+1]
        self.assertTrue(source.startswith('gfxcapture=hmonitor=9876:'))
        self.assertNotIn('monitor_idx',source)
        with self.assertRaises(ValueError):
            compatible_command(encoder_command(Settings(capture='ddagrab').bridge()),hmonitor=9876)

    def test_old_settings_migrate_without_losing_user_values(self):
        result=Settings.from_dict(dict(schema=1,fps=60,bitrate_mbps=8,capture='gfxcapture'))
        self.assertEqual((result.fps,result.bitrate_mbps,result.source),(60,8,'primary'))
        self.assertEqual(result.capture, 'ddagrab')
        Settings(source='extended',capture='ddagrab').validate()

    def test_dxgi_identity_and_720p_without_mutating_sdk(self):
        original = encoder_command(Settings(capture='ddagrab').bridge())
        adapted = compatible_command(original, output=dict(adapter=1, output=2), dimensions=(1280,720))
        self.assertIn('d3d11va=cap:1', adapted)
        self.assertIn('output_idx=2', adapted[adapted.index('-filter_complex')+1])
        self.assertIn('pad=1280:720', adapted[adapted.index('-filter_complex')+1])
        self.assertIn('pad=1920:1080', original[original.index('-vf')+1])
        self.assertNotIn('gfxcapture', ' '.join(adapted))

    def test_both_sources_use_identical_immediate_selection_and_no_catchup_filter(self):
        for fps in (60, 75, 90, 100):
            settings = Settings(fps=fps).bridge()
            graphs = []
            for output in (0, 1):
                command = compatible_command(encoder_command(settings),
                                             output=dict(adapter=0, output=output))
                graph = command[command.index('-filter_complex')+1]
                self.assertNotIn(',fps=', graph)
                self.assertIn(','+frame_selection(fps)+',hwdownload', graph)
                graphs.append(graph.replace(f'output_idx={output}', 'output_idx=TARGET'))
            self.assertEqual(graphs[0], graphs[1])

    def test_selection_matches_the_sdk_no_wait_rule(self):
        for fps in (60, 75, 90, 100):
            original = encoder_command(Settings(fps=fps, capture='gfxcapture').bridge())
            self.assertEqual(frame_selection(fps), original[original.index('-vf')+1])


class DisplayTests(unittest.TestCase):
    def test_no_silent_primary_fallback_when_virtual_screen_disappears(self):
        with patch('desktop_app.displays.inventory',return_value=[screen()]):
            self.assertEqual(select_source('primary')['width'],3440)
            with self.assertRaises(DisplayError):
                select_source('extended')

    def test_rejects_virtual_primary_and_duplicate_targets(self):
        virtual=screen('virtual',True);virtual['primary']=True
        with patch('desktop_app.displays.inventory',return_value=[screen(),virtual]):
            with self.assertRaises(DisplayError): select_source('extended')
            with self.assertRaises(DisplayError): disable_extended()
        virtual['primary']=False
        with patch('desktop_app.displays.inventory',return_value=[screen(),virtual,virtual]):
            with self.assertRaises(DisplayError): select_source('extended')

    def test_enable_changes_only_virtual_screen_to_right_of_ultrawide(self):
        from unittest.mock import Mock
        physical=screen();virtual=screen('virtual',True)
        desired=DEVMODE(dmSize=ctypes.sizeof(DEVMODE),dmPelsWidth=1920,dmPelsHeight=1080,dmDisplayFrequency=60)
        api=Mock();api.ChangeDisplaySettingsExW.return_value=0
        with patch('desktop_app.displays.inventory',return_value=[physical,virtual]), \
             patch('desktop_app.displays.mode',return_value=desired),patch('desktop_app.displays.api',return_value=api):
            result=enable_extended()
        self.assertEqual(result['device'],'virtual')
        self.assertEqual((desired.x,desired.y),(3440,0))
        for call in api.ChangeDisplaySettingsExW.call_args_list:
            self.assertEqual(call.args[0],'virtual')
            self.assertFalse(call.args[3] & 0x10)  # Never CDS_SET_PRIMARY.

    def test_driver_hash_failure_precedes_any_windows_signature_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'mttvdd.cat').write_bytes(b'modified')
            with patch('desktop_app.virtual_driver.powershell_json') as query:
                with self.assertRaises(ValueError): verify_package(directory)
                query.assert_not_called()

    def test_detached_monitor_uses_ccd_and_verifies_new_handle(self):
        from unittest.mock import Mock
        physical = screen()
        virtual = screen('virtual', True)
        virtual.update(active=False, hmonitor=None, width=0, height=0, hz=0)
        desired = DEVMODE(dmSize=ctypes.sizeof(DEVMODE), dmPelsWidth=1920,
                          dmPelsHeight=1080, dmDisplayFrequency=60)

        def attach(device, width, height, hz, x, y):
            self.assertEqual(device, 'virtual')
            self.assertEqual((width, height, hz, x, y), (1920, 1080, 60, 3440, 0))
            virtual.update(active=True, hmonitor=789, width=width, height=height, hz=hz)
            return Mock()

        api = Mock()
        api.ChangeDisplaySettingsExW.return_value = -1  # Real host rejects legacy reattachment.
        with patch('desktop_app.displays.inventory', return_value=[physical, virtual]), \
             patch('desktop_app.displays.mode', return_value=desired), \
             patch('desktop_app.displays.api', return_value=api), \
             patch('desktop_app.display_config.attach', side_effect=attach):
            self.assertEqual(enable_extended()['hmonitor'], 789)
            self.assertEqual(select_source('primary'), screen())
        api.ChangeDisplaySettingsExW.assert_not_called()

    def test_reattach_rolls_back_if_primary_refresh_changes(self):
        from unittest.mock import Mock
        physical = screen()
        virtual = screen('virtual', True)
        virtual.update(active=False, hmonitor=None)
        changed = dict(physical, hz=120)
        desired = DEVMODE(dmSize=ctypes.sizeof(DEVMODE), dmPelsWidth=1920,
                          dmPelsHeight=1080, dmDisplayFrequency=60)
        rollback = Mock()
        with patch('desktop_app.displays.inventory', side_effect=[[physical, virtual], [changed, virtual]]), \
             patch('desktop_app.displays.mode', return_value=desired), \
             patch('desktop_app.display_config.attach', return_value=rollback):
            with self.assertRaises(DisplayError):
                enable_extended()
        rollback.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
