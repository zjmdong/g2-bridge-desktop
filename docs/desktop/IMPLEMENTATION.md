# Windows implementation history

## 0.2.6 bounded acquisition and source-clock delivery

The desktop explicitly enables `fresh_wait_us=2000` and
`delivery_delay_us=8000` for both primary and virtual display capture. Both new
native options default to zero, so other FFmpeg callers keep the previous
behavior unless they opt in. The target remains 1080p100/20 Mbps/P4; retain the
0.2.5 High/CABAC and symmetric chroma QP offsets, NVENC ULL/qres, no B frames or
lookahead, startup IDRs at 0/1/2 seconds, and the existing bitrate and frame-size guards.

After the scheduled DDA sample, a bounded fresh-image acquisition window can
catch a desktop update that was nearly ready. The window shares one absolute
deadline across retries and respects the next capture slot. Every retry on this
live path calls `AcquireNextFrame(0)`; the existing high-resolution timer waits
at most 250 microseconds between attempts, without a polling spin loop. One
final nonblocking attempt can accept an image already ready at the deadline.
This replaces the positive-DXGI-timeout prototype, whose actual USB runs still
showed approximately 20 ms output tails. A zero requested timeout does not
guarantee a bounded driver call or OS scheduling delay. Initial format probing
and callers with the fresh-image option disabled retain their existing policy.
Mouse-only updates do not become new image samples. Timeout fallback reuses the last valid image
with explicit texture/duplication-frame ownership. This cannot create a new
source frame when the simulator or compositor has not produced one.

Each output, including a repeated picture, carries its scheduled capture slot
and QPC clock information through frame metadata and FFmpeg `FrameData`.
NVENC's existing `COPY_OPAQUE` mapping associates that information with the
completed H.264 access unit. The mux thread waits only until **capture slot +
8 ms** before writing AVI. This budget includes the intervening capture, GPU
processing and encoding; it is not an extra 8 ms sleep after encoding. Initial
prototype measurements placed the additional host wait at roughly 3 ms median;
the release-specific results and conditions belong in
[0.2.6 validation](VALIDATION-0.2.6.md), not an optical-latency claim.

The high-resolution timer belongs to the mux thread. Its budget is validated
against one source period and a 20 ms maximum, with a bounded 100 us spin tail.
Late access units are sent immediately without moving later deadlines or
dropping encoded references. The existing single-packet queue remains; the mux
also holds the current packet while waiting. This is bounded added latency,
not zero buffering. The accumulating sender pacer removed in 0.2.2 remains
removed: no deadline is derived from a previous USB completion.

Constant-cost counters reuse the waiter's existing QPC samples. One shutdown
summary distinguishes arrival after the deadline from overshoot while waiting;
it adds no per-frame logging, allocation or USB readback. Source-frame identity,
host output cadence and these counters must be assessed separately: stable
packet output does not prove distinct source images or stable lens presentation.
The recovered protocol still supplies no headset VSync or presentation feedback.
No universal zero-drop, optical-latency or ±1% guarantee is established.

The native source patch and binaries are rebuilt for this release. CPU checks
cover 16 fresh-acquisition scenarios and a 10,000-frame delivery-deadline model,
alongside clock, source-phase and mailbox tests. The SDK protocol and audited
SDK patches remain unchanged. See the [VR timing review](VR_TIMING.md) and
[native build guide](../../packaging/windows/ffmpeg/README.md).

The selected nonblocking 60-second USB experiment measured host completion
interval P99 10.577 ms and maximum 11.2204 ms, with none above 15 ms. Its decoded
identity window still contained 111 repeats and 62 omitted source submissions;
source presentation gaps and catch-up bursts explain much of this distinction,
but sparse presentation samples leave some omissions unresolved. This is not
evidence of zero missing pictures or constant optical latency. Increasing the
stdout pipe to 64 KiB did not remove the long tails; moving the source guard to
5 ms increased source age and did not justify adoption. Both experiments were
rejected. The default pipe and 3 ms guard remain.

The final clean production binary's extended-display USB run had 5700 unique
steady-window pictures with no repeats or omitted IDs. Its separate 20-second
primary-display check retained two repeats and two omissions among 1700 outputs;
both omitted IDs were explicitly observed in DXGI presentation statistics.
Increasing fresh wait to 4 ms or the primary source guard to 5 ms still left one
repeat and one presented-but-omitted ID per run. Neither change was adopted.
The remaining primary-source loss has not been fully eliminated; it must not be
attributed entirely to missing application renders or hidden by regular AU timing.

## 0.2.5 motion coding quality

