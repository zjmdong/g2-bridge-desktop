"""Packaging must verify both sources of the native fresh-image regression."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location('desktop_ffmpeg_inputs',
    Path(__file__).resolve().parents[1] / 'packaging/windows/ffmpeg_inputs.py')
INPUTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INPUTS)


class FfmpegSourceInputTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.entries = {}
        for name in ('source_archive', 'patch', 'build_script', 'clock_test',
                     'fresh_wait_test', 'fresh_wait_runner'):
            data = (name + '\n').encode()
            path = self.root / name
            path.write_bytes(data)
            self.entries[name] = dict(path=name, bytes=len(data),
                                     sha256=hashlib.sha256(data).hexdigest())
        recipe = {}
        for name in ('build_script', 'clock_test', 'fresh_wait_test', 'fresh_wait_runner'):
            recipe[name] = self.entries[name]['path']
            recipe[name + '_sha256'] = self.entries[name]['sha256']
        self.manifest = dict(upstream={'source_archive': self.entries['source_archive']},
                             patch=self.entries['patch'], recipe=recipe)

    def test_all_source_and_test_inputs_are_accepted_when_pinned(self):
        INPUTS.verify_ffmpeg_sources(self.root, self.manifest)

    def test_missing_fresh_wait_source_or_extractor_blocks_packaging(self):
        for name in ('fresh_wait_test', 'fresh_wait_runner'):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.unlink()
                try:
                    with self.assertRaisesRegex(RuntimeError, 'Missing FFmpeg source input: ' + name):
                        INPUTS.verify_ffmpeg_sources(self.root, self.manifest)
                finally:
                    path.write_bytes(original)

    def test_same_length_fresh_wait_changes_require_new_hashes(self):
        for name in ('fresh_wait_test', 'fresh_wait_runner'):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(b'!' + original[1:])
                try:
                    with self.assertRaisesRegex(RuntimeError, 'FFmpeg source hash mismatch: ' + name):
                        INPUTS.verify_ffmpeg_sources(self.root, self.manifest)
                finally:
                    path.write_bytes(original)


if __name__ == '__main__':
    unittest.main()
