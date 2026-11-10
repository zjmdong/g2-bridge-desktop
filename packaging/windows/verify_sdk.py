"""Assert SDK source is identical to the recorded upstream baseline."""
from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parents[2]
baseline = json.loads((root/'docs/desktop/sdk-baseline.json').read_text(encoding='utf-8'))
changed = [name for name, digest in baseline['files'].items()
           if hashlib.sha256((root/name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() != digest]
if changed:
    raise SystemExit('SDK files changed: '+', '.join(changed))
print(f"SDK baseline intact: {len(baseline['files'])} files at {baseline['commit']}")