Version 0.2.5 selected H.264 High, explicitly requested CABAC entropy coding,
and set both chroma QP offsets to -4.
The environment probe, settings-to-SDK adapter, capture command and reported
profile share this policy. Baseline was retained during early compatibility
debugging; the receiver supports High, and the separate colour-description-free
VUI policy remains in place. Input is still 8-bit limited-range BT.709 NV12.

High/CABAC alone produced a six-code-value error at a red letterbox boundary,
exceeding the existing four-code-value decoded-colour tolerance. The symmetric
chroma offsets allocate finer quantization to colour components; all six geometry
checks then passed without relaxing that tolerance. This is an NVENC quantization
setting, not a change to RGB conversion, scaling or the use of hardware encoding.
It slightly redistributes the fixed coding budget from luminance to chroma
relative to the High-only candidate, so the final policy is measured separately.

Keep NVIDIA NVENC, P1/P4, ULL, qres multipass, the configured bitrate and the
existing VBV/frame-size protection. The default target remains
1080p100/20 Mbps/P4. There are still no B frames or lookahead, one reference
frame, startup IDRs at 0, 1 and 2 seconds and no periodic forced IDR or intra
refresh. Capture scheduling, the raw-frame mailbox and ordered USB output are
unchanged; this profile change adds no output pacing queue.

At the same configured 20 Mbps, the 540-frame generated GPU-input comparison
with the final High/CABAC, qres and chroma-offset policy reduced aggregate
luminance squared error versus Baseline by 46.75% for fast panning, 54.18% for
scene changes and 25.08% for fine texture. These percentages
come from aggregated pixel error, not an average of per-frame decibel scores.
Actual coded byte counts differed, so this is not a comparison at strictly equal
effective bitrate. Frame identities, reference-chain checks and the 56,000-byte
frame guard passed for these samples. They do not establish the goggles' visual
result or optical latency.

Full-resolution multipass and spatial AQ were also compared. Fullres improved
average detail but produced larger error spikes at scene changes; AQ had mixed
local results. Neither is enabled by this release. The original qres policy
keeps the measured motion-quality improvement without those tested regressions.
See [the quality evidence](evidence/v0.2.5-motion-quality.md) and
[0.2.5 validation](VALIDATION-0.2.5.md) for conditions and remaining limits.

An identical 500-frame generated input produced byte-identical H.264 access units
with the 0.2.3 and 0.2.4 native binaries. This does not support attributing the
reported quality issue to a new native encoding change in 0.2.4. It also does not
compare changing live desktop inputs. Version 0.2.5 reuses the 0.2.4 FFmpeg
binaries, source patch and dependency manifest. The two audited SDK patches
remain unchanged; the quality policy is implemented only in the desktop adapter.

The following sections preserve earlier configurations and measurements,
including the former Baseline profile. They are not new 0.2.6 acceptance results.

## 0.2.4 source-phase alignment and GPU scheduling

Retain the 1080p100/20 Mbps/P4 target and the existing capture, colour conversion,
NVENC and ordered USB path. The desktop client requests GPU scheduling class 4
(High) for its own encoder, replacing its previous class 5 (Realtime) request.
The setting applies once after the first encoded frame and is best-effort;
unsupported or rejected policy requests do not stop streaming. This change does
not establish zero drops, a constant optical latency or a universal 1% bound.

The desktop enables `ddagrab` source alignment with `source_clock=1` and
`source_guard_us=3000`. A qualified window of real DXGI desktop updates provides
a robust phase estimate; repeated, stale, mouse-only and inconsistent samples
cannot steer the clock. Each correction moves only future capture deadlines,
by at most ±100 microseconds. The 3 ms guard places the sampling phase after
the estimated desktop update; it is not an encoded-frame buffer. Substantially
late wakes discard missed timing slots instead of producing catch-up bursts.
The native option remains off by default, preserving existing native callers.
This aligns to the source, not to an unreported headset VSync.

The selected guard provides additional sampling margin over the 2 ms candidate.
The release comparisons, including source-identity and actual USB-write
observations, are documented in [0.2.4 validation](VALIDATION-0.2.4.md).
These observations cover the tested host and source; they do not guarantee
fixed optical timing or identical behavior under all GPU loads. There is no
new post-encode pacing queue or adaptive bitrate reduction.
See [VR timing design and primary sources](VR_TIMING.md).

