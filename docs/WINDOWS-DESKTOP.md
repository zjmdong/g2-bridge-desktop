# Windows desktop integration

Version 0.3.0 integrates the fork's Windows stream backend into the upstream
Goggles Bridge window. The previous Qt window is not included. The CLI and
macOS capture paths retain their upstream defaults and protocol behavior.
Upstream's monitor-to-lens latency results are not a measurement of this fork.

## Source and lifecycle

Choose **Display** to capture a connected screen, or **Separate display** for
an independent SDR desktop. Both support 720p/1080p and 60/75/90/100 fps.
Separate display setup installs the pinned signed MTT driver with normal UAC;
it never changes certificate trust or enables test signing. The app recognizes
the driver previously installed by DJI Goggles Streamer. It leaves other apps'
VDD installations alone.

Starting a virtual stream creates the selected mode; stopping, unplugging USB,
capture failure, and quitting release the owned screen. A session-local named
Windows mutex prevents two stream workers from managing it at once. The main display
and existing layout are preserved. Automatic USB start is optional. Manual
Stop inhibits restarting until the cable is reconnected. Presence detection
runs even when the window is hidden; the goggles must still be in Virtual Flight.

Existing Goggles Bridge preferences take precedence. When none exist, settings
are imported once from DJI Goggles Streamer without deleting the old file.
Windows source settings are separate from the SDK settings. Capture uses a
stable display device name and resolves its current DXGI adapter/output at start.

## Bitrate follows frame rate

| Frame rate | Automatic Windows bitrate | Maximum accepted bitrate |
| --- | --- | --- |
| 60 fps | 24 Mbps | 24 Mbps |
| 75 fps | 30 Mbps | 30 Mbps |
| 90 fps | 32 Mbps | 32 Mbps |
| 100 fps | 32 Mbps | 40 Mbps |

At 100 fps, 20/32/40 Mbps provide average budgets of 25/40/50 KB per frame.
At 60 fps, 20 Mbps provides 41.7 KB. Therefore 32 Mbps at 100 fps is a much
closer motion-quality comparison to 20 Mbps at 60 fps. High-motion simulations
can benefit from 40 Mbps at 100 fps. These are coding budgets, not measured
frame times: insufficient bitrate causes quantization/blur, not necessarily
dropped frames. The SDK's 56 KB frame ceiling and 50 KB average-frame budget
remain enforced. Larger VBV buffers or filler packets are not used to make
graphs look constant at the expense of delay or the frame ceiling.

## Performance path

The Windows worker runs independently of the WebView process. It uses native
DDA source timing, GPU NV12 conversion, asynchronous NVENC, a single latest raw
frame slot, and capture-clock delivery deadlines. Encoded reference frames are
not discarded. NVENC remains the only encoder. On NVIDIA-owned outputs there
is no CPU image readback. Capture on a different GPU vendor requires explicit
readback/upload; diagnostics identify that path. Neither a matching vendor nor
a DXGI source proves which GPU rendered the game.

Capture and encoding share the same adapter selection and preflight command.
GPU priority is High, rather than Realtime, to avoid starving game rendering.
The CLI retains its existing priority default. Colour conversion is SDR BT.709;
the tested goggles-compatible SPS, High/CABAC policy, and startup-only IDRs are
retained. Log and UI event writers have bounded asynchronous queues, and the
optional high-frequency sender telemetry is disabled in this integration.

**Copy diagnostics** records the capture adapter/LUID, effective mode and
whether image processing stays on the GPU. It does not claim optical latency,
game render GPU identity, or receiver display timestamps. See the
[Sunshine/Moonlight display-path study](windows-display-path.md) for the
shared-texture driver approach and its limitations.

Windows scheduling, application rendering and the closed goggles receiver
prevent a defensible zero-jitter or no-dropped-frame guarantee. Source-code
inspection and sender timings cannot establish monitor-to-lens latency.

## Build and checks

Follow [packaging instructions](../packaging/README.md). Run
`python -m unittest discover -s tests -v` for protocol, backend lifecycle,
display ownership/rollback, native-command and scheduling regressions.
`node --test tests/test_app_ui.mjs` runs the offline interface scenarios on a
machine with Microsoft Edge. No headset interaction is needed by these tests.
