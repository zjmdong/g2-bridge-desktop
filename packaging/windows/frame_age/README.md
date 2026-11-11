# Host picture-age diagnostics

These opt-in Windows research tools distinguish a regularly delivered packet
from a freshly captured picture. They are not imported by the desktop app.
Production FFmpeg must not contain this instrumentation: release streaming has
no per-frame probe timestamps, metadata, arrays or diagnostic output.

The tools never open USB or change a display mode. Normal probes discard all
video and save numeric JSON plus the FFmpeg diagnostic log. `--verify-pattern`
temporarily retains a bounded generated-pattern sample in memory, decodes its
marker after capture stops, and saves only numeric identities. It writes no
video or screenshot files. Do not enable it while capturing private desktop
content; its purpose is the native test renderer's marker.

## Build an isolated probe

The pinned source is `vendor/ffmpeg/source/ffmpeg-upstream-n9.0.2.tar.gz`.
Use MSYS2 UCRT64, GCC 16.2.0 and ffnvcodec headers 13.0.19.0, as specified by the
FFmpeg source-build documentation. Do not compile or run other CPU/GPU tests
during a timed capture. The script only writes a separate `work/` directory.

```sh
bash packaging/windows/frame_age/native/build-probe.sh source-clock-v2
```

`native/manifest.json` preserves three independently reconstructable historical
research stages against the frozen **0.2.3** base patch:

| Stage | Purpose |
| --- | --- |
| `before-source-clock` | Provenance probe plus optional lease, VP and MMCSS experiments |
| `source-clock-v1` | First source-phase estimator; retained because its acquisition gate failed |
| `source-clock-v2` | Corrected estimator accepting DXGI evidence of missed acquisitions |

All experimental switches default off in these binaries. The combined patches
are complete deltas against `native/base-0.2.3-goggles.patch`; apply exactly one.
Source-file hashes use UTF-8 text normalized to LF. Recorded binary hashes identify
the binaries actually measured. Historical builds omitted production's file-path
remapping flags, so a different build location can change retained diagnostic
strings and the binary hash without changing the source implementation.

The separate `instrument-production-v024.patch` adds **only instrumentation** to
the final 0.2.4 source. It does not add the rejected deferred-release or video
processor experiments. The optional `production-v024` build stage uses the current
release source patch followed by this diagnostic-only delta. The historical
combined binaries were exercised; this smaller source delta is provided for
follow-up research and is not a shipped or measured release binary.

## Run a controlled comparison

Use an already active NVIDIA output at the desired refresh rate. The example
assumes adapter 0, output 1; inspect the machine's actual output inventory first.
Do not run the installed streamer simultaneously. Keep one unchanged moving
source active, alternate comparison cases, and inspect the renderer's own cadence.

```powershell
python packaging/windows/frame_age/check_frame_age.py --ffmpeg work/frame-age-rebuild-source-clock-v2/build/ffmpeg.exe --output-index 1 --seconds 30 --warmup 3 --output work/probe-baseline.json
python packaging/windows/frame_age/check_frame_age.py --ffmpeg work/frame-age-rebuild-source-clock-v2/build/ffmpeg.exe --output-index 1 --seconds 30 --warmup 3 --gpu-priority-class 4 --source-clock --source-guard-us 3000 --output work/probe-candidate.json
```

The frozen `baseline-command-v023.json` fixes 1080p, 100 fps, 20 Mbps, P4,
asynchronous NVENC, the latest raw-frame mailbox, and the original source clock.
The runner does not call the live application's command builder. Later app
defaults cannot silently turn the baseline into the candidate. It explicitly
disables source phase/deferred release when the research binary exposes them;
native capability discovery happens before the timed capture and uses no GPU.
The template content hash is recorded in every new result.

Available controls:

- `--source-clock --source-guard-us N`: source phase, explicit margin in 0–5000 µs.
  A bare `--source-clock` keeps the historical 2000 µs experiment; the selected
  application policy is 3000 µs.
- `--no-gpu-priority`: leave the child's GPU scheduling class unchanged.
- `--gpu-priority-class 2|3|4|5`: Normal / AboveNormal / High / Realtime. Native
  before/after queries and NTSTATUS values distinguish an API attempt from the
  actual applied class. The default retains the original SDK's class 5 call.
- `--mmcss`, `--defer-release`, `--vp-speed`, `--vp-rate`: historical candidates,
  available only in the combined research builds. The rejected deferred-release
  plus nonblocking acquisition combination repeated approximately half the images.
- `--fifo`, `--legacy-clock`, `--synchronous`: older-path diagnostic comparisons.

