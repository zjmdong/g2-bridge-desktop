"""Refresh the pinned FFmpeg patch after capture, encoding or scheduling edits.

This does not build, publish, modify vendor binaries, or approve old binary hashes
for a changed source tree. Run the build/validation before recording new outputs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
COMMIT = '946fcce07b6dcd0331c8cc609192aeff5e1924f8'
SOURCE_DIRS = ('libavfilter', 'libavcodec', 'fftools')


def git(source, *args):
    return subprocess.check_output(['git', *args], cwd=source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-tree', type=Path,
                        default=ROOT / 'work/ffmpeg-src-n9.0.2')
    args = parser.parse_args()
    source = args.source_tree.resolve(strict=True)
    if git(source, 'rev-parse', 'HEAD').decode().strip() != COMMIT:
        parser.error('The FFmpeg checkout must be at the pinned n9.0.2 commit')
    patch = git(source, 'diff', '--binary', '--full-index', 'HEAD', '--', *SOURCE_DIRS).decode()
    changed = git(source, 'diff', '--name-only', 'HEAD', '--', *SOURCE_DIRS).decode().splitlines()
    added = git(source, 'ls-files', '--others', '--exclude-standard', '--', *SOURCE_DIRS).decode().splitlines()
    for name in added:
        is_test_runner = name.startswith('fftools/tests/') and Path(name).suffix == '.ps1'
        if Path(name).suffix not in ('.c', '.h', '.cpp') and not is_test_runner:
            raise ValueError(f'Unexpected untracked FFmpeg source input: {name}')
        text = (source / name).read_text(encoding='utf-8')
        lines = text.splitlines()
        patch += (f'diff --git a/{name} b/{name}\nnew file mode 100644\n'
                  f'--- /dev/null\n+++ b/{name}\n@@ -0,0 +1,{len(lines)} @@\n'
                  + ''.join('+' + line + '\n' for line in lines))
        if not text.endswith('\n'):
            patch += '\\ No newline at end of file\n'
    if not patch:
        raise ValueError('No FFmpeg changes found')
    target = HERE / 'ffmpeg-n9.0.2-goggles.patch'
    target.write_text(patch, encoding='utf-8', newline='\n')
    subprocess.run(['git', 'apply', '--check', '--reverse', str(target)], cwd=source, check=True)

    manifest_path = HERE / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    old_patch_hash = manifest['patch']['sha256']
    old_recipe_hashes = {name: manifest['recipe'].get(name + '_sha256')
                         for name in ('build_script', 'clock_test')}
    for name in old_recipe_hashes:
        manifest['recipe'][name + '_sha256'] = hashlib.sha256(
            (ROOT / manifest['recipe'][name]).read_bytes()).hexdigest()
    new_patch_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest['patch'] = dict(path=target.relative_to(ROOT).as_posix(),
                            bytes=target.stat().st_size, sha256=new_patch_hash)
    manifest['patched_source_files'] = {
        # Git for Windows may check tracked source out as CRLF. The archive and
        # the emitted patch use LF, so identify the actual build input bytes.
        name: hashlib.sha256((source / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        for name in sorted(set(changed + added)) if (source / name).is_file()
    }
    manifest['source_hash_line_endings'] = 'LF'
    recipe_changed = any(manifest['recipe'][name + '_sha256'] != old_hash
                         for name, old_hash in old_recipe_hashes.items())
    if old_patch_hash != new_patch_hash or recipe_changed:
        manifest.pop('reference_research_build', None)
        manifest.pop('validated_outputs', None)
        manifest.pop('release_binaries', None)
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(f'Updated patch for {len(changed) + len(added)} files; reverse application checked.')
    print('Rebuild and validate before assigning executable hashes to this patch.')


if __name__ == '__main__':
    main()
