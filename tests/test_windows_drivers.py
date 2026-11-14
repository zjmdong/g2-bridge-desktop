"""No installer, UAC prompt, driver change, network request or GPU is run here."""
import hashlib
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from goggles_bridge.app.windows import drivers, virtual_driver


class DriverTests(unittest.TestCase):
    def test_legacy_ownership_identity_is_retained(self):
        self.assertEqual(virtual_driver.OWNER, r'SOFTWARE\G2Bridge\DJIGogglesStreamerDisplay')
        self.assertEqual(virtual_driver.REGISTRY, r'SOFTWARE\MikeTheTech\VirtualDisplayDriver')
        self.assertEqual(virtual_driver.install_folder().name, 'DJI Goggles Streamer Display')

    def test_config_has_eight_modes_without_replacing_selected_gpu(self):
        root=ET.fromstring(virtual_driver.CONFIG)
        rates={int(node.text) for node in root.findall('global/g_refresh_rate')}
        modes={(int(node.findtext('width')),int(node.findtext('height')),hz)
               for node in root.findall('resolutions/resolution') for hz in rates}
        self.assertEqual(modes,{(w,h,hz) for w,h in ((1280,720),(1920,1080))
                                for hz in (60,75,90,100)})
        configured=virtual_driver.CONFIG.replace('>default<','>NVIDIA Test GPU<')
        self.assertEqual(virtual_driver.configuration_details(configured),(True,'NVIDIA Test GPU'))
        self.assertFalse(virtual_driver.configuration_details(configured.replace('>100<','>120<'))[0])
        self.assertFalse(virtual_driver.configuration_details('<broken')[0])

    def test_virtual_driver_hash_failure_precedes_windows_signature_check(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'mttvdd.cat').write_bytes(b'tampered')
            with patch.object(virtual_driver,'powershell_json') as signature:
                with self.assertRaises(ValueError):
                    virtual_driver.verify_package(folder)
                signature.assert_not_called()

    def test_dji_driver_hash_failure_precedes_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder,'DEVICE_BULK.inf')
            path.write_bytes(b'tampered')
            with patch.object(drivers.InstallerProcess,'_launch') as launch:
                with self.assertRaises(ValueError):
                    drivers.InstallerProcess(path)
                launch.assert_not_called()

    def test_dji_installer_requires_both_hash_and_trusted_signature(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder,'assistant.exe')
            path.write_bytes(b'fixture')
            digest=hashlib.sha256(b'fixture').hexdigest()
            with patch.object(drivers,'ASSISTANT_SHA256',digest), \
                 patch.object(drivers,'powershell_json',return_value={'Status':'NotTrusted'}):
                with self.assertRaises(ValueError):
                    drivers.verify_installer(path)
            with patch.object(drivers,'powershell_json') as signature:
                with self.assertRaises(ValueError):
                    drivers.verify_installer(path)
                signature.assert_not_called()

    def test_maintenance_rejects_arbitrary_or_extra_arguments(self):
        with patch.object(virtual_driver,'elevated_main',return_value=3010) as elevated:
            for args in ([],['anything'],['install-display-driver','arbitrary-path'],['--remove-display-driver']):
                self.assertEqual(virtual_driver.maintenance_main(args),64)
            elevated.assert_not_called()
            self.assertEqual(virtual_driver.maintenance_main(['install-display-driver']),3010)
            elevated.assert_called_once_with(remove_driver=False)

    def test_virtual_installer_uses_fixed_worker_operation(self):
        with patch.object(virtual_driver,'verify_package'), \
             patch.object(virtual_driver,'worker_command',return_value=('worker.exe',['--windows-maintenance'])), \
             patch.object(drivers.InstallerProcess,'_launch') as launch:
            virtual_driver.VirtualInstaller()
            launch.assert_called_once_with('worker.exe','--windows-maintenance install-display-driver')

    def test_foreign_configuration_blocks_update_before_writing(self):
        with patch.object(virtual_driver,'owned_instance',return_value=r'ROOT\DISPLAY\0001'), \
             patch.object(virtual_driver,'_owns_configuration',return_value=False), \
             patch.object(virtual_driver,'verify_package') as verify, \
             patch.object(virtual_driver.subprocess,'run') as run, \
             patch.object(virtual_driver,'os',SimpleNamespace(name='nt',environ={})):
            with self.assertRaises(RuntimeError):
                virtual_driver.install()
            verify.assert_not_called()
            run.assert_not_called()

    def test_second_driver_consumer_blocks_shared_configuration_update(self):
        instance=r'ROOT\DISPLAY\0001'
        with patch.object(virtual_driver,'owned_instance',return_value=instance), \
             patch.object(virtual_driver,'_owns_configuration',return_value=True), \
             patch.object(virtual_driver,'_instance_registered',return_value=True), \
             patch.object(virtual_driver,'vdd_devices',return_value=[{'PNPDeviceID':instance},
                                                                    {'PNPDeviceID':r'ROOT\DISPLAY\0002'}]), \
             patch.object(virtual_driver,'verify_package') as verify, \
             patch.object(virtual_driver,'os',SimpleNamespace(name='nt',environ={})):
            with self.assertRaises(RuntimeError):
                virtual_driver.install()
            verify.assert_not_called()

    def test_download_redirect_must_remain_on_the_official_host(self):
        with tempfile.TemporaryDirectory() as folder:
            response=Mock(url='https://example.org/driver.exe')
            response.__enter__=Mock(return_value=response)
            response.__exit__=Mock(return_value=False)
            with patch.object(drivers,'data_dir',return_value=Path(folder)), \
                 patch.object(drivers.urllib.request,'urlopen',return_value=response):
                with self.assertRaisesRegex(ValueError,'重定向'):
                    drivers.download_assistant(threading.Event(),Mock())
            self.assertEqual(list(Path(folder).rglob('*.partial')),[])


if __name__ == '__main__':
    unittest.main()
