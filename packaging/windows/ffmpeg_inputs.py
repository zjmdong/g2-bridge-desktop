"""Verify the corresponding FFmpeg source inputs before packaging any release."""
import hashlib


def verify_ffmpeg_sources(root, manifest):
    entries = [manifest['upstream']['source_archive'], manifest['patch']]
    recipe = manifest['recipe']
    entries.extend(dict(path=recipe[key], sha256=recipe[key+'_sha256'])
                   for key in ('build_script', 'clock_test', 'fresh_wait_test', 'fresh_wait_runner'))
    for entry in entries:
        path = root/entry['path']
        if not path.is_file():
            raise RuntimeError(f'Missing FFmpeg source input: {entry["path"]}')
        if 'bytes' in entry and path.stat().st_size != entry['bytes']:
            raise RuntimeError(f'FFmpeg source length mismatch: {entry["path"]}')
        with path.open('rb') as source:
            actual = hashlib.file_digest(source, 'sha256').hexdigest()
        if actual != entry['sha256']:
            raise RuntimeError(f'FFmpeg source hash mismatch: {entry["path"]}; refresh, rebuild and validate first')
