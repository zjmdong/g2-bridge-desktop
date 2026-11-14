# Windows native release inputs

The Windows desktop integration requires the modified FFmpeg build pinned in
[the manifest](windows/ffmpeg/manifest.json). A stock FFmpeg cannot provide its
native clock, bounded mailbox and asynchronous encoder extensions. The Windows
release job therefore requires an explicit validated native-input bundle.
The macOS job and its native capture helper do not consume this bundle.

## Prepare once after validating native changes

Build the source archive, patch and toolchain using the
[MSYS2 UCRT64 recipe](windows/ffmpeg/README.md). The recipe pins the FFmpeg commit,
source archive SHA-256, GCC/NASM/ffnvcodec versions, MSYS2 package URLs and hashes.
It does not automatically approve a newly built executable: compare/review its
validation results before updating `release_binaries` in the manifest.
Do not replace those identities with a runner's output merely to make CI pass.

After the locally validated binaries are in `vendor/ffmpeg` and the exact
corresponding upstream archive is in `vendor/ffmpeg/source`, run:

```powershell
python packaging/bootstrap_native.py verify
python packaging/bootstrap_native.py pack --output dist/GogglesBridge-Native-Windows.zip
```

The bundle includes `ffmpeg.exe`, `ffprobe.exe`, the complete upstream source
archive and metadata bound to the canonical manifest. The helper verifies
file sizes, SHA-256 values, the patch and each hashed recipe input. It does not
execute FFmpeg or perform a hardware test. Keep the printed bundle hash with
the release validation evidence. Upload the resulting artifact only when
authorized as part of preparing a release.

The repository does not invent or assume an already-published binary URL.
Publish the bundle at a stable HTTPS location you control, or distribute it
as a local build input. GitHub release asset URLs are supported, including
their HTTPS asset-host redirects. Use a non-secret URL; an Actions input or
repository variable is not a secret store.

## Restore on a clean builder

```powershell
python packaging/bootstrap_native.py install --bundle path/to/GogglesBridge-Native-Windows.zip
# Or supply the actual HTTPS URL of the prepared artifact:
python packaging/bootstrap_native.py install --url "$env:WINDOWS_NATIVE_BUNDLE_URL"
python packaging/build_windows.py --repository owner/repository
```

The helper restricts the bundle to the expected members, rejects duplicate
members and symlinks, streams bounded payloads into temporary staging, and
checks every size/hash before replacing any vendor input. It also requires
the bundle's full manifest identity to match this checkout. A stale bundle
from another native patch or recipe is rejected even if filenames match.
There is no fallback to stock FFmpeg, disabled integrity checks or a changed
source archive hash.

## Release workflow

For a manual Release workflow run, enter `windows_native_bundle_url`, or set
the repository Actions variable `WINDOWS_NATIVE_BUNDLE_URL`. The explicit
run input takes precedence. Version-file pushes cannot carry a manual input,
so automated releases should use the repository variable. When the workflow
automatically dispatches a second run after its version PR merge, it forwards
an explicitly supplied native bundle URL.

The Windows job restores and verifies the bundle before invoking the installer
builder. A missing URL fails with a preparation message. Missing or mismatched
inputs fail closed. This is a documented release prerequisite: a fresh checkout
does not contain the validated native binaries or generated source archive.
The job passes `github.repository` to the Windows builder so fork installers
keep their own update channel.

No URL is required by the macOS job. Its signing, notarization, packaging and
artifact steps remain independent of the Windows native inputs. The final
draft still waits for both platform jobs, as in the upstream workflow.
