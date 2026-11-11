# Native source timing pattern

Research-only Windows D3D11 source for an existing **1920×1080 / 100 Hz** extended
display at **(3440, 0)**. It refuses a primary monitor, another rectangle or
another currently configured refresh rate. It never changes the display topology,
opens USB, sets system timer resolution, or activates its window.

Build only; does not run the executable:

    python packaging/windows/frame_age/renderer/build.py

The compiler defaults to the repository's pinned UCRT64 toolchain, falling back
to `g++` on PATH; `--compiler` can specify another compatible toolchain. The
executable is written under ignored `work/frame-age-renderer/`, never beside the
tracked source. Building does not run it. This fixture intentionally retains the
experiment's strict monitor geometry; it fails closed on a different topology.

Launch only when the coordinating agent has reserved the GPU test slot. Use a new,
absolute JSON path. Do not launch a second renderer over an existing one. When
using PowerShell Start-Process, specify -WindowStyle Hidden to hide the console.
The renderer executable takes:

    --mode texture --seconds 180 --output C:\\absolute\\unique.json

The texture mode is preferred for timing comparisons: it generates a deterministic
1024×1024 multiscale RGB texture and its mip chain once before measurement,
uploads them as an immutable resource, then uses two texture samples per pixel.
Translation and rotation advance by frame ID and repeat after exactly 200 frames
(two seconds at 100 Hz). Regions have different motion fields. The frame ID/QPC
overlay remains unique and is intentionally excluded from that image-content
repeat. No procedural noise or trigonometry runs per pixel in texture mode.

The original complex mode has deterministic, continuously moving textured ground, clouds
and panels plus a foreground block. The motion mode has a simpler grid and moving
block. The source fills only the target extended monitor. Both modes embed frame
ID and QPC timestamp as binary cells and hexadecimal digits; marker geometry is
written in the JSON. The QPC marker is sampled before that frame's render work.
There are no per-frame CPU texture uploads.

The swapchain uses flip-discard, two buffers, a frame-latency waitable object,
maximum frame latency one, and Present1(1, 0). Each frame waits for the swapchain,
not a separate 10 ms timer. This requests synchronization to the actual output;
the recorded statistics must still establish the achieved cadence.

Rows are preallocated and never written to disk in the render loop. Once the
window and graphics resources close, a new JSON file records all QPC timestamps,
Present results, last-present counts and DXGI frame statistics. An unsuccessful
statistics HRESULT is recorded explicitly; it is not interpreted as zero latency.
Present1 returning does not establish physical display time or goggles timing.

Escape, close, Ctrl+C, a display configuration change, or the specified duration
ends the renderer. A stalled frame-event wait still checks the duration deadline
at least every 200 ms. Use the duration or a normal close for useful results;
terminating the process discards its in-memory records.

The timing approach follows Microsoft's
[DXGI latency guidance](https://learn.microsoft.com/en-us/windows/uwp/gaming/reduce-latency-with-dxgi-1-3-swap-chains)
and [Present1 behavior](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_2/nf-dxgi1_2-idxgiswapchain1-present1).
