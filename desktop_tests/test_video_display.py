import ctypes
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from goggles_bridge.engine import encoder_command
from desktop_app.settings import Settings
from desktop_app.video import compatible_command
from desktop_app.displays import DEVMODE, DisplayError, select_source, enable_extended, disable_extended
from desktop_app.virtual_driver import verify_package


def screen(device='physical', virtual=False, **fields):
    return dict(device=device, hardware_id='Root\\MttVDD' if virtual else 'PCI\\GPU',
        monitor_id='MONITOR\\TEST', adapter='Virtual Display Driver' if virtual else 'NVIDIA',
        primary=not virtual, active=True, hmonitor=123 if virtual else 456,
        width=1920 if virtual else 3440, height=1080 if virtual else 1440,
        x=3440 if virtual else 0,y=0,hz=60, **fields)


class VideoTests(unittest.TestCase):
    def test_capture_check_and_stream_use_same_conversion(self):
        for capture in ('gfxcapture','ddagrab'):
            settings=Settings(capture=capture).bridge()
            for frames in (0,1):
                command=compatible_command(encoder_command(settings,frames=frames))
                vf=command[command.index('-vf')+1]
                self.assertIn('format=nv12',vf)
                self.assertIn('out_color_matrix=bt709:out_range=tv',vf)
                self.assertIn('setsar=1',vf)
                self.assertIn('color_trc=unknown',vf)
                self.assertEqual(command[command.index('-intra-refresh')+1],'0')
                self.assertEqual(command[command.index('-single-slice-intra-refresh')+1],'0')
                self.assertEqual(command[command.index('-force_key_frames')+1],'expr:gte(t,n_forced)')
                self.assertEqual(command[-3:], ['-f','null' if frames else 'avi','-' if frames else 'pipe:1'])

    def test_monitor_handle_replaces_index_without_mutating_sdk_command(self):
        original=encoder_command(Settings().bridge())
        adapted=compatible_command(original,hmonitor=9876)
        self.assertIn('monitor_idx=0',original[original.index('-i')+1])
        source=adapted[adapted.index('-i')+1]
        self.assertTrue(source.startswith('gfxcapture=hmonitor=9876:'))
        self.assertNotIn('monitor_idx',source)
        with self.assertRaises(ValueError):
            compatible_command(encoder_command(Settings(capture='ddagrab').bridge()),hmonitor=9876)

    def test_old_settings_migrate_without_losing_user_values(self):
        result=Settings.from_dict(dict(schema=1,fps=60,bitrate_mbps=8,capture='gfxcapture'))
        self.assertEqual((result.fps,result.bitrate_mbps,result.source),(60,8,'primary'))
        with self.assertRaises(ValueError):
            Settings(source='extended',capture='ddagrab').validate()


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


if __name__ == '__main__':
    unittest.main()