The SDK adds optional `BridgeEngine(..., gpu_priority_class=5)` and
`prioritize_gpu(process, priority_class=5)` arguments. `None` leaves the OS
policy untouched; otherwise only integers 0 through 5 are accepted. The default
remains 5 for existing callers and the command-line client. DLL loading is
restricted to System32, invalid/closed/pseudo handles are rejected, and NTSTATUS
uses its explicit 32-bit ABI. Streaming events record `gpu_priority_class` and
`gpu_priority_applied`; `gpu_realtime` is true only for a successful class 5 request.

The original 70-file SDK baseline remains recorded without replacing its hashes:
68 files still match the original baseline. The sole runtime change is in
`goggles_bridge/engine.py`. A second patch corrects `tests/test_engine.py`:
querying a User32 desktop window does not create a D3D context, so a best-effort
GPU scheduling request may legitimately return false. That test now verifies
the boolean result and closes the child stdout; successful and rejected
policies have separate mocked coverage, with real encoder checks in validation.
`sdk-patches.json` records both original hashes, exact patched hashes and
reasons. `packaging/windows/verify_sdk.py` rejects unlisted changes,
stale patch hashes and a patch tied to a different baseline. The desktop changes
and mocked regression tests remain separate from the SDK protocol implementation.

## 0.2.3 bound raw-frame backlog and repair native capture timing

Keep all 70 SDK baseline files at `a34690a58d48f0cd9b43cdeddf39b5efaf024b9c`
unchanged. The native modifications are a patch against bundled FFmpeg n9.0.2
(`946fcce07b6dcd0331c8cc609192aeff5e1924f8`), configured as a minimal standalone
LGPL build. USB framing, the session/heartbeat protocol, DJI driver handling,
firmware policy and the SDK's encoded-frame protection remain in place.

The production DDA source now runs at the selected target fps. Its single
capture clock uses absolute QPC deadlines, a high-resolution waitable timer
and a bounded 500 microsecond busy tail; acquisition is nonblocking. Expired
deadlines are skipped after a stall. This replaces 240 Hz polling plus selection,
which could turn a 100 fps target into alternating sampling intervals. It does
not add a post-encode pacer or turn an unchanged desktop into new source images.
Primary and virtual displays use the same implementation, distinguished by
DXGI adapter/output identity and actual dimensions. Their source refresh rates,
game rendering and Windows presentation timing can still differ.

For NVIDIA-owned outputs, D3D11 textures remain on the GPU through aspect-fit
scaling and full-range SDR RGB to limited BT.709 NV12 conversion. Explicit YCbCr
background colour fixes black bars previously written at Y=0 instead of Y=16.
Only an enlarged source uses two GPU passes: first BGRA scaling, then 1:1 NV12
conversion. This avoids observed chroma contamination at the image boundaries
when NVIDIA's VideoProcessor enlarged RGB and subsampled it in one operation.
Equal-size and downscaled sources retain one pass. Foreign-vendor display
adapters retain an explicit CPU transfer/conversion path followed by NVIDIA
encoding; the desktop client has no software-encoder fallback.

Windows NVENC opts into asynchronous encoding, per-surface completion events
and system-memory bitstream output. It waits for the event before
`nvEncLockBitstream(doNotWait=0)`, following NVIDIA's DirectX threading guidance.
Input references remain owned until completion; EOS is awaited before event
unregistration and resource destruction. A failed completion wait poisons the
session. Resources that may still be in flight are retained until process exit
after failed shutdown; a timeout is not GPU cancellation. The event wait limit
does not bound arbitrary calls inside the display driver.

The opt-in `-latest_frame 1` output uses a single-slot raw AVFrame mailbox before
the encoder. A new producer frame replaces only the waiting frame's references,
under the queue lock; it cannot overwrite a texture already held by the encoder.
EOF follows the final pending frame. Compact timestamps are assigned after
admission using the number of encoded input frames, preventing AVI gap-fill
packets without fabricating images. The mode is restricted to one video encoder
and one single-stream output, with explicit rate and passthrough frame mode;
audio synchronization, `-frames`, `-shortest`, copyts and two-pass file encoding
are rejected. The SDK's qres NVENC multipass is a separate rate-control setting
and remains enabled. Overload can discard unencoded raw frames; it does not
discard encoded P-frame references or promise zero drops.

Keep the default target at 1080p100/20 Mbps/P4, ULL, Baseline, no B frames,
one reference, no lookahead, and startup IDRs at 0, 1 and 2 seconds of admitted
video. The long GOP and disabled periodic intra refresh are retained. Keep
qres and the SDK's approximately two-frame VBV formula: 400,000 bits at the
default 20 Mbps/100 fps. VBV is a rate-control model, not a fixed sender sleep;
CBR does not make every frame or short measurement window the same size.

