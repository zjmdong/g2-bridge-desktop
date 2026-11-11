# Windows implementation history

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

The following sections preserve earlier implementation and validation history.
They do not imply that a historical experiment is a new 0.2.4 measurement.

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
30 seconds. Remove this pacer entirely; keep encoded reference pictures ordered.

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
