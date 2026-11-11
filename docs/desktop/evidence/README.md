# Sender evidence

## 0.2.4

- [Host timing findings](v0.2.4-host-research.md) explains source freshness,
  controlled comparisons, selected changes and the limits of the measurements.
- [Host research summaries](v0.2.4-host-research.json) preserves 38 completed
  generated-motion cases, including rejected candidates and source correlation.
- [Release validation](v0.2.4-release-validation.json) records the uninstrumented
  binary hashes, generated pixel/codec checks and actual USB timing for the
  extended and primary displays.
- [Reproduction tools](../../../packaging/windows/frame_age/README.md) include
  frozen baseline commands, historical native patches, a generated-pattern
  renderer and opt-in provenance/identity diagnostics. They are not shipped in
  the app's streaming path.

## 0.2.3

These artifacts contain numeric measurements, commands and source changes only.
They contain no desktop pictures, headset recordings, USB payload captures or
user-specific paths. Measurements do not establish optical latency.

`v0.2.3-release-checks.json` records the final release binary's generated pixel
checks, 16 codec mode checks, real-desktop codec check, and 20-second latest/FIFO
host timing samples. Both timing samples explicitly fail the strict 1% targets.
The FIFO comparison does not establish frame age; an interval statistic alone
cannot show whether a queued picture is current.

`v0.2.3-nvenc-phases.json` preserves the QPC phase summaries and slow-frame
records from the final attribution experiments. Profile durations are in
microseconds; output-interval summaries are in milliseconds. The source was a
60 Hz virtual desktop, so a 100 fps output is not 100 distinct source pictures.

`nvenc-phase-timing.patch` is **research instrumentation, not part of the release
FFmpeg patch**. It applies after the release patch to a separate FFmpeg n9.0.2
source tree. It adds opt-in `-phase_timing 1`; samples use a fixed-capacity memory
buffer and are printed only when the encoder closes. The JSON includes the
exact encoder argument lists, with the executable replaced by a placeholder.
When reproducing, consume and discard stdout AVI bytes while draining stderr;
do not send the experimental BGRA/readback variants to goggles. Use the pinned
build configuration/toolchain in `packaging/windows/ffmpeg/` and keep this
research build separate from release binaries and their manifest.

The release build was made from a fresh source archive plus the production
patch. It contains no `phase_timing` option or timing arrays. In particular, the
additional probe clocks and storage do not run while using the installed app.

The event-wait phase includes outstanding GPU dependencies, driver scheduling,
encoding and thread wakeup. It is not a measurement of NVENC hardware execution
alone. Readback can move a wait before the instrumented region without reducing
total frame age. Refer to `../VALIDATION-0.2.3.md` for interpretation and limits.
