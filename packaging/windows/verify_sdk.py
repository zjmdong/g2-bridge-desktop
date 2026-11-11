"""Verify the original SDK baseline and any explicitly audited exact patches."""
from pathlib import Path
import hashlib
import json
import re


def digest(path):
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def verify(root):
    root = Path(root)
    baseline = json.loads((root/'docs/desktop/sdk-baseline.json').read_text(encoding='utf-8'))
    manifest_path = root/'docs/desktop/sdk-patches.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {
        'schema': 1, 'baseline_commit': baseline['commit'], 'files': {}}
    if manifest.get('schema') != 1 or manifest.get('baseline_commit') != baseline['commit']:
        raise ValueError('SDK patch manifest schema or baseline commit mismatch')
    patches = manifest.get('files')
    if not isinstance(patches, dict):
        raise ValueError('SDK patch manifest files must be an object')
    for name, patch in patches.items():
        if name not in baseline['files']:
            raise ValueError(f'SDK patch is not in the baseline: {name}')
        if not isinstance(patch, dict):
            raise ValueError(f'Invalid SDK patch record: {name}')
        original, patched = patch.get('original_sha256'), patch.get('patched_sha256')
        if original != baseline['files'][name]:
            raise ValueError(f'SDK patch original hash mismatch: {name}')
        if not isinstance(patched, str) or not re.fullmatch('[0-9a-f]{64}', patched) or patched == original:
            raise ValueError(f'Invalid or stale SDK patch hash: {name}')
        if not isinstance(patch.get('reason'), str) or not patch['reason'].strip():
            raise ValueError(f'SDK patch is missing its audit reason: {name}')
    changed = []
    for name, original in baseline['files'].items():
        expected = patches[name]['patched_sha256'] if name in patches else original
        try:
            actual = digest(root/name)
        except FileNotFoundError:
            actual = None
        if actual != expected:
            changed.append(name)
    if changed:
        raise ValueError('SDK files differ from baseline/audited patches: '+', '.join(changed))
    return dict(files=len(baseline['files']), commit=baseline['commit'], patched=sorted(patches))


def main():
    try:
        result = verify(Path(__file__).resolve().parents[2])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(str(exc))
    print(f"SDK verified: {result['files']} files at {result['commit']}; "
          f"{len(result['patched'])} exact audited patch(es)")


if __name__ == '__main__':
    main()
