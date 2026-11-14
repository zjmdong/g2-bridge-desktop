# VR streaming timing: applicable mechanisms and remaining boundaries

This is a design and source review for 0.2.6, targeting **1920×1080,
100 fps, 20 Mbps, NVIDIA NVENC**. It explains why wired VR can feel stable,
which mechanisms this client can use, and which require a headset runtime that
the recovered Goggles 2 protocol does not expose. It does not establish a new
optical latency measurement or a ±1% bound.

Implementation details are in [IMPLEMENTATION.md](IMPLEMENTATION.md).
Protocol and device limits are in [PROTOCOL_LIMITS.md](PROTOCOL_LIMITS.md).
The tested host, source-identity results and actual USB-write measurements are
recorded in [VALIDATION-0.2.6.md](VALIDATION-0.2.6.md). The desktop retains
source-phase alignment with `source_clock=1` and `source_guard_us=3000`, and
explicitly enables `fresh_wait_us=2000` and `delivery_delay_us=8000`.
Source alignment and both new controls remain off by default for native callers.
These settings control the host pipeline, not the headset display phase.

## A cable is only one part of the display path

| Path | Image transport | Timing ownership |
| --- | --- | --- |
| A DisplayPort PC headset | A display video signal | GPU display output and headset display path |
| Meta Quest Link over USB | Encoded video through a USB transport | PC runtime plus Quest decoder and compositor, with feedback |
| Goggles 2 Virtual Flight USB | H.264 in recovered DUML PC V1 video messages | PC controls capture, encode and submission; headset decode/display timing remains opaque |

