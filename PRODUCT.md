# Product

<!-- impeccable:product-schema 1 -->

## Platform

Windows native desktop (PySide6). macOS is deferred by the user.

## Stack

Delegated by the user: Python/PySide6 desktop application around the existing,
unchanged g2-bridge SDK. A child process owns streaming and USB. Native Qt
controls provide keyboard navigation, DPI scaling and Windows integration.

## Users

DJI Goggles 2 owners using their computer desktop, especially FPV simulators,
who want to connect and stream without a terminal.

## Product Purpose

DJI Goggles Streamer prepares the PC, checks the goggles, configures streaming,
and starts/stops desktop video over USB. The initial Windows installer is 0.0.1.

## Capabilities and Constraints

- Existing SDK files, CLI, protocol and encoder defaults remain unchanged.
- Version 0.0.1 has only the computer desktop as a source. Version 0.1.0 adds an
  experimental independent 1080p/60 Hz Windows virtual extended desktop, using
  an optional signed driver and the unchanged SDK video transport.
- The second display means an independent extended desktop, allowing a
  simulator to appear in the goggles while the primary monitor remains usable.
- The SDK's verified stream is 1920x1080; unsupported modes must never be
  presented as verified capabilities.
- Version 0.2.0 adds two resolutions (720p/1080p), four virtual refresh rates
  (60/75/90/100 Hz), automatic USB and display lifecycle, borderless DXGI capture,
  and asynchronous sender statistics. Firmware optical results are recorded
  separately from local mode/decoder checks.
- Version 0.2.1 uses NVIDIA NVENC exclusively, per the user's requirement after
  software encoding caused unsatisfactory motion and latency. Do not introduce
  software fallback. Earlier NVENC optical grey-block issues remain a distinct
  compatibility concern; report evidence without claiming an unverified fix.
  SDK encoder defaults and USB framing remain unchanged.
- Version 0.2.2 prioritizes picture age: raw-frame admission before encoding,
  immediate ordered USB writes, no stale-frame catch-up or post-encode pacing,
  no synchronous diagnostic disk writes in the sender. Both display sources
  share this pipeline. Default target is 1080p100/20 Mbps/P4. Never claim source
  refresh/display timing is identical or 12 ms optical latency without evidence.
- USB driver installation can need Windows elevation. Firmware updates remain
  in DJI's official software, with integrated instructions and rechecking.
- New features increment the minor version; fixes/tests increment the patch.
- No hardware result, signing identity or compatibility claim may be invented.

## Brand Commitments

Name: DJI Goggles Streamer. Independent GPL-3.0-only project; not an official DJI
application. Chinese UI initially, English source and contribution materials.

## Product Principles

- Make the next useful action obvious from actual device state.
- Keep the video path independent of UI rendering.
- Explain failures with a recovery action and preserve diagnostic evidence.
- Keep upstream contribution small and additive.

## Assumptions

The user explicitly delegated implementation and requested no manual
intervention. A restrained, light desktop utility, Chinese-first copy and native
controls are implementation choices, not user-approved visual preferences.
