# Windows 0.1.0 validation

## Scope and observed hardware

Windows 11 x64, NVIDIA RTX 4060 Laptop GPU, 3440×1440 / 60 Hz primary monitor,
DJI Goggles 2 reporting 01.14.0000. Original SDK baseline remains
a34690a58d48f0cd9b43cdeddf39b5efaf024b9c, 70 protected files unchanged.

The user confirmed that the upstream fixed colour pattern and a separately
generated 10-second moving 1080p/60 clip were visible in the goggles. Original
desktop capture, Baseline-only, 2 KB USB writes, and intra-refresh=0 alone did
not produce a visible desktop. After installing 0.1.0, on 2026-11-10 the user
confirmed that the primary desktop was visible at 60 fps / 8 Mbps. The user
also confirmed the independent extended-display test below. Other measurements
are host-side evidence and do not establish capture-to-display latency.

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
left untouched. The user completed Windows administrator authorization for the
installed 0.1.0 worker. Driver installation returned success / code 0 without a
reboot. Windows enumerated the owned VDD monitor as a separate, non-primary
1920×1080 / 60 Hz desktop at (3440, 0). The physical primary retained
3440×1440 / 60 Hz at (0, 0), with its primary and active flags unchanged.

Using the installed GUI, the extended source was selected and streamed at
60 fps / 8 Mbps through its actual HMONITOR. A temporary native window on only
that desktop displayed `EXTENDED DISPLAY - 1080p`, an advancing timer and a
moving green square. The user confirmed all three were visible in the goggles.
This validates independent desktop selection, capture, encoding, USB delivery
and optical output; it is not a simulator performance benchmark.

The 56.33-second GUI run sent 3,266 frames, with steady 5-second intervals at
58.19–59.62 fps, zero oversized frames, no receive discard and a clean stop.
Maximum observed frame size was 30,664 bytes. USB send p95 was 0.40–0.45 ms;
this does not measure end-to-end latency. The SDK log's raw `starting` record
describes SDK defaults; the desktop adapter disables intra-refresh and the
actual encoder command and GUI-worker event reflect that override.

After closing the test window and stopping the stream, the installed GUI's
disconnect control left only the physical primary active and gated streaming.
However, re-enabling failed with Windows status -1. This is a confirmed 0.1.0
bug, fixed separately in 0.1.1 using explicit CCD paths; see VALIDATION-0.1.1.md.
Primary resolution, refresh rate, position and primary/active flags remained
unchanged. Driver removal and forced rollback were not exercised on this
working installation.

## Remaining acceptance

- Test an actual simulator and its input/fullscreen behaviour on that desktop.
- Exercise driver removal and failure rollback on a dedicated test installation.
  The working driver is retained on this user's computer.
- Broader supported-GPU and optical 75/90/100 fps tests; macOS is outside this
  release. The existing host capture matrix passed all 16 combinations of
  capture path, 60/75/90/100 fps and p1/p4 (1,380 decoded frames); those are not
  optical tests of higher frame rates.

The primary black-screen fix and independent 1080p output are optically verified
on this host and firmware. The compatibility changes were tested together, so
the evidence does not isolate a single encoder flag as the sole root cause.
Private local captures and USB dumps are not committed.