Only the owned FFmpeg process receives ABOVE_NORMAL CPU priority and a
best-effort HighQoS policy disabling execution-speed throttling and, where
supported, timer-resolution ignoring. Unsupported flags are recorded and fall
back without hiding encoder errors. No global power plan or REALTIME CPU policy
is changed; the SDK's GPU scheduling request remains unchanged.

Remove the streaming worker's redundant 250 ms SetupAPI enumeration. The
independent GUI presence watcher remains, and an SDK USB/session failure triggers
one presence check after SDK cleanup. Confirmed removal or user cancellation
ends normally; an uncertain/connected result retains the original recovery or
error semantics. Keep constant-work send counters, the 100 ms coalesced telemetry
thread, bounded IPC and asynchronous session logging. The isolated background
benchmark did not establish telemetry or the duplicate guard as the main cause
of stutter; removal is not evidence of an end-to-end latency bound.

`packaging/windows/check_gpu_pipeline.py` replaces capture with generated frames,
retains production NVENC flags (including async), and disables the live mailbox
for offline frame-order checks. The six-geometry development run checked 48
frames per geometry: GPU and CPU reference paths each encoded and decoded 288
frames, with matching SPS/PPS and no access unit exceeding 56,000 bytes. GPU raw
and decoded sample errors, including pure-colour edges, were at most one 8-bit
code value; black bars were exact. The previous CPU-encoded baseline's worst
edge error of nine is retained as a non-gating colour diagnostic; its decoding,
frame order, headers and size guard still gate. These checks are neither a
live-cadence measurement nor optical/USB hardware acceptance.

The installer and companion source archive include complete upstream FFmpeg
source, the local patch, build recipe, pinned dependency manifest and license
texts. Build and validate native inputs according to the
[FFmpeg build guide](../../packaging/windows/ffmpeg/README.md) before running
`prepare.py`; preparation requires matching release binary hashes and source
archive identity. See [VALIDATION-0.2.3.md](VALIDATION-0.2.3.md) for final evidence
and [PROTOCOL_LIMITS.md](PROTOCOL_LIMITS.md) for the theoretical constraints and
Moonlight/Sunshine comparison. No new optical 12 ms result, universal 1% bound,
constant bitrate, or lossless wired-display equivalence is claimed.

## 0.2.2 remove accumulating latency

The previous post-encode pacer preserved timing regularity by retaining old
reference frames. Its initial 20 ms wait was not a latency bound: repeated late
writes shifted its deadline and prevented faster draining. A deterministic
100 fps model with a 25 ms stall each second reached 355 ms frame age after
30 seconds. Version 0.2.2 removed this pacer entirely while keeping encoded
reference pictures ordered. The bounded capture-slot deadline introduced in
0.2.6 does not restore its completion-relative, accumulating schedule.

The old fps filter also waited for a second input and filled timestamp gaps with
old pictures. Apply the SDK's existing select/setpts admission rule before pixel
conversion and NVENC instead. Compact PTS prevents CFR/AVI from filling gaps.
Combine DDA and the processing chain in a source filter_complex, removing lavfi
demux/wrapped-frame decoder queues upstream of selection. Both primary and
extended source differ only by display identity. Keep explicit NV12 conversion,
startup IDRs, NVIDIA P1/P4, qres, AVI framing and SDK size guards.

DesktopBridgeEngine inherits the SDK loop and overrides only diagnostic emission
plus the outside logging lifetime: control hex events are omitted, other events
append asynchronously through bounded storage with finite shutdown. FFmpeg
progress output is disabled. Live write counters stay constant-work and add no
USB request; they do not measure picture age. Startup-only DXGI GPU/LUID metadata
helps diagnose display placement without assigning CUDA indices from DXGI IDs.

No driver mode/configuration or source-refresh changes are required. The new
default is 1080p100/20 Mbps/P4. See VALIDATION-0.2.2.md for code evidence, synthetic
checks and the distinction between upstream monitor-to-lens timing and total
simulator input latency. No new optical measurement is claimed.

## 0.2.1 NVIDIA-only correction

The user rejected software encoding after observing tearing, latency and stutter
in use. Restore h264_nvenc as the only desktop encoder and environment probe;
an unavailable NVIDIA encoder blocks streaming without software fallback.
Keep P1/P4, ULL, CBR/VBV, quarter-resolution multipass and zero reorder delay;
disable lookahead and periodic intra refresh. Preserve three startup IDRs, one reference,
wall-clock DDA frame selection and sender pacing from the prior hardware trials.
Capture conversion, USB framing, virtual-display lifetime and statistics stay
unchanged. Earlier NVENC grey-block corruption is not claimed fixed by this
encoder restoration. See VALIDATION-0.2.1.md for verification and limitations.

