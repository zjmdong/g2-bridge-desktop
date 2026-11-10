# Windows 0.0.1 validation

Date: 2026-11-10. SDK baseline:
`a34690a58d48f0cd9b43cdeddf39b5efaf024b9c`.

## Completed

- 18 independent desktop unit/integration tests passed. Coverage includes
  compatibility allow/block decisions, route validation during manifest reads,
  no simulator entry during information probes, verification on every connection,
  transport cleanup after failure/cancellation, bounded encoder termination,
  driver hash rejection, settings budget/roundtrip/recovery, Qt worker ownership,
  duplicate-start prevention, graceful stop, status updates, accessible names and
  contextual recovery actions.
- SDK integrity: 70 recorded source/test/research files match the baseline after
  Git line-ending normalization. No SDK implementation or original test changed.
- Original SDK suite: 89 tests, 87 passed, one macOS test skipped, one existing
  environment-dependent failure (`test_gpu_priority_is_best_effort`). The same
  assertion failed before desktop development; GPU priority is best-effort in
  production. This result is not reported as an all-green SDK suite.
- Real host checks: Windows build 26200 x64; NVIDIA GeForce RTX 4060 Laptop GPU.
  Bundled FFmpeg synthetic NVENC encode passed. SDK one-frame capture checks
  passed for both `gfxcapture` and `ddagrab` at default 1080p100 settings.
- Frozen worker: UTF-8 JSON event pipe, bundled FFmpeg resolution and NVENC
  environment check passed, with no DJI driver present.
- DJI Assistant 2 Consumer 2.1.42 downloaded from the fixed official CDN URL.
  Its SHA-256 and Authenticode signature were verified. Extraction of the signed
  5.0.0.7 driver succeeded; all required driver file hashes match the pinned
  manifest, including the SDK's exact DLL hash. The driver CAT signature is valid.
- Native GUI captures at 1120×800 and 920×680 reviewed. Fresh finish reviewer
  scored the three required corrections resolved (dropdown indicators,
  accessible field names, actionable footer recovery). This is a verdict on
  those corrections, not a hardware compatibility certification.
- Per-user installer completed with exit code 0 into a path containing Chinese
  characters and spaces. Installed application launched successfully, displayed
  its real environment state and exposed the corrected accessible field names.
  Installed frozen worker and driver extraction were smoke-tested separately.
- Installed native UI: selecting 60 fps clamped the balanced preset to 24 Mbps
  and persisted it; restoring 100 fps restored 32 Mbps. The test installation was
  then uninstalled with exit code 0; its executable and uninstall registration
  were removed, while per-user settings remained as documented.

## Hardware and distribution limits

No physical goggles were connected. Actual USB binding after elevation, optical
video output, reconnect behavior on hardware, prolonged thermal behavior and
monitor-to-lens latency have not been measured for this client. A physical test
matrix should cover Goggles 2 01.11/01.14 and Integra 01.09, start/stop cycles,
unplug/replug, wrong firmware, slow USB link, UAC denial and driver install/reboot.

Installer has no publisher code-signing certificate. Windows driver signature
enforcement remains enabled; the app never installs an unsigned replacement.
First driver setup requires internet or the exact official offline installer.
The app installer bundles no DJI driver/firmware binaries.

Windows GUI CI is provided for future PR/manual runs. Local execution is recorded
above; no remote CI run or hardware pass is implied.
