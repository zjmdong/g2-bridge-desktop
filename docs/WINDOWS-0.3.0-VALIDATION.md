# Windows 0.3.0 integration validation

This branch starts at upstream `e88bb484f6643e98ed2785698b272a3f8399f0db`.
It retains the upstream window and SDK handshake, including the 500 ms control
read timeout, G2 firmware mapping and Integra support. The optional GPU-priority
parameter retains the CLI's original default.

## Host checks

Checked on Windows with an RTX 4060 Laptop GPU and the existing owned MTT
25.7.23 virtual display. These checks did not install a driver or change system
trust settings.

- All eight 720p/1080p × 60/75/90/100 Hz virtual modes passed the real native
  capture/NVENC preflight. Each lease restored the previous active layout.
- At 1080p100, both the physical desktop and virtual desktop passed 20, 32,
  and 40 Mbps preflights: 13 checks in total including the other modes.
- Both sources resolved to the same NVIDIA DXGI adapter LUID. Virtual modes
  reported the exact requested integer refresh ratio, including 100/1.
  This establishes the capture path, not the game's render adapter identity.
- The packaged worker streamed 1080p100/40 Mbps/P4 over real USB to G2
  firmware 01.14.00.00. It stopped automatically after 16 seconds of sending
  and released the virtual display without changing the physical layout.
- After startup, the two complete five-second intervals reported 100.05 and
  100.00 fps, queue p95 0.05 ms, USB send p95 1.04 and 0.99 ms, and zero
  oversized frames. The first interval includes startup and reported 82.38 fps;
  it must not be represented as a steady-state frame rate.
- The packaged WebView smoke test exited successfully. Offline UI cases cover
  Windows, macOS, source selection, installation states, and the minimum window size.

The scene was a desktop, not a running FPV game. These are host-side startup,
capture, encoding, transport, and lifecycle checks. No optical latency,
headset display cadence, or improvement in game frame times was measured.
Five-second counters cannot establish per-frame jitter bounds. The optional
high-frequency sender instrumentation was not enabled in this build.

## Bitrate finding

The reported higher-bitrate improvement is plausible for motion quality:
100 fps at 20 Mbps budgets 25 KB per frame; 32/40 Mbps budget 40/50 KB.
The inspected recent 20 Mbps sessions also used 60 fps, while the 32/40 Mbps
sessions used 100 fps. Those sessions therefore do not isolate bitrate as the
cause of smoother motion. The integration restores the upstream automatic
24/30/32/32 Mbps recommendations rather than a fixed 20 Mbps desktop default.

## Reproduction

Offline checks: `python -m unittest discover -s tests -v` and
`node --test tests/test_app_ui.mjs`. Build instructions and exact native
inputs are in [packaging](../packaging/README.md). The native executable hashes
and corresponding source/patch are unchanged from the previously validated
capture build; this release integrates that backend into the upstream app.
