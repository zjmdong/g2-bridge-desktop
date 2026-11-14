# Windows capture build

This builds the modified FFmpeg used for Desktop Duplication and NVIDIA H.264
encoding. Version 0.2.6 adds opt-in bounded fresh-image acquisition and
source-clock delivery deadlines to the existing DDA timing, source-phase
alignment, D3D11 scaler, asynchronous NVENC output and bounded raw-frame mailbox.
The command interface is retained; both new options default to zero. It does
not alter the goggles USB protocol or roll back the desktop's High/CABAC policy.

The default output is `work/ffmpeg-repro-n9.0.2/install/bin`. The build script
does not overwrite `vendor/ffmpeg/ffmpeg.exe`; promotion of a validated binary is
a separate packaging step.

## Inputs

`manifest.json` pins FFmpeg tag `n9.0.2`, commit
`946fcce07b6dcd0331c8cc609192aeff5e1924f8`, the portable MSYS2 base, dependency
package versions and SHA-256 values, and the patch identity. The package archives
were installed with MSYS2 signature verification enabled. Use MSYS2 UCRT64, GCC
16.2.0, NASM 3.02, and ffnvcodec headers 13.0.19.0. No CUDA SDK installation or
administrator elevation is required for this build.

The complete upstream source archive is supplied at
`vendor/ffmpeg/source/ffmpeg-upstream-n9.0.2.tar.gz` in the release source bundle.
It is ignored by Git. To reconstruct it from the official upstream repository
in a new local directory:

```sh
git clone --depth 1 --branch n9.0.2 https://github.com/FFmpeg/FFmpeg.git ffmpeg-upstream
git -C ffmpeg-upstream rev-parse HEAD
git -C ffmpeg-upstream archive --format=tar.gz --prefix=ffmpeg-n9.0.2/ \
    -o ../ffmpeg-upstream-n9.0.2.tar.gz n9.0.2
sha256sum ffmpeg-upstream-n9.0.2.tar.gz
```

Verify the commit and archive hash against `manifest.json`, then place the
archive at the vendor source path. A mismatch must be investigated, not ignored.
Git/compressor versions can affect generated archive bytes; the release source
bundle contains the exact archive used for the validated build.

The required MSYS2 packages are `make`, `diffutils`, `patch`,
`mingw-w64-ucrt-x86_64-gcc`, `mingw-w64-ucrt-x86_64-nasm`,
`mingw-w64-ucrt-x86_64-pkgconf`, and
`mingw-w64-ucrt-x86_64-ffnvcodec-headers`, together with the exact dependency
versions in the manifest. Do not silently substitute current rolling package
versions when reproducing a release.

## Build and check

Run from an MSYS2 UCRT64 shell:

```sh
bash packaging/windows/ffmpeg/build.sh --prepare-only
bash packaging/windows/ffmpeg/build.sh
```

The script checks the source hash, applies the patch to a fresh work directory,
builds FFmpeg/ffprobe, runs clock arithmetic, source-phase acquisition/recovery,
16 bounded fresh-acquisition scenarios, a 10,000-frame delivery-deadline model
with invalid-input checks, and raw-frame mailbox tests,
performs a tiny synthetic CPU encode, and records output hashes. It does not capture the screen, open USB,
start a stream, or require a connected NVIDIA device merely to build.

Optional variables: `GOGGLES_FFMPEG_WORK`, `GOGGLES_FFMPEG_OUTPUT`,
`GOGGLES_FFMPEG_SOURCE_TAR`, `GOGGLES_FFMPEG_JOBS`, and
`GOGGLES_FFMPEG_PYTHON`. The fresh-acquisition test runner uses the project's
`.venv/Scripts/python.exe` by default; set `GOGGLES_FFMPEG_PYTHON` to an explicit
Python interpreter path when reproducing outside that environment.
Use a work/source path
without spaces, as FFmpeg rejects spaces in out-of-tree source paths.
Choose a new work directory when changing source inputs; the script deliberately
does not delete an existing build tree. A portable toolchain under
`work/toolchain/msys64/ucrt64/bin` is recognized without changing global PATH.

The recipe disables third-party autodetection. PNG and `negate` are requested
for compatibility with the research recipe but are disabled by FFmpeg when their
optional dependencies are absent; production capture/NVENC does not use them.
The required DDA, GPU scaler, NVENC, rawvideo, H.264 decoder, AVI, and frame hash
paths are enabled. The build configuration is recorded by `ffmpeg -buildconf`.

The recipe fixes `SOURCE_DATE_EPOCH` to the upstream commit time (1789687190),
disables current-time PE link timestamps, remaps absolute source/build paths in `__FILE__`
through GCC's make-time `ECFLAGS`, uses a generic install prefix, and disables
debug information. The remapping flags are not part of the embedded configure
command string. These controls remove common build-time
and user-directory differences. They do not alone establish bit-for-bit
reproducibility across different toolchains or library versions; compare hashes
from clean builds using the pinned dependencies before making that claim.
With the pinned Binutils toolchain, the PE timestamp is the fixed
`SOURCE_DATE_EPOCH`, rather than zero or the current build time.

