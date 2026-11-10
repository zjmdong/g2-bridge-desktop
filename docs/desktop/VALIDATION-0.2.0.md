# Windows 0.2.0 validation

Date: 2026-11-10. SDK baseline: a34690a58d48f0cd9b43cdeddf39b5efaf024b9c.
Branch: feat/windows-streaming-v0.2.0, user fork zjmdong/g2-bridge-desktop.
Physical host: Windows x64, AMD 780M/NVIDIA RTX 4060 Laptop, 16 logical CPUs,
3440x1440/60 Hz primary. Goggles 2 firmware 01.14.0000; DJI driver 5.0.0.7.

## Hardware findings and optical acceptance

- Repeated IDRs every second correlated with flashes and changing grey levels in
  the user's 60 fps lens recording. Removing all recurring IDRs blacked out the
  goggles. Retaining forced IDRs at seconds 0/1/2, then stopping periodic refresh,
  restored the image and removed the periodic flash. No oversize/discard events
  accompanied that optical failure.
- Native-rate DDA plus compacted timestamps achieved only about 72 fps at a
  requested 100 fps. DDA sampling at 240 Hz, wall-clock frame selection and a
  transport pacer achieved 99.99–100.01 fps in stable five-second USB windows.
  A local pacing sample improved p95 frame gap from about 25 to 11.4 ms; it is
  not a measurement of the goggles' presentation latency.
- User first reported tearing at 60 fps. At 100 fps they reported tearing gone,
  then substantial improvement with remaining slight motion unevenness after
  pacing. The single-reference trial was described as motion basically normal.
  There is no claim of perfect frame timing under every simulator load.
- NVENC output decoded locally to exactly neutral grey interiors (U=V=128), but
  the user still saw pink/red patches in the goggles, including with one reference
  frame. Software libx264 at the same 1080p100/8 Mbps and USB protocol eliminated
  the patches; the user explicitly confirmed uniform grey. The release therefore
  uses software encoding. This isolates the problematic NVENC/firmware path; it
  does not establish a general defect in every NVIDIA GPU or Goggles firmware.
- User also explicitly confirmed normal picture and uniform greys at native
  720p100/40 Mbps with software encoding. That USB run sent 7,718 frames in 78.30 s
  including startup, with zero discarded bytes and a clean automatic detach.
- The 1080p100/8 Mbps software run sent 7,786 frames in 78.89 s including startup,
  with zero discarded bytes. Stable windows were 99.99–100.01 fps. Stop returned
  the virtual desktop to inactive state and preserved the primary display.

## Local mode, encoder and performance checks

- Signed VDD 25.7.23 configuration was updated with the user's Windows elevation.
  Windows enumerated all eight combinations of 1280x720/1920x1080 and 60/75/90/100
  Hz. All were attached and detached successfully; primary mode/position/refresh
  remained unchanged. Driver binary signatures were preserved.
- Sixteen local captures covered both resolutions, all four rates, both speed
  presets and the maximum valid bitrate at each rate (24/30/32/40 Mbps). Every
  stream decoded without errors; every frame stayed at or below 56,000 bytes.
  Exactly three startup IDRs were present. Largest observed frame: 54,702 bytes.
- A separate 1080p100/40 Mbps high-motion test encoded 1,200 frames per preset.
  Ultrafast: 530.2 fps, max 47,549 bytes, average 34.186 Mbps. Veryfast: 312.1 fps,
  max 45,965 bytes, average 33.451 Mbps. No oversized frames or decode errors.
  These are unconstrained CPU encoder throughput checks, not live capture FPS.
- A 720p100/40 Mbps live encoder sample consumed 25.56 CPU seconds over 26.77
  elapsed seconds (about one logical core, ~6% of this 16-thread host), 90.9 MiB
  working set. Game load and other hardware can change these costs substantially.
- Constant-work sender timing/counters measured 0.265 microseconds per call in a
  100,000-call microbenchmark. A stalled-output regression fills/coalesces bounded
  IPC queues without blocking the producer. No per-frame formatting or IPC write
  occurs in the video sender. This is measured low overhead, not a zero-cost claim.

