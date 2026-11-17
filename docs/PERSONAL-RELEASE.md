# Goggles Bridge Personal 0.0.1

This is zjmdong's Windows edition of [Goggles Bridge](https://github.com/Ammaar-Alam/goggles-bridge),
maintained on the `dev` branch of [g2-bridge-desktop](https://github.com/zjmdong/g2-bridge-desktop).
Its version sequence starts at 0.0.1 independently of upstream. Upstream authorship
and the GPL-3.0 license are retained.

## Included code

- Full virtual-display implementation through `6abd2b37a40abb449fe9e929a794743666fd1494`,
  including application-managed installation, repair, removal, protected elevated
  maintenance, owned-device checks, and uninstall cleanup. Later scope reductions
  of PR #48 are excluded.
- Upstream app and AMD AMF changes through `b307f4d` (upstream 0.3.0).
- Native capture and isolated USB worker from `2e9f910`, with the capture delivery
  adjustment in `16a80ab`. This includes bounded raw-frame replacement, asynchronous
  NVENC, GPU scaling, chroma offsets, source-clock alignment and background logging.
- Integration connecting the leased virtual display to the native worker. The
  display remains leased until the worker exits; virtual streams stop on disconnect
  instead of retaining an invisible extended screen while reconnecting.
- The existing virtual-display implementation differs from the specified cutoff
  only at its capture entry point, which now accepts the native worker.

## Use and separation from upstream

Install `GogglesBridgePersonal-0.0.1-Setup.exe`. The app has a separate installer ID,
`Goggles Bridge Personal` installation directory and settings/log directory. Its
update check and issue links point to this fork; update assets must match the
`GogglesBridgePersonal-VERSION-Setup.exe` name exactly.

Choose **Virtual Display** under Source and use **Setup guide** to manage the
driver. Both 720p and 1080p desktops are encoded as 1080p to fill the goggles.
The driver retains its existing **Goggles Bridge Display** identity from the cutoff
commit. A verified installation from that version is reused, not duplicated.
This machine-wide driver is shared by compatible local builds; do not uninstall
another build's display component while relying on it. Older unverifiable devices
must be removed using their original app before setup, as the cutoff already requires.

Packaged NVIDIA installations default to native Desktop Duplication; NVIDIA
virtual screens use the native worker regardless of the saved physical-capture
preference. Physical Windows Graphics Capture and AMD AMF use stock FFmpeg. All
existing advanced controls remain available. Stopping a virtual stream releases
the screen. The 6 ms delivery offset at 100 fps on NVIDIA (8 ms otherwise) is an
internal scheduling policy, not a claim about monitor-to-eye latency.

## Build and release

Use Windows x64, Python with `requirements-app.txt`, PyInstaller 6.22.3, Node.js for
UI tests, and Inno Setup 6 on PATH. Prepare the pinned native executable and source
archive using [the native build recipe](../packaging/windows/ffmpeg/README.md).

```powershell
python -m pip install -r requirements-app.txt pyinstaller==6.22.3
python -m unittest discover -s tests -v
node --test tests/test_virtual_ui.mjs
python packaging/verify_native.py
python packaging/build_windows.py --native
& 'dist/Goggles Bridge Personal/Goggles Bridge Personal.exe' --self-test
python packaging/personal_source_bundle.py
```

Always pass `--native` for this edition's release. The installer contains both
FFmpeg implementations, the isolated worker, full native corresponding source,
patch, pinned build recipe and licenses. The source bundle contains the exact Git
commit and native FFmpeg upstream archive. The binary's SHA-256 must match the
manifest before packaging. Native inputs can also be recovered from an existing
verified release under `ffmpeg-native/` and `ffmpeg-native/source/`.

Commit on `dev`, build and verify, then publish the installer, source bundle and
`SHA256SUMS.txt` to this repository's Release using the numeric version as its tag.
The inherited upstream automatic release workflow is replaced with manual checks:
it must not create upstream-style version PRs, publish a stock-only installer or
require the author's macOS signing credentials. This release ships Windows only.

## Validation on 2026-11-17

- 199 Python tests: passed, with one macOS-only test skipped on Windows.
- Six browser UI tests: passed, including source choices, 720p output explanation,
  repair/removal controls and non-Windows behavior.
- Packaged hidden-window self-test: exit 0.
- Packaged native worker: starts, waits for goggles and stops through its IPC
  command with exit 0.
- Native physical display (3440 × 1440) and virtual displays (1280 × 720 and
  1920 × 1080): each encoded 100 frames at a requested 100 fps with exit 0 on the
  local NVIDIA adapter. Virtual screens were released and the original DXGI display
  inventory was restored.
- Native executable, upstream archive, patch and recipe passed manifest checks.

No goggles were attached during this release check. These checks do not establish
optical latency, long-duration streaming stability, or fresh installer/UAC lifecycle
validation. The installed driver was already owned and configured. Perform a headset
streaming check after installation before using this build for a long session.
