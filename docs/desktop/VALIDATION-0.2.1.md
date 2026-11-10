# Windows 0.2.1 validation

Date: 2026-11-10. Branch: fix/windows-nvenc-v0.2.1 in the user's fork.
SDK baseline: a34690a58d48f0cd9b43cdeddf39b5efaf024b9c.

## Request and correction

After the 0.2.0 optical grey-scale checks, the user reported unacceptable tearing,
latency and stutter in actual use and explicitly required NVIDIA hardware
encoding only. Both the environment probe and actual stream now use h264_nvenc.
There is no software-encoder fallback. P1/P4 remain hardware presets; NVENC
initialization failure blocks streaming and reports the NVIDIA driver problem.
The SDK source, protocol, capture source identity, virtual display lifecycle,
sender statistics and pacing are unchanged by this correction.

Retain ULL, CBR/VBV, no B frames, zero lookahead/reorder delay, one reference frame,
and forced startup IDRs at 0/1/2 seconds. Keep periodic intra refresh disabled.
An initial single-pass candidate exceeded the 56,000-byte SDK frame limit on
real desktop captures (up to 110,315 bytes); it is not shipped. Retain the SDK's
quarter-resolution multipass rate control instead. Synthetic testsrc2 alone did
not expose that desktop failure, so actual desktop mode tests are required.
NVIDIA documents the rate-control/per-frame-work tradeoff in its
[FFmpeg guide](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/ffmpeg-with-nvidia-gpu/index.html).

## Verification

- 49 desktop tests passed, including failure without software fallback and
  preserving both hardware presets. Existing lifecycle/statistics checks pass.
- SDK verification confirmed all 70 protected files unchanged.
- The actual NVIDIA hardware environment probe succeeded on the RTX 4060 Laptop.
- All 16 real desktop captures passed: 720p/1080p, 60/75/90/100 fps, P1/P4 and
  each rate's maximum SDK bitrate (24/30/32/40 Mbps). Every stream decoded without
  errors; no frame exceeded 56,000 bytes. Each four-second stream contained the
  three startup IDRs. Total: 5,200 frames; largest frame: 53,112 bytes.
  The physical primary mode/layout was preserved across
  virtual-display attach/detach checks.
- High-motion 1080p100/40 Mbps testsrc2 checks encoded 1,200 frames per preset:
  P1 374.0 fps and max 49,158 bytes; P4 302.8 fps and max 49,678 bytes. No oversize
  frames or decoder errors. These are unconstrained encoder throughput figures,
  not live capture/presentation rates or end-to-end latency measurements.
- PyInstaller/Inno Setup built the installer. Both the distribution and installed
  worker passed the NVENC environment probe and USB presence/clean-stop checks.
- Per-user upgrade exited 0; file version is 0.2.1. Installer preserved the user
  settings byte-for-byte. All installed distribution files match build hashes.
- The installed application automatically started with the user's retained
  1080p/60 fps/24 Mbps/P4 configuration. The actual FFmpeg process was verified
  to use h264_nvenc, ULL, CBR, qres, no B frames and zero lookahead. After more
  than 115 seconds, stable five-second USB windows measured 60.00–60.01 fps,
  with no oversized frames in those windows.
- The user explicitly confirmed improved smoothness and no observed colour
  cast with the installed 0.2.1 build. This is optical acceptance of the current
  configuration, not a claim of perfect motion or colour under every mode/load.

Installer: `DJI-Goggles-Streamer-0.2.1-Setup.exe`, 61,805,102 bytes.
SHA-256: `2704576e4bf181730f3cb3cd097e10c76aee09f6fbdcc17042ddb401d7289496`.

## Limits

Changing the encoder does not establish that every reported motion problem was
caused solely by software encoding. Host load, source refresh rate, USB pacing
and goggles presentation timing remain relevant. Previous NVENC optical tests
showed uneven grey patches; the current accepted run does not rule out every
firmware/content-specific colour issue.
Local decoder checks cannot establish the final image seen inside the goggles.
Only NVIDIA encoding is allowed regardless of those earlier colour findings.
Desktop capture/colour conversion still performs CPU work; hardware encoding
does not mean the entire capture pipeline is GPU-only. End-to-end latency is
not measured by the SDK. USB timing in the UI remains write duration only.
