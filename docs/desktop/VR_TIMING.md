# VR streaming timing: applicable mechanisms and remaining boundaries

This is a design and source review for 0.2.4, targeting **1920×1080,
100 fps, 20 Mbps, NVIDIA NVENC**. It explains why wired VR can feel stable,
which mechanisms this client can use, and which require a headset runtime that
the recovered Goggles 2 protocol does not expose. It does not establish a new
optical latency measurement or a ±1% bound.

Implementation details are in [IMPLEMENTATION.md](IMPLEMENTATION.md).
Protocol and device limits are in [PROTOCOL_LIMITS.md](PROTOCOL_LIMITS.md).
The tested host, source-identity results and actual USB-write measurements are
recorded in [VALIDATION-0.2.4.md](VALIDATION-0.2.4.md). The desktop now adopts
source-phase alignment with `source_clock=1` and `source_guard_us=3000`; the
native option remains off by default. These are source-side settings, not
measurements or controls of the headset display phase.

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
| One cadence authority | The capture clock uses QPC and a target interval, without a second encoded-output pacing queue. |
| Source-phase alignment | Qualified desktop-update timestamps steer future capture deadlines, with a 3 ms guard and corrections bounded to ±100 microseconds. Native callers must opt in. |
| Keep waiting images fresh | A single-slot raw-frame mailbox replaces an older waiting image before encoding when necessary. Already encoded reference frames retain their order. |
| Hardware completion notification | The bundled Windows NVENC path uses completion events. An API completion is not a presentation acknowledgment. |
| Avoid starving the producer | The desktop client requests GPU scheduling class 4 for its own encoder; the SDK's optional policy still defaults to class 5 for existing CLI callers. This is a best-effort request, not a guaranteed GPU time slice. |
| Fixed quality policy | The requested bitrate remains 20 Mbps for the target scenario. The receiver-compatible rate-control and frame-size safeguards remain relevant. |
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
is bounded to ±100 microseconds; there is no new encoded-frame buffer or
adaptive bitrate reduction. The comparison and its limited-host acceptance
evidence are recorded in the release validation.

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

## Measurement needed to accept a change

At 100 Hz the requested period is 10 ms. Four different observations must stay
separate:

1. **Source production:** unique frame IDs, presentation intervals and source
   renderer statistics. A renderer that itself falls below 100 fps cannot
   establish that a capture implementation lost otherwise available frames.
2. **Source age through encoding:** desktop-update QPC to capture, GPU filter
   submission, encoder submission and packet availability. CPU submission
   durations alone do not measure when GPU work actually executes.
3. **Host USB submission:** full video-message write start/end and completion
   intervals, separated from control packets. A completed host USB API call
   does not establish decode completion or lens presentation.
4. **Optical result:** source-to-lens timing and unique displayed frames, which
   require independent optical or receiver measurements. Neither a nominal
   100 fps counter nor the metrics above substitute for this.

Diagnostic probes keep bounded records in memory and write them after a run.
The comparison source presents with a DXGI frame-latency waitable object and
uses a precomputed moving texture, so expensive procedural shading does not
become an uncontrolled source of missed frames. Its own timing is retained
alongside the pipeline observations.

The acceptance question is whether a change reduces measured frame age and
long gaps without increasing backlog, breaking image integrity or hiding
repeats. A forced sleep after encoding can regularize a delivery graph while
making every displayed frame older; padding compressed frames can regularize
byte counts without improving their content. Neither is evidence of a more
responsive simulator.

Wired VR's useful lesson is to control frame ownership, queue depth, timing
phase and deadline feedback across the whole pipeline. This client can improve
the sender-controlled portions now. It must report the headset-controlled
portion as unmeasured until the necessary feedback or optical evidence exists.
