# Windows 0.2.2 latency correction

Branch: `fix/windows-low-latency-v0.2.2` in the user fork.
SDK baseline: `a34690a58d48f0cd9b43cdeddf39b5efaf024b9c`.
Requested target: 1920x1080, 100 fps, 20 Mbps, NVIDIA hardware encoding only.
The user requested source-based analysis rather than repeated goggles trials.

## Root causes and changes

1. **Sending completed frames through a second rate limiter retained old video.**
   In 0.2.1, `VerifiedTransport.write` called `FramePacer.wait` before every video
   write. The first frame waited 20 ms. Late deadlines were moved forward, while
   subsequent packets still could not drain faster than the target rate. The SDK
   single-slot queue could only move the backlog into the reader/pipe/encoder;
   it could not make those reference pictures current again. Delete the pacer.
   Encoded pictures are now written immediately and in order, never arbitrarily
   discarded. In a deterministic 100 fps model with a 25 ms stall every second
   and a 1 ms USB write, the old sender reaches 355 ms picture age at 30 seconds;
   the immediate sender recovers from each 25 ms stall in four frames. These are
   model results, not a measurement of the user's goggles or actual USB service.

2. **The fps filter looked ahead and filled capture gaps with stale pictures.**
   FFmpeg's `vf_fps.c` buffers two frames before output. With a 20/200 ms input
   timestamp gap, an in-memory ID test reproduces 2/20 repeated old pictures.
   Use the original SDK select/setpts rule before conversion/encoding instead:
   accept eligible raw frames immediately, compact PTS, and do not fill missing
   capture time with old pictures. A source slower than the target remains slow.

3. **The lavfi input added queues before selection.**
   `-f lavfi -i ddagrab=... -vf ...` goes through FFmpeg's demuxer/wrapped-frame
   decoder scheduler before reaching the selector. The n9.0.2 scheduler defines
   default packet queues of eight and frame queues of two; the old output-side
   `-thread_queue_size 1` did not limit all these upstream stages. Use a direct
   source `-filter_complex ddagrab=...,select...,setpts...,conversion[desktop]`
   and map that output. This removes the lavfi input/decoder queues, not every
   remaining FFmpeg or NVENC queue. Device identity, colour conversion, NVENC
   compatibility flags, AVI framing and USB protocol remain unchanged.

4. **Synchronous diagnostics could delay the session thread.**
   SDK `EventLog` wrote/flushed control events on that thread. Filtering the UI
   callback happened after disk writes. A desktop `BridgeEngine` subclass keeps
   the original run/session/recovery and clock, omits control hex events and
   appends other events via bounded asynchronous logging. Slow storage can lose
   diagnostic history, but cannot back-pressure video. Shutdown waits at most
   two seconds for that writer after SDK device/encoder cleanup. FFmpeg uses
   `-nostats -loglevel warning`, avoiding periodic progress writes. Application
   `starting` records carry actual adapter flags, rather than unchanged SDK defaults.

## Source parity and remaining boundaries

Both primary and extended desktops use the same direct DDA graph, raw-frame
selection, NVENC settings and immediate transport. Only display identity and
the image's native geometry differ. Virtual display attach/detach happens
outside the video loop. VDD 25.7.23 waits on a frame-ready event when AcquireBuffer
returns E_PENDING; its 16 ms timeout is not a mandatory per-frame sleep. Its
default GPU choice uses the largest dedicated video memory. Read-only DXGI
enumeration on this host identified the primary output on the RTX 4060 Laptop;
the inactive virtual output was not reattached for a test. GPU name/LUID is now
recorded once at stream setup; DXGI indices are not passed as CUDA/NVENC indices.
No virtual-driver changes, elevation or display-mode trials were needed.

The host primary is 3440x1440/60 Hz, while the virtual display can run at 100 Hz.
The source/game/DWM timing therefore cannot be guaranteed identical by application
code. Neither can a 60 Hz source supply 100 distinct pictures per second. Colour
conversion still uses CPU work; an unverified GPU filter replacement was avoided.
The signed driver, yellow-border-free capture and NVIDIA-only requirement remain.

