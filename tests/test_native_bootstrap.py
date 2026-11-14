"""Native release inputs are validated without executing downloaded binaries."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile


SPEC = importlib.util.spec_from_file_location('native_bootstrap',
    Path(__file__).resolve().parents[1] / 'packaging/bootstrap_native.py')
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)


def record(data):
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


class NativeBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        inputs = {
            'vendor/ffmpeg/ffmpeg.exe': b'MZ-native-fixture',
            'vendor/ffmpeg/ffprobe.exe': b'MZ-probe-fixture',
            'vendor/ffmpeg/source/upstream.tar.gz': b'complete-pinned-source-fixture',
            'packaging/windows/ffmpeg/patch.diff': b'pinned-patch\n',
            'packaging/windows/ffmpeg/build.sh': b'pinned-recipe\n',
        }
        for path, data in inputs.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.manifest = dict(schema_version=1,
            upstream=dict(commit='immutable-source-commit', source_archive=dict(
                path='vendor/ffmpeg/source/upstream.tar.gz',
                **record(inputs['vendor/ffmpeg/source/upstream.tar.gz']))),
            release_binaries={name: record(inputs['vendor/ffmpeg/' + name])
                              for name in ('ffmpeg.exe','ffprobe.exe')},
            patch=dict(path='packaging/windows/ffmpeg/patch.diff',
                       **record(inputs['packaging/windows/ffmpeg/patch.diff'])),
            recipe=dict(build_script='packaging/windows/ffmpeg/build.sh',
                        build_script_sha256=record(inputs['packaging/windows/ffmpeg/build.sh'])['sha256']))
        self.write_manifest()
        self.bundle = self.root / 'validated-native.zip'

    def write_manifest(self):
        (self.root / native.MANIFEST).write_text(json.dumps(self.manifest), encoding='utf-8')

    def altered_bundle(self, replacements=None, additions=None):
        native.pack_bundle(self.bundle, self.root)
        changed = self.root / 'changed.zip'
        with zipfile.ZipFile(self.bundle) as original, zipfile.ZipFile(changed,'w') as target:
            for item in original.infolist():
                target.writestr(item, (replacements or {}).get(item.filename, original.read(item)))
            for name, value in (additions or {}).items():
                target.writestr(name,value)
        return changed

    def test_bundle_restores_exact_binaries_and_complete_source(self):
        native.pack_bundle(self.bundle,self.root)
        for path, _ in native.bundle_layout(self.root,self.manifest).values():
            path.unlink()
        native.install_bundle(self.bundle,self.root)
        native.verify_inputs(self.root)

    def test_bundle_identity_is_independent_of_json_line_endings(self):
        native.pack_bundle(self.bundle,self.root)
        (self.root/native.MANIFEST).write_text(json.dumps(self.manifest,indent=2),encoding='utf-8',newline='\r\n')
        native.install_bundle(self.bundle,self.root)

    def test_missing_or_wrong_source_is_not_accepted_as_binary_only_bundle(self):
        bad = self.altered_bundle({'source/upstream.tar.gz':b'not-the-pinned-source'})
        existing = self.root/'vendor/ffmpeg/ffmpeg.exe'
        existing.write_bytes(b'previous-installed-input')
        with self.assertRaises(ValueError):
            native.install_bundle(bad,self.root)
        self.assertEqual(existing.read_bytes(),b'previous-installed-input')

    def test_path_escape_and_duplicate_members_are_rejected(self):
        bad = self.altered_bundle(additions={'../outside.exe':b'payload'})
        with self.assertRaisesRegex(ValueError,'entries'):
            native.install_bundle(bad,self.root)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            with zipfile.ZipFile(self.bundle,'a') as target:
                target.writestr('ffmpeg.exe',b'duplicate')
        with self.assertRaisesRegex(ValueError,'duplicate'):
            native.install_bundle(self.bundle,self.root)

    def test_new_source_commit_cannot_reuse_old_bundle_metadata(self):
        native.pack_bundle(self.bundle,self.root)
        self.manifest['upstream']['commit']='changed-source-commit'
        self.write_manifest()
        with self.assertRaisesRegex(ValueError,'different source'):
            native.install_bundle(self.bundle,self.root)

    def test_changed_recipe_or_binary_refuses_pack(self):
        for relative in ('packaging/windows/ffmpeg/build.sh','vendor/ffmpeg/ffmpeg.exe'):
            with self.subTest(path=relative):
                path=self.root/relative
                original=path.read_bytes()
                path.write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    native.pack_bundle(self.bundle,self.root)
                self.assertFalse(self.bundle.exists())
                path.write_bytes(original)

    def test_manifest_path_escape_is_rejected_before_install(self):
        self.manifest['upstream']['source_archive']['path']='../outside.tar.gz'
        self.write_manifest()
        with self.assertRaisesRegex(ValueError,'path'):
            native.read_manifest(self.root)

    def test_pack_does_not_overwrite_existing_artifact(self):
        self.bundle.write_bytes(b'existing')
        with self.assertRaisesRegex(ValueError,'already exists'):
            native.pack_bundle(self.bundle,self.root)
        self.assertEqual(self.bundle.read_bytes(),b'existing')

    def test_https_without_embedded_credentials_is_required(self):
        native.validate_url('https://github.com/owner/repository/releases/download/tag/native.zip')
        for url in ('http://host/native.zip','file:///native.zip','https://user:password@host/native.zip',
                    'https://host/native.zip#fragment',''):
            with self.subTest(url=url), self.assertRaises(ValueError):
                native.validate_url(url)
        with self.assertRaises(ValueError):
            native._HTTPSRedirect().redirect_request(None,None,302,'',{},'http://host/native.zip')


if __name__ == '__main__':
    unittest.main()
