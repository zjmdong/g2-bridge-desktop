"""Find a newer release on GitHub and download its installer."""
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.request

def release_repository():
    """Fork installers can pin their own channel; source builds default to upstream."""
    try:
        name = json.loads(Path(__file__).with_name('release-channel.json').read_text(encoding='utf-8'))['repository']
        if re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', name):
            return name
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return 'Ammaar-Alam/goggles-bridge'


REPOSITORY = release_repository()
LATEST = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
DOWNLOADS = f'https://github.com/{REPOSITORY}/releases/download/'
ASSET = '.dmg' if sys.platform == 'darwin' else '-Setup.exe'
# run as sh -c SWAP swap IMAGE APP PID: waits for the app to close, replaces it with the copy in the disk image
# when that copy is signed like the running app, and reopens the app either way
SWAP = '''
image=$1 app=$2
while kill -0 "$3" 2>/dev/null; do sleep .2; done
mount=$(mktemp -d)
if hdiutil attach -quiet -nobrowse -readonly -mountpoint "$mount" "$image"; then
  new="$mount/$(basename "$app")"
  requirement=$(codesign -d -r- "$app" 2>&1 | sed -n 's/^designated => //p')
  if [ -n "$requirement" ] && codesign --verify --deep --strict -R="$requirement" "$new" \\
      && ditto "$new" "$app.new" && mv "$app" "$app.old" && mv "$app.new" "$app"; then
    rm -rf "$app.old"
  fi
  rm -rf "$app.new"
  hdiutil detach -quiet "$mount" && rmdir "$mount"
fi
open "$app"
'''


def newer(version, current):
    def numbers(text):
        return tuple(int(part) for part in text.split('.'))
    return numbers(version) > numbers(current)


def find(current):
    """Return the version, installer URL, and SHA-256 of a release newer than current, or None."""
    request = urllib.request.Request(LATEST, headers={'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=10) as reply:
        release = json.load(reply)
    if not newer(release['tag_name'], current):
        return None
    for asset in release['assets']:
        digest = asset.get('digest') or ''
        if (asset['name'].endswith(ASSET) and asset['browser_download_url'].startswith(DOWNLOADS)
                and digest.startswith('sha256:')):
            return dict(version=release['tag_name'], url=asset['browser_download_url'], sha256=digest[7:])
    return None


def download(update, folder):
    """Save the installer and return its path. Delete a file that doesn't match the published SHA-256."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/f'GogglesBridge{ASSET}'
    digest = hashlib.sha256()
    with urllib.request.urlopen(update['url'], timeout=30) as reply, path.open('wb') as file:
        while block := reply.read(1 << 20):
            digest.update(block)
            file.write(block)
    if digest.hexdigest() != update['sha256']:
        path.unlink()
        raise ValueError("The download doesn't match the published SHA-256")
    return path