## Timing controls and interpretation

The patched DDA defaults are
`precise_clock=1:acquire_timeout=0:clock_spin_us=500:fresh_wait_us=0:delivery_delay_us=0`.
The clock uses QPC and a high-resolution waitable timer, with a bounded 500 us
busy tail. At 100 fps this consumes at most 5% of one logical core for the tail.
It skips expired deadlines after a stall instead of replaying an unbounded
backlog. The bounded fresh-acquisition path explicitly tracks texture references
and ownership of a DXGI duplication frame across retries and timeout fallback.

The desktop explicitly sets `source_clock=1:source_guard_us=3000`,
`fresh_wait_us=2000`, and `delivery_delay_us=8000` for both primary and virtual
display sources. The native defaults leave source alignment and both new controls
off for existing callers. Fresh acquisition has one shared deadline across
retries, capped by its configured budget and the next capture slot. Every retry
on this live path calls `AcquireNextFrame(0)` and uses the existing high-resolution
timer for intervals of at most 250 microseconds; no positive DXGI timeout or
unbounded spin loop is used. The final nonblocking poll may accept an already
ready image at the deadline. A mouse-only update does not count as a new desktop
image. Initial probing and callers with fresh retry disabled retain their existing
acquisition policy. OS/driver scheduling can still overshoot a requested timer
deadline, and a zero timeout is not a hard bound on API execution.

The earlier positive-timeout retry candidate had approximately 20 ms long tails
in actual USB streaming despite improved host-only cadence. It was superseded
by this nonblocking policy. A 64 KiB stdout-pipe experiment and a 5 ms source
guard were not adopted; the production pipe and 3 ms guard remain unchanged.
The primary-display follow-up with a 4 ms fresh-image budget also retained a
presented-but-omitted source ID. The production fresh-image budget remains
2 ms; the available checks do not establish universal zero picture loss.

Delivery uses **scheduled capture slot + 8 ms**, carried through metadata,
`FrameData`, and the existing NVENC `COPY_OPAQUE` association. It is not an extra
8 ms sleep after encoding. The mux thread waits only for remaining budget after
bitstream filtering, before AVI output. Each frame, including repeats, has its
own deadline; late access units go immediately without shifting later deadlines
or dropping encoded references. The existing single-packet queue remains, and
the mux holds the current packet during its wait. This is bounded added latency,
not zero buffering and not the accumulating sender pacer removed in 0.2.2.

The mux owns a high-resolution waitable timer and uses at most a 100 us spin
tail, without a new system timer-policy change. Validation rejects budgets
exceeding one source frame period or 20 ms, invalid metadata and mismatched QPC
clocks. A single INFO `G2_DELIVERY_SUMMARY` at shutdown reports eligible frames,
completed waits, late arrivals, arrivals over 100 us late, maximum arrival
lateness, maximum wait overshoot and total actual wait. It reuses existing QPC
reads and adds no per-frame log, allocation or USB readback. A wait interrupted
by shutdown/error is eligible but not counted as a completed wait.

For a comparison using the same executable, set
`precise_clock=0:acquire_timeout=-1`; this selects the upstream-style sleep clock
and half-frame acquisition timeout. `clock_spin_us` accepts 0 through 1000.
The standalone test includes the actual clock header from the patched source;
run its generated `check_clock.exe --measure 500` for a timer-only measurement.

Capture clock/source-phase controls act before encoding; the opt-in delivery
deadline also holds early completed access units in the native mux thread.
There is no added Python USB-sender pacer. Static desktop repeats, a 60 Hz source streamed at
100 fps, GPU scheduling, encoding, USB completion and headset scanout are separate
effects. Host timing tests do not establish optical latency or a universal 1%
variation bound.
The release's host measurements and added-wait tradeoff are documented in
[0.2.6 validation](../../../docs/desktop/VALIDATION-0.2.6.md); they are not a new
optical-latency acceptance result.

See `NOTICE.txt` and `licenses/` for redistribution notices. Distribute the
complete source archive and this directory with the app's source release.

## Updating the local patch

Work on a checkout of the exact pinned FFmpeg commit. After editing capture,
scaler, NVENC or scheduling sources, run:

```sh
python packaging/windows/ffmpeg/refresh_patch.py --source-tree work/ffmpeg-src-n9.0.2
```

This includes changes throughout `libavfilter`, `libavcodec`, `libavutil` and `fftools`,
including the delivery-policy header/tests, new source headers and the PowerShell mailbox test runner under
`fftools/tests`, verifies reverse application against the working tree, and
updates source and recipe hashes. It removes obsolete executable identities when
the patch or recipe changes. Use a fresh work directory for the subsequent build, validate it, then
record the final executable hashes in the release manifest's `release_binaries`
mapping, keyed by `ffmpeg.exe` and `ffprobe.exe`, each with `sha256` and `bytes`.
A successful patch
refresh is not evidence that an older executable contains the new changes.
