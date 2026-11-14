"""Pack or restore the Windows FFmpeg inputs pinned by the release manifest.

The bundle contains the validated binaries AND the exact corresponding upstream
source archive. Restoring it never executes downloaded code or falls back to a
stock FFmpeg build. Build/revalidate native changes before creating a new bundle.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path('packaging/windows/ffmpeg/manifest.json')
METADATA = 'bundle.json'
CHUNK_SIZE = 1024 * 1024


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def beneath(root, relative):
    """Manifest paths must stay in the repository, including existing symlinks."""
    path = PurePosixPath(relative)
    if not relative or '\\' in relative or ':' in relative or path.is_absolute() or '..' in path.parts:
        raise ValueError('Invalid native input path')
    result = (Path(root) / path).resolve()
    if not result.is_relative_to(Path(root).resolve()):
        raise ValueError('Native input path escapes the repository')
    return result


def validate_record(record):
    if not re.fullmatch(r'[0-9a-f]{64}', record.get('sha256', '')):
        raise ValueError('Missing or invalid native SHA-256')
    if type(record.get('bytes')) is not int or not 0 < record['bytes'] < 1024 ** 3:
        raise ValueError('Missing or invalid native input size')


def read_manifest(root):
    manifest = json.loads((Path(root) / MANIFEST).read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1:
        raise ValueError('Unsupported native manifest schema')
    if set(manifest.get('release_binaries', {})) != {'ffmpeg.exe', 'ffprobe.exe'}:
        raise ValueError('Native release binaries have not been validated')
    for record in [*manifest['release_binaries'].values(), manifest['upstream']['source_archive'], manifest['patch']]:
        validate_record(record)
    # Validate all paths before doing any downloads or writing files.
    bundle_layout(root, manifest)
    beneath(root, manifest['patch']['path'])
    return manifest


def manifest_digest(manifest):
    # JSON whitespace/checkout line endings must not change bundle identity.
    canonical = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def bundle_layout(root, manifest):
    entries = {name: (beneath(root, 'vendor/ffmpeg/' + name), record)
               for name, record in manifest['release_binaries'].items()}
    source = manifest['upstream']['source_archive']
    path = beneath(root, source['path'])
    entries['source/' + path.name] = (path, source)
    return entries


def verify_file(path, record):
    if not Path(path).is_file() or Path(path).stat().st_size != record['bytes'] or sha256(path) != record['sha256']:
        raise ValueError(f'Native input checksum or size mismatch: {Path(path).name}')


def verify_recipe(root, manifest):
    patch = manifest['patch']
    verify_file(beneath(root, patch['path']), patch)
    recipe = manifest['recipe']
    for field, digest in recipe.items():
        if not field.endswith('_sha256'):
            continue
        source_field = field.removesuffix('_sha256')
        if source_field not in recipe or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Invalid native recipe checksum record')
        if sha256(beneath(root, recipe[source_field])) != digest:
            raise ValueError(f'Native recipe checksum mismatch: {source_field}')


def verify_inputs(root=ROOT):
    manifest = read_manifest(root)
    verify_recipe(root, manifest)
    for path, record in bundle_layout(root, manifest).values():
        verify_file(path, record)
    return manifest


def bundle_metadata(manifest):
    source = manifest['upstream']['source_archive']
    records = {**manifest['release_binaries'], 'source/' + PurePosixPath(source['path']).name: source}
    return dict(schema_version=1, manifest_sha256=manifest_digest(manifest),
                files={name: dict(bytes=record['bytes'], sha256=record['sha256'])
                       for name, record in records.items()})


def pack_bundle(output, root=ROOT):
    manifest = verify_inputs(root)
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Bundle output already exists; choose a new file')
    output.parent.mkdir(parents=True, exist_ok=True)
    # An unfinished ZIP is never exposed as a completed release input.
    with tempfile.TemporaryDirectory(prefix='native-bundle-', dir=output.parent) as stage:
        temporary = Path(stage) / 'native.zip'
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            metadata = json.dumps(bundle_metadata(manifest), sort_keys=True, indent=2).encode('utf-8')
            info = zipfile.ZipInfo(METADATA, date_time=(1980,1,1,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, metadata)
            for name, (path, record) in sorted(bundle_layout(root, manifest).items()):
                info = zipfile.ZipInfo(name, date_time=(1980,1,1,0,0,0))
                info.compress_type = zipfile.ZIP_DEFLATED
                with path.open('rb') as source, archive.open(info, 'w') as target:
                    shutil.copyfileobj(source, target, CHUNK_SIZE)
                # Detect inputs being edited while preparing the release bundle.
                verify_file(path, record)
        # Re-read and validate the content, not only the source files.
        validate_bundle(temporary, manifest, root)
        # Refuse a race that would overwrite another producer's output.
        with output.open('xb') as target, temporary.open('rb') as source:
            shutil.copyfileobj(source, target, CHUNK_SIZE)
    return output


def validate_bundle(bundle, manifest, root=ROOT, stage=None):
    """Verify ZIP members, metadata and streamed payloads before committing any."""
    layout = bundle_layout(root, manifest)
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(layout) | {METADATA}:
            raise ValueError('Native bundle has unexpected, missing or duplicate entries')
        info = archive.getinfo(METADATA)
        if info.file_size > 64 * 1024 or info.is_dir():
            raise ValueError('Invalid native bundle metadata size')
        metadata = json.loads(archive.read(METADATA).decode('utf-8'))
        if metadata != bundle_metadata(manifest):
            raise ValueError('Native bundle belongs to different source/recipe/binary inputs')
        for name, (_destination, record) in layout.items():
            info = archive.getinfo(name)
            mode = info.external_attr >> 16
            if info.is_dir() or mode & 0o170000 == 0o120000 or info.file_size != record['bytes']:
                raise ValueError('Invalid native bundle member type or size')
            digest, received = hashlib.sha256(), 0
            target_path = Path(stage) / name if stage else None
            if target_path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source:
                target = target_path.open('xb') if target_path else None
                try:
                    for block in iter(lambda: source.read(CHUNK_SIZE), b''):
                        received += len(block)
                        if received > record['bytes']:
                            raise ValueError('Native bundle member exceeds its pinned size')
                        digest.update(block)
                        if target:
                            target.write(block)
                finally:
                    if target:
                        target.close()
            if received != record['bytes'] or digest.hexdigest() != record['sha256']:
                raise ValueError(f'Native bundle checksum mismatch: {name}')


def install_bundle(bundle, root=ROOT):
    root = Path(root).resolve()
    manifest = read_manifest(root)
    verify_recipe(root, manifest)
    # Only a completely verified set of inputs can replace vendor files.
    with tempfile.TemporaryDirectory(prefix='native-inputs-', dir=root) as stage:
        validate_bundle(bundle, manifest, root, stage)
        for name, (destination, _record) in bundle_layout(root, manifest).items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(Path(stage) / name, destination)
    verify_inputs(root)
    return manifest


def validate_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('Native bundle URL must be HTTPS without credentials or a fragment')


class _HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # GitHub releases legitimately redirect to a separate asset host.
        validate_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def install_url(url, root=ROOT):
    validate_url(url)
    manifest = read_manifest(root)
    verify_recipe(root, manifest)
    limit = sum(record['bytes'] for _path, record in bundle_layout(root, manifest).values()) + 2 * 1024 * 1024
    with tempfile.TemporaryDirectory(prefix='native-download-') as stage:
        bundle = Path(stage) / 'native.zip'
        request = urllib.request.Request(url, headers={'User-Agent':'Goggles-Bridge-Native-Bootstrap'})
        opener = urllib.request.build_opener(_HTTPSRedirect())
        with opener.open(request, timeout=60) as response, bundle.open('xb') as output:
            validate_url(response.url)
            declared = response.headers.get('Content-Length')
            if declared and int(declared) > limit:
                raise ValueError('Native bundle download exceeds expected size')
            received = 0
            for block in iter(lambda: response.read(CHUNK_SIZE), b''):
                received += len(block)
                if received > limit:
                    raise ValueError('Native bundle download exceeds expected size')
                output.write(block)
        return install_bundle(bundle, root)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    pack = commands.add_parser('pack', help='Create a bundle from locally validated native inputs')
    pack.add_argument('--output', required=True, type=Path)
    install = commands.add_parser('install', help='Restore a verified local or HTTPS native bundle')
    source = install.add_mutually_exclusive_group(required=True)
    source.add_argument('--bundle', type=Path)
    source.add_argument('--url')
    commands.add_parser('verify', help='Verify existing vendor native inputs without running them')
    args = parser.parse_args(argv)
    try:
        if args.command == 'pack':
            path = pack_bundle(args.output)
            print(f'Native bundle: {path}\nSHA-256: {sha256(path)}')
        elif args.command == 'install':
            manifest = install_bundle(args.bundle) if args.bundle else install_url(args.url)
            print(f'Verified native inputs: {manifest_digest(manifest)}')
        else:
            manifest = verify_inputs()
            print(f'Verified native inputs: {manifest_digest(manifest)}')
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        parser.exit(1, f'Native input preparation failed: {exc}\n')


if __name__ == '__main__':
    main()
