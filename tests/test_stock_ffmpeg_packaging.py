"""Verify the separate upstream WGC build without downloading or executing it."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('windows_build', Path(__file__).resolve().parents[1]/'packaging/build_windows.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class StockBuildTests(unittest.TestCase):
    def archive(self, root):
        path = root/'packaging/cache'/f'{build.STOCK_FFMPEG}.zip'
        path.parent.mkdir(parents=True)
        with zipfile.ZipFile(path, 'w') as bundle:
            bundle.writestr(f'{build.STOCK_FFMPEG}/bin/ffmpeg.exe', b'upstream WGC fixture')
            bundle.writestr(f'{build.STOCK_FFMPEG}/LICENSE', b'upstream license')
        return path

    def test_hash_checked_upstream_build_stays_separate_from_native(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = self.archive(root)
            native = root/'vendor/ffmpeg/ffmpeg.exe'
            native.parent.mkdir(parents=True)
            native.write_bytes(b'native DDA fixture')
            with patch.object(build, 'ROOT', root), patch.object(build, 'STOCK_FFMPEG_SHA256', hashlib.sha256(archive.read_bytes()).hexdigest()), \
                    patch.object(build.urllib.request, 'urlretrieve', side_effect=AssertionError('unexpected network')):
                target = build.prepare_stock()
            self.assertEqual((target/'ffmpeg.exe').read_bytes(), b'upstream WGC fixture')
            self.assertEqual((target/'LICENSE.txt').read_bytes(), b'upstream license')
            self.assertIn('0893feba65', (target/'SOURCE.txt').read_text())
            self.assertEqual(native.read_bytes(), b'native DDA fixture')

    def test_wrong_hash_is_rejected_before_replacing_existing_binary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.archive(root)
            target = root/'vendor/ffmpeg-stock/ffmpeg.exe'
            target.parent.mkdir(parents=True)
            target.write_bytes(b'previous verified build')
            with patch.object(build, 'ROOT', root), patch.object(build, 'STOCK_FFMPEG_SHA256', '0'*64):
                with self.assertRaisesRegex(ValueError, 'pinned checksum'):
                    build.prepare_stock()
            self.assertEqual(target.read_bytes(), b'previous verified build')


if __name__ == '__main__':
    unittest.main()