For example, Valve Index specifies DisplayPort for its display connection and
USB for other functions. That is a different image path from compressed USB
streaming; the presence of a USB cable alone does not identify the path.
[Valve Index connection requirements](https://help.steampowered.com/en/faqs/view/105E-66E3-962A-1577)

The following Meta example is specifically the documented **USB Link**
architecture, not an inference from Air Link or Wi-Fi behavior. Likewise,
DJI aircraft radio latency and bitrate specifications do not describe this
Virtual Flight USB path. WiVRn and ALVR provide useful runtime and queue
designs; citing their pacing code does not imply that every transport they
support behaves like this USB endpoint.

## What the VR runtime adds

Meta's Link architecture describes more than moving encoded bytes. The PC
encodes and transmits slices; the headset decodes and submits images to its
compositor. Feedback includes headset VSync timing, and prediction uses timing
observations to place the work before the intended display opportunity. Its
compositor can apply asynchronous timewarp close to presentation. These
capabilities depend on software at both ends.
[Meta: Link architecture, pipeline and AADT](https://developers.meta.com/vr/blog/how-does-oculus-link-work-the-architecture-pipeline-and-aadt-explained/)

Meta's frame lifecycle description also distinguishes application rendering
from compositor rendering. The compositor consumes completed images, uses
synchronization between GPU work, and can reuse and reproject an earlier
application image when a new one misses its deadline.
[Meta: A VR Frame's Life](https://developers.meta.com/vr/blog/a-vr-frames-life/)
Consequently, a stable headset refresh does not itself prove that every refresh
contains a newly rendered application frame. Reprojection can reduce visible
head-motion error; it does not make old simulator state newly computed. That
last distinction is a consequence of reusing an older application image.

OpenXR exposes this separation explicitly. `xrWaitFrame` lets the runtime pace
an application and returns a predicted display time and period; `xrEndFrame`
submits layers for a display time. This is a contract with a runtime that owns
the compositor, not a timer an arbitrary video sender can call to synchronize
an unrelated headset.
[OpenXR 1.1 frame-loop specification](https://registry.khronos.org/OpenXR/specs/1.1/html/xrspec.html#xrWaitFrame)
Monado's pacing model similarly tracks the path from application wake-up,
through GPU and compositor work, to display and scanout.
[Monado frame pacing](https://monado.pages.freedesktop.org/monado/frame-pacing.html)

## Concrete open-source mechanisms

WiVRn's compositor pacer converts headset feedback into a common clock domain
and uses decode, blit and display observations to estimate a safe deadline
budget. At the revision below, its budget uses a high percentile of recent
timings plus a margin; its display-phase correction is gradual rather than
following each noisy sample directly. These are useful examples of separating
frequency, phase and deadline slack. They require receiver feedback that the
Goggles 2 PC protocol currently lacks.
[WiVRn pacer at 869b0ce660b439d7065f60a50c6df8823b5606b3](https://github.com/WiVRn/WiVRn/blob/869b0ce660b439d7065f60a50c6df8823b5606b3/server/compositor/pacer.cpp)

ALVR separates constant and adaptive bitrate policy. Its adaptive path responds
to measured bottlenecks; its constant path preserves the configured target.
That supports keeping the requested 20 Mbps fixed here instead of lowering it
in response to a sender scheduling gap. A constant target still does not imply
identical encoded byte counts per frame.
[ALVR bitrate manager at 2945d90e6285c4794a7ce89b07d85ca8e5d52185](https://github.com/alvr-org/ALVR/blob/2945d90e6285c4794a7ce89b07d85ca8e5d52185/alvr/server_core/src/bitrate.rs)

ALVR also bounds its decoded-image queue and can discard old decoded images.
Its client statistics accept VSync queue timing from the runtime rather than
pretending to infer it solely from packet arrival.
[ALVR decoder queue](https://github.com/alvr-org/ALVR/blob/2945d90e6285c4794a7ce89b07d85ca8e5d52185/alvr/client_core/src/video_decoder/android.rs),
[ALVR client timing](https://github.com/alvr-org/ALVR/blob/2945d90e6285c4794a7ce89b07d85ca8e5d52185/alvr/client_core/src/statistics.rs)
Dropping a decoded image is different from dropping a compressed H.264
reference frame before it reaches the decoder. The latter can invalidate
subsequent dependent frames and is not adopted as a sender pacing strategy.

ALVR's Windows NVENC implementation also provides a useful comparison for
avoiding additional output delay and controlling VBV. Its exact encoder
settings cannot be copied without checking this receiver's compatibility and
frame-size limits.
[ALVR Windows NVENC implementation](https://github.com/alvr-org/ALVR/blob/2945d90e6285c4794a7ce89b07d85ca8e5d52185/alvr/server_openvr/cpp/platform/win32/VideoEncoderNVENC.cpp)
NVIDIA documents asynchronous completion events and separate input/output
threading. These can prevent unnecessary CPU blocking; they do not remove GPU
dependencies or guarantee that adding more in-flight frames reduces latency.
[NVIDIA Video Codec SDK 13.0 threading model](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-video-encoder-api-prog-guide/#threading-model)

## Application to this client

| Mechanism | Current use or boundary |
| --- | --- |
| One cadence authority | The QPC capture schedule supplies both sampling slots and absolute mux delivery deadlines; no schedule is based on a previous packet's completion. |
| Source-phase alignment | Qualified desktop-update timestamps steer future capture deadlines, with a 3 ms guard and corrections bounded to ±100 microseconds. Native callers must opt in. |
| Bounded fresh acquisition | Nonblocking `AcquireNextFrame(0)` attempts, separated by timer waits of at most 250 microseconds, share a 2 ms budget; they cannot replace a missing source render. |
| Bounded delivery timing | The mux waits until capture slot + 8 ms when an access unit is ready early. Late units go immediately, without moving future deadlines or dropping references. The existing one-packet queue and current held packet still exist. |
| Keep waiting images fresh | A single-slot raw-frame mailbox replaces an older waiting image before encoding when necessary. Already encoded reference frames retain their order. |
| Hardware completion notification | The bundled Windows NVENC path uses completion events. An API completion is not a presentation acknowledgment. |
| Avoid starving the producer | The desktop client requests GPU scheduling class 4 for its own encoder; the SDK's optional policy still defaults to class 5 for existing CLI callers. This is a best-effort request, not a guaranteed GPU time slice. |
| Fixed quality policy | The target remains 20 Mbps, with 0.2.5 High/CABAC and chroma QP offsets of -4. NVENC ULL/qres, no B frames or lookahead, and receiver-compatible frame-size safeguards remain in place. |
| Source freshness measurement | Native probes compare real desktop-update timestamps with capture, encode and output stages; source frame IDs distinguish new images from repeated captures. |
| Headset display feedback | Not available in the recovered PC video path. There is no measured eye-display phase for the sender to lock to. |
| Timewarp or spacewarp | Not available to this PC client. Implementing it would require suitable headset rendering, pose and presentation integration. |

The GPU policy hook is the only runtime SDK change. The original 70-file
baseline remains recorded: 68 files match their original hashes, while
`goggles_bridge/engine.py` and `tests/test_engine.py` must match exact audited
patch hashes. The test patch corrects the assumption that a User32 desktop
window query creates a D3D context and therefore guarantees that a best-effort
GPU request succeeds. Separate mocked and real-encoder checks cover policy
application. Neither patch alters DUML video framing or adds receiver timing
commands.
[Patch manifest](sdk-patches.json),
[SDK validator](../../packaging/windows/verify_sdk.py)

### Adopted source-phase alignment

A fixed 100 Hz capture timer and a fixed 100 Hz desktop producer can still have
different phases. Sampling just before an update can repeat an older image;
small drift can then move that sampling point across the update boundary.
Matching the average rate alone does not solve this.

The implementation uses DXGI `LastPresentTime` to estimate the phase of consistent
desktop updates, qualifies the source cadence, rejects invalid and mouse-only
samples, and slews only future capture deadlines by bounded amounts. It avoids
turning isolated desktop timestamp jitter into a new capture interval. A
substantially late wake discards missed timing slots rather than replaying them
as a burst. The desktop uses a 3 ms guard after the estimated source update,
adding sampling margin over the 2 ms candidate. Each future-deadline correction
is bounded to ±100 microseconds. This phase estimator itself adds no encoded
queue or adaptive bitrate reduction. The separate 0.2.6 delivery wait is
described below; historical source-phase evidence remains in
[0.2.4 validation](VALIDATION-0.2.4.md).

Microsoft defines `LastPresentTime` as the QPC time of the last desktop-image
update; a mouse-only update does not provide a new desktop-present timestamp.
It is neither the future presentation time of the source application nor the
Goggles 2 display time.
[DXGI output-duplication frame information](https://learn.microsoft.com/windows/win32/api/dxgi1_2/ns-dxgi1_2-dxgi_outdupl_frame_info)

This implementation borrows the idea of conservative phase correction, not WiVRn's
receiver feedback loop. A 60 Hz desktop, a stalled simulator or variable-rate
source must not be mistaken for 100 distinct source images per second.
Primary and virtual outputs share capture and encode logic; their actual
application, compositor and scanout timing can still differ.

### Bounded acquisition and delivery

The fresh-image window shares one absolute deadline across acquisition retries.
It releases mouse-only duplication leases correctly, and either obtains the
new image or falls back to the last valid texture. Its budget is bounded by
`fresh_wait_us` and the next scheduled slot. Every live retry requests zero
DXGI timeout. The existing timer sleeps for at most 250 microseconds before
checking again, including one last nonblocking attempt at the shared deadline.
This avoids the positive-timeout DXGI path in the earlier candidate; that
candidate still had approximately 20 ms delivery tails in actual USB runs.
Windows can wake a timer late and a driver call can take longer than its requested
timeout, so the shared budget is not a hard real-time guarantee. The 16 CPU mock
cases check policy and ownership, not real driver execution latency.

Capture and encoder completion are different events. Even with regular capture,
varying GPU/encoder execution time can produce uneven access-unit delivery.
Version 0.2.6 carries the original capture-slot deadline through metadata,
`FrameData`, and NVENC's existing `COPY_OPAQUE` association. The mux waits until
that slot plus 8 ms, after bitstream filtering and before writing AVI.
The slot is neither the desktop's `LastPresentTime` nor compact encoder PTS;
every output, including a repeated picture, receives its own slot metadata.

The 8 ms includes work already spent capturing and encoding. Only the remaining
budget is waited; it is not an additional 8 ms after encoder completion. This
trades some host latency for less delivery jitter. The actual added wait and
its test conditions are recorded in [0.2.6 validation](VALIDATION-0.2.6.md).
It cannot be interpreted as a source-to-lens or input-to-lens measurement.

A mux-owned high-resolution timer handles this wait, with no system timer-policy
change and at most a 100 us busy tail. Validation limits the budget to one
source period and 20 ms. The existing one-packet queue is unchanged, and the
mux retains the current packet while waiting. A late packet is sent immediately;
the next frame keeps its own source-derived deadline. This preserves the
reference chain and avoids the accumulating completion-relative pacer removed
in 0.2.2. After a sufficiently long stall, these rules can still produce late
or closely spaced outputs; they cannot guarantee constant optical intervals.

One constant-cost shutdown summary separates arrivals already past their
deadline from overshoot incurred during a completed wait. It reuses QPC reads
already needed by the waiter and adds no per-frame log or USB request. Arrival
lateness includes upstream processing and mux scheduling, not just NVENC;
downstream Python/USB timing is a separate measurement. None of these counters
provides the receiver feedback used by a VR runtime.

## Measurement needed to accept a change

At 100 Hz the requested period is 10 ms. Five different observations must stay
separate:

1. **Source production:** unique frame IDs, presentation intervals and source
   renderer statistics. A renderer that itself falls below 100 fps cannot
   establish that a capture implementation lost otherwise available frames.
2. **Source age through encoding:** desktop-update QPC to capture, GPU filter
   submission, encoder submission and packet availability. CPU submission
   durations alone do not measure when GPU work actually executes.
3. **Native delivery:** arrivals past the source-derived deadline, time spent
   waiting and wait overshoot. These distinguish native scheduling from
   downstream pipe-reader or USB timing; they are not lens timestamps.
4. **Host USB submission:** full video-message write start/end and completion
   intervals, separated from control packets. A completed host USB API call
   does not establish decode completion or lens presentation.
5. **Optical result:** source-to-lens timing and unique displayed frames, which
   require independent optical or receiver measurements. Neither a nominal
   100 fps counter nor the metrics above substitute for this.

Diagnostic probes keep bounded records in memory and write them after a run.
The comparison source presents with a DXGI frame-latency waitable object and
uses a precomputed moving texture, so expensive procedural shading does not
become an uncontrolled source of missed frames. Its own timing is retained
alongside the pipeline observations.

The selected nonblocking 60-second USB experiment illustrates why both timing
and picture identity matter. Host completion interval P99/maximum were
10.577/11.2204 ms, with none above 15 ms; nevertheless its 5700-picture identity
window contained 111 repeats and 62 omitted source submissions. The source
itself had 111 excess nominal slots in its long gaps and 62 submillisecond
catch-up submissions. None of the omitted IDs was explicitly observed by sampled
DXGI presentation statistics, but 35 remain compatible with an unsampled
presentation. The counts are strongly associated with source timing; they do
not prove that all omissions occurred before capture. No inference of zero
drops or stable optical latency is justified. See the versioned validation for
final production-binary checks and superseded candidates.

Expanding the stdout pipe to 64 KiB did not eliminate the observed tails.
Increasing the source guard from 3 to 5 ms increased source age and did not
justify a change. Neither experiment is enabled in the product.

The final production extended-display USB window subsequently contained 5700
distinct pictures without repeats or omissions. Its primary-display check still
had two repeated and two omitted IDs among 1700 outputs, with both omitted IDs
explicitly observed by DXGI presentation statistics. A 4 ms fresh-image budget
and a separate 5 ms primary source guard each still left one such omission.
The released 2/3/8 ms policy therefore improves measured sender cadence without
claiming to have eliminated all presented-source loss. Presentation sampling and
regular delivery alone cannot resolve every capture/admission-stage omission.

The acceptance question is whether a change reduces measured frame age and
long gaps without increasing backlog, breaking image integrity or hiding
repeats. The bounded source-derived wait must be evaluated together with its
added frame age; regular output alone is insufficient. Padding compressed
frames can regularize byte counts without improving their content. Neither
a smoother delivery graph nor uniform byte counts alone establishes a more
responsive simulator.

Wired VR's useful lesson is to control frame ownership, queue depth, timing
phase and deadline feedback across the whole pipeline. This client can improve
the sender-controlled portions now. It must report the headset-controlled
portion as unmeasured until the necessary feedback or optical evidence exists.