## Automated and UI checks

- 47 desktop tests passed: settings/migration and bitrate budget, firmware gate,
  driver integrity, CCD rollback, capture identities, resolution adaptation,
  display cleanup on failure, USB hotplug/manual-stop logic, probe/stream
  exclusion, stale probe suppression, pacing and telemetry/IPC backpressure.
  A device rejection remains visible after virtual-display cleanup; d6 includes
  the Virtual Flight recovery instruction.
- SDK verifier confirmed all 70 protected files match the baseline. Original
  CLI/protocol/encoder files are unchanged.
- Actual Qt widgets were rendered offscreen at 1120x800 and 920x680. Checked
  source/setup, parameters, streaming statistics, device/driver and help pages,
  plus unsupported-firmware state. Offscreen rendering explicitly loads Windows
  fonts and uses labeled fixtures; it does not claim live USB acceptance.
- Native desktop input was stopped when the user pressed Escape. Subsequent
  rendering/tests used isolated processes and did not inject desktop input.

## Release gates

- PyInstaller and Inno Setup built the 0.2.0 Windows x64 application and installer.
  The actual frozen worker passed its bundled libx264 environment probe and
  emitted USB presence before stopping cleanly on the JSON stop command.
- An isolated offscreen Qt instance used the frozen worker, actual USB device and
  virtual display at 1080p100/40 Mbps. Startup auto-streamed 451 frames with no
  discarded bytes; manual stop retracted the display and suppressed auto-restart.
  A synthetic removal/insertion edge triggered the next real worker attempt,
  but the goggles rejected the second session with d6. The display was retracted.
  This is not evidence of a successful physical unplug/replug: the USB cable
  remained connected. The test harness timed out awaiting a second successful
  stream; its hidden-window exit handling required cleanup. No video/USB worker
  remained and the primary display retained 3440x1440/60 Hz.
- The per-user installer upgraded the installed application successfully (exit 0,
  executable version 0.2.0). The settings file was byte-for-byte unchanged by the
  installer. All installed distribution files matched their build SHA-256 hashes.
  The installed worker passed the encoder and presence/stop probes again.
  On first launch, existing 1080p100/40 Mbps quality settings were retained, the
  old capture choice migrated to Desktop Duplication and the new auto-start
  default was enabled. The installed app automatically streamed 2,834 frames
  before USB removal, with zero discarded bytes, then ended the session.
- The user physically unplugged/replugged USB and explicitly confirmed automatic
  start, a normal picture, then automatic virtual-desktop removal on unplug.
  The second installed session sent 1,943 frames with zero discarded bytes;
  stable USB windows measured 99.93–99.99 fps. After unplug, PnP presence was
  false, the owned virtual display was inactive, and the physical primary
  remained 3440x1440/60 Hz at (0,0).

Installer: `DJI-Goggles-Streamer-0.2.0-Setup.exe`, 61,803,389 bytes.
SHA-256: `32e4e519a7d4498b31bacfa9d6a3f40d6ca793dd9c785140ef2d77b13bc16d9c`.
The source archive and a checksum manifest accompany this installer.

## Limits

Only Goggles 2 01.14.0000 was optically tested in this release. Other firmware,
Integra, AMD/Intel-only computers and long-duration game/thermal load remain
unverified. The adapter's live USB duration excludes capture, CPU encoding,
pacing and device display; actual end-to-end latency is not available from the
SDK. Bandwidth counts successfully written protocol/video bytes, not bus overhead.
MI04 uses 512-byte Bulk endpoints (USB 2.0 High Speed); faster host ports cannot
upgrade that device route to SuperSpeed. Goggles panel timing remains device-owned.

The application installer is not publisher-code-signed. Drivers retain their
original signatures. The installer bundles no DJI firmware or proprietary DJI
installer; first driver setup downloads the pinned official package or imports
the exact offline package. SDK frame limits remain enforced for software output.
