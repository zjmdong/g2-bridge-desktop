# Windows 0.1.0 validation

## Scope and observed hardware

Windows 11 x64, NVIDIA RTX 4060 Laptop GPU, 3440×1440 / 60 Hz primary monitor,
DJI Goggles 2 reporting 01.14.0000. Original SDK baseline remains
a34690a58d48f0cd9b43cdeddf39b5efaf024b9c, 70 protected files unchanged.

The user confirmed that the upstream fixed colour pattern and a separately
generated 10-second moving 1080p/60 clip were visible in the goggles. Original
desktop capture, Baseline-only, 2 KB USB writes, and intra-refresh=0 alone did
not produce a visible desktop. The user then left; subsequent results below
are host-side evidence, not optical confirmation.

## Compatibility adapter

The desktop stream carried sRGB transfer characteristic 13 and, on gfxcapture,
matrix coefficient 5. The successful synthetic clip omitted video-signal VUI.
ddagrab also produced a non-square 2881:2880 sample aspect ratio for this screen.
Changing only the NVENC intra-refresh flag did not yield recurring IDRs with
the remaining SDK flags on this driver.

The app now explicitly converts desktop RGB to limited-range NV12, sets square
pixels, omits inherited colour descriptors, uses Baseline, disables both intra
refresh switches and forces an IDR each second. It uses the SDK process/run
injection boundaries, with no SDK patches or USB protocol changes.

Both adapted capture paths generated 180 frames and decoded without errors.
Maximum frame sizes were 28,408 and 28,796 bytes, below SDK's 56,000-byte limit.
SPS and PPS were byte-identical to the successful motion clip at 60 fps / 8 Mbps:

- SPS SHA-256: `3a4b3d069d8817a1bd892efaaf744799c4501afafdd67b362fb66148b6bc9161`
- PPS SHA-256: `f3051b36ce3f91c60b265a3ea976d88f6256dad3187f4aea5ffcf01ac6c3cc16`

A real GUI-worker-path USB smoke run sent 979 desktop frames in 17.27 seconds
(including startup), stable segments 59.98 fps, no oversized frames, no receive
discard, and clean stop/exit. USB send p95 was approximately 0.85 ms; this is
neither capture-to-display latency nor proof the goggles rendered the picture.
The installed frozen worker repeated this test: 979 frames, stable segments
59.97–59.99 fps, zero oversized frames and clean shutdown.

`python packaging/windows/check_capture.py` reproduces header/decode/IDR checks
without saving or uploading desktop media. Use an unlocked Windows desktop
and the pinned FFmpeg/NVIDIA stack. Unit tests cover source disappearance,
ambiguous/primary virtual targets, targeted layout changes, driver tampering,
capture adapters, settings migration and existing GUI/worker lifecycle. All
28 desktop tests passed. The 120 Hz rejection and removal recovery tests use
explicit simulated display state, not an installed virtual monitor.

## Packaging and interface

The per-user 0.0.1 -> 0.1.0 installer upgrade completed with exit code 0 on this
host and preserved the existing settings file byte-for-byte. Installed product
version is 0.1.0. Frozen environment checks found the bundled FFmpeg, working
NVENC and verified DJI USB component. Installation retained the original
Windows 10 build 19041 minimum. The application itself is not code-signed.

Native UI review identified two material state-copy issues (actual refresh rate
and uninstall recovery); both were fixed and the reviewer returned `ship` for
those two scored fixes. Documentation review found no reusable visual-system
change; the incumbent DESIGN.md was preserved. Historical 0.0.1 capability prose
there is stale; PRODUCT.md, USER_GUIDE.md and this validation record describe the
current experimental feature and its acceptance limits.

## Extended display

VDD 25.7.23 package SHA-256:
`e24210692b442b39af763536330ce78b423f19342b7a7792c26de3944e418b3a`.
Original catalog and DLL signatures are Valid (SignPath Foundation).
No certificates are imported and signature enforcement is not changed.
The pinned source's SETDISPLAYCOUNT calls ReloadDriver with a pipe handle
where a WDF object is expected; the client never calls either command.

The host already has GameViewer, Oray and Virtual Desktop drivers. These were
left untouched. VDD is not installed on this host, and creating a display
device requires Windows administrator authorization. Thus actual VDD device
creation, capture from it, disconnect and rollback remain hardware acceptance
items. The app exposes normal Windows elevation and marks this source experimental.

## Remaining acceptance

- User confirms adapted live desktop is visible after entering Virtual Flight.
- Complete Windows driver authorization, enable 1080p extended desktop, verify
  physical primary layout is unchanged, and launch a simulator on that desktop.
- Verify visible goggles output, move/close simulator, disconnect and remove the
  owned virtual device; confirm existing third-party displays remain untouched.
- Broader supported-GPU and 75/90/100 fps tests; macOS is outside this release.

Do not describe this build as an optically verified black-screen fix until those
observations are recorded. Private local captures and USB dumps are not committed.