The upstream **12.1 ms** is median **monitor-to-lens added delay**, measured with a
native D3D11 prototype, 01.11 firmware, RTX 5060 Laptop, 240 Hz reference monitor,
1080p100/20 Mbps High/P4, without added GPU load. The same upstream notes report
13.3 ms for a Windows desktop CLI measurement. These are not simulator-input-to-eye
latency and not a guarantee for this 01.14 machine. This correction has no new
optical measurement and does not claim that the 12 ms target has been demonstrated.

Live telemetry stays constant-work: counter publication and USB write timing,
sampled separately; no extra device request, disk access or per-frame IPC occurs
there. It excludes image age/capture/encoding/goggles presentation and must not
be used as proof of total latency. Retaining it does not restore a pacing wait.

## Verification

- 59 desktop tests pass, including immediate ordered writes across repeated
  stalls, identical primary/virtual selection, source identity/reordering,
  blocked disk/IPC, lifecycle cleanup and NVIDIA-only failures.
- All 70 protected SDK files match the original baseline.
- `packaging/windows/check_latency.py` runs actual FFmpeg on in-memory frame IDs,
  with no screen/USB access: four target rates; equal/slightly slower/slightly
  faster/240/30 fps sources; 0/20/200 ms timestamp gaps; +/-500 microsecond jitter.
  All 180 cases passed with no duplicate old IDs. The two old-fps controls
  reproduced exactly 2/20 stale duplicates after the respective 20/200 ms gaps.
- The synthetic NVENC direct-graph check produced 400 frames at 1080p100/20 Mbps
  P4, with exactly the three startup IDRs [0,100,200], a largest frame of 43,445
  bytes, and no decoder error. The direct graph and lavfi comparison produced
  identical 400-frame pixel hashes before encoding. It exercises encoder and
  AVI output, not real DDA capture, USB or goggles display.
- PyInstaller/Inno Setup built Windows 0.2.2; frozen and installed workers passed
  the NVIDIA environment encode and read-only PnP presence/clean-stop checks.
  The per-user upgrade exited 0, reports executable version 0.2.2, and all
  installed distribution files match build hashes. Installer preserved settings
  byte-for-byte. Afterwards only the requested target parameters were applied:
  this host already had 1080p/100/P4, so bitrate changed from 24 to 20 Mbps.
- No actual desktop capture, virtual mode change, USB video stream, or optical
  trial was performed for this correction. The previous idle GUI was closed for
  upgrade and left closed; launching it is left to the user. The synthetic
  frame/GPU checks above do not establish real DDA throughput or 12 ms latency.

Installer: `DJI-Goggles-Streamer-0.2.2-Setup.exe`, 61,805,978 bytes.
SHA-256: `ae23301896f0bb602f26ad31e0ece3fa8c4b5cd8be86ebd2df0a4f1e4edb6249`.

## Source references

- [Upstream optical methodology](../LATENCY.md) and
  [capture/CLI experiments](../research/EXPERIMENTS.md).
- FFmpeg n9.0.2 [fps filter](https://github.com/FFmpeg/FFmpeg/blob/n9.0.2/libavfilter/vf_fps.c),
  [DDA source](https://github.com/FFmpeg/FFmpeg/blob/n9.0.2/libavfilter/vsrc_ddagrab.c),
  [scheduler](https://github.com/FFmpeg/FFmpeg/blob/n9.0.2/fftools/ffmpeg_sched.c).
- VDD 25.7.23 [driver](https://github.com/VirtualDrivers/Virtual-Display-Driver/blob/25.7.23/Virtual%20Display%20Driver%20(HDR)/MttVDD/Driver.cpp)
  and [adapter selection](https://github.com/VirtualDrivers/Virtual-Display-Driver/blob/25.7.23/Common/Include/AdapterOption.h).