Only the newly launched encoder child's existing handle is used to set GPU
priority. These tools do not change global NVIDIA settings or another process.
Output paths must be new. Normal sampling is limited to 120 seconds to remain
within the fixed native record capacity.

## Exact generated-picture identity

The native renderer embeds 32-bit frame ID and a 64-bit render-start QPC in three
rows of 16×16 black/white cells, starting at (16, 8). With that generated source
filling the native 1920×1080 output:

```powershell
python packaging/windows/frame_age/check_frame_age.py --ffmpeg work/frame-age-rebuild-source-clock-v2/build/ffmpeg.exe --output-index 1 --seconds 5 --warmup 1 --gpu-priority-class 4 --source-clock --source-guard-us 3000 --verify-pattern --output work/probe-identity.json
```

The runner retains at most 800 access units / 48 MiB for this option and permits
at most six seconds. It waits for the encoder to stop, then explicitly uses a
single-threaded CPU H.264 decoder and extracts the 512×48 luma marker. It validates
counts, cell confidence, monotonic IDs/QPC, repeated-ID consistency and causality.
There is no live decode, readback or extra renderer work in the measured path.

All frames, including startup and graceful-stop tail, remain in validation.
`included_in_summary` applies the same warmup and requested end boundary as the
main host summary. The optional `revise_pattern_summary.py` can re-summarize older
numeric evidence into a new annotated file; it never overwrites or recaptures the
original. Earlier identity summaries that excluded only warmup are not comparable
to the bounded host window without this revision.

After the renderer exits and writes its numeric log, correlate completed runs:

```powershell
python packaging/windows/frame_age/correlate_renderer.py --renderer work/renderer.json --runs work/probe-identity.json --output work/probe-correlation.json
```

Ordinary correlation compares QPC windows and explicitly does not map picture
identities. When decoded markers exist, the tool additionally matches each exact
`(frame ID, render QPC)` tuple against the renderer's log. No optical display
measurement is implied by either operation.

## Provenance and interpretation

DDA attaches raw QPC frequency, sequence, `LastPresentTime`, capture sample,
acquisition start/end, emit time, `AccumulatedFrames` and cursor information.
Metadata survives `setpts`, GPU conversion and the latest-frame mailbox. At the
filter output it enters an additional field of FFmpeg's existing `FrameData`;
the existing `AV_CODEC_FLAG_COPY_OPAQUE` path carries it through NVENC to packets.
No foreign object replaces the `opaque_ref` that FFmpeg owns.

The encoder adds dequeue, encode-submit and packet-ready QPC. The muxer records
AVI write start/end; Python records receipt of each complete access unit using
the same raw QPC clock. The runner verifies native/AVI counts, raw chunk sizes,
increasing capture IDs, stream IDs and causal timing. The SDK normally removes
AUD NAL units, so the probe observes original chunk size inside a private parser
module before normal removal. It does not modify SDK code or its global module.

Records remain in a fixed 16,384-entry array until cleanup; there is no per-frame
native log write. Graceful `q` drains the single pipe reader and preserves the
array. A forced termination loses it and fails the measurement. Metadata
allocation and QPC reads still impose research overhead, so compare candidates
using the same probe, then validate release behavior separately without it.

Key limits:

- `LastPresentTime` timestamps the OS desktop image update, not application input,
  physical scanout, USB completion or goggles presentation. Its age on an unchanged
  desktop is not queued latency. Use a changing source and report repeats alongside
  unique-image and all-image age distributions.
- Capture may wait across a desktop update, so present can follow sample. A pipe
  reader may receive bytes before the producer's write returns; arrival need only
  follow write start. Neither condition is automatically a clock error.
- Encode-submit to packet-ready includes pending GPU work, driver scheduling and
  API work. It is not a measurement of isolated NVENC hardware execution.
- Compact media PTS are never used to infer age. A steady packet rate can still
  repeat old images. A latest-frame replacement can lower age while losing a
  source picture; report both outcomes.
- Renderer Present calls are source activity, not optical completion. Overlapping
  renderer/desktop gaps are temporal correlation, not proof of one-to-one causality.
- An observed zero-loss interval does not guarantee zero losses for all workloads.
  These measurements cannot establish the user's optical latency or ±1% target.

Primary API references: [DXGI frame information](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_2/ns-dxgi1_2-dxgi_outdupl_frame_info),
[QPC clock properties](https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps),
[GPU scheduling classes](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/d3dkmthk/ne-d3dkmthk-_d3dkmt_schedulingpriorityclass).

Run the pure CPU parser/summary tests with `python packaging/windows/frame_age/test_frame_age.py`
and `python packaging/windows/frame_age/test_pattern_identity.py`. They do not
capture, encode, create a window or open USB.