## 0.2.0 stream lifecycle and compatibility

The application adapter selects the DXGI adapter/output by display identity,
captures without WGC's yellow border, samples at 240 Hz and converts wall-clock
timestamps to the selected frame rate before RGB-to-NV12 conversion. It encodes
with libx264 and zero lookahead: optical A/B testing found grey-block corruption
in NVENC output despite neutral decoded source pixels. Keyframes at 0, 1 and 2
seconds bootstrap the goggles; periodic forced IDRs caused visible pulses, and
omitting the bootstrap produced a black display. Transport pacing absorbs short
scheduling bursts without dropping H.264 references. This adds up to 20 ms of
initial lead; it is not a claim of sub-20 ms end-to-end latency.

USB presence uses SetupAPI in a separate worker without claiming the device.
Probing has its own controller and never toggles the main task's busy state.
Manual stop suppresses automatic restart until the next insertion. Streaming
owns the virtual desktop through a finally-protected context; normal stop,
unplug and capture failures retract it. The GUI recovers after a killed worker.
The signed driver stays installed. A configuration update adds eight modes,
using the existing ownership and elevated-install boundary.

The USB writer publishes a constant-size counter snapshot. A separate thread
samples it every 100 ms; a bounded IPC writer coalesces statistics, so a stalled
GUI cannot block video. USB duration excludes pacing and is explicitly not
capture-to-eye latency. The unmodified SDK log still reports its original
settings; application capture_source/starting events describe the adapter.

## 0.1.1 reattachment fix

On the acceptance host, legacy ChangeDisplaySettingsEx rejected a detached IDD
with status -1, even though its enumerated 1080p60 mode was supported. Detached
attachment now uses QueryDisplayConfig and SetDisplayConfig. It preserves the
exact active paths and mode bytes, adds only the unique requested virtual target,
validates before applying and never sets SDC_ALLOW_CHANGES or a global extend
topology. Original paths are retained for rollback. Physical refresh rate joins
resolution, position and primary status in post-change verification. The video
adapter, USB protocol, driver binaries and settings schema are unchanged.

See VALIDATION-0.1.1.md for regression and installed-build checks.

## 0.1.0 extension

Add a Windows encoder-command adapter through SDK injection points, with
explicit desktop RGB-to-NV12 conversion, square pixels and recurring IDRs.
Resolve primary/virtual monitor handles at capture setup. Bundle a pinned,
signed MIT VDD package with a dedicated elevated driver operation; normal
display layout and streaming stay unprivileged. Protect existing VDD settings
and unrelated display drivers. Add source/setup controls and targeted tests.
See VALIDATION-0.1.0.md for hardware evidence and remaining acceptance items.

## 0.0.1 original implementation

Baseline SDK: a34690a58d48f0cd9b43cdeddf39b5efaf024b9c.

1. Freeze the SDK and add an independent desktop application package.
2. Add persistent settings, compatibility policy, device/environment probes,
   and a cancellable subprocess adapter using the SDK's public entry points.
3. Add a Chinese native Qt interface with a fixed desktop source, verified settings,
   device details, live statistics, driver setup and offline firmware help.
4. Bundle Python, Qt, PyUSB and a pinned FFmpeg; build a per-user Windows installer.
5. Verify offline behavior, lifecycle/error paths, GUI and installer launch,
   SDK integrity and packaging. Keep hardware checks explicitly separate.

## Release policy

Initial release: 0.0.1. Features/major changes: increment minor and reset patch.
Behavior-preserving fixes/tests: increment patch. CLI versioning is independent.

## Boundaries

Preserve the original SDK baseline and review any required exception as an exact
patch in docs/desktop/sdk-patches.json; the current exceptions are the engine's
optional GPU scheduling hook and correction of an existing test's false D3D
context assumption. Protocol, scripts, tools/research and all other baseline
files remain unchanged. New desktop tests live in desktop_tests/.
Only desktop sources are exposed in this release.
The SDK defaults remain 1920x1080. The application adapter can output 720p;
its hardware acceptance evidence is tracked independently of the SDK baseline.
Third-party driver binaries are not committed or redistributed without permission.
An integrated official installer workflow replaces manual terminal setup.

## Original 0.0.1 validation record

Before development: 89 upstream tests, 87 passed, 1 failed (environment-dependent
GPU scheduling assertion), 1 macOS-only test skipped. No goggles hardware has
been exercised in this session.
