# Windows capture build

This builds the modified FFmpeg used for Desktop Duplication and NVIDIA H.264
encoding. It changes capture timing and the D3D11 scaler, adds opt-in source-phase
alignment, asynchronous
NVENC output and a bounded raw-frame mailbox, and preserves the existing FFmpeg
command interface. It does not alter the goggles USB protocol.

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
builds FFmpeg/ffprobe, runs the clock arithmetic, source-phase acquisition/recovery,
and raw-frame mailbox tests,
performs a tiny synthetic CPU encode, and records output hashes. It does not capture the screen, open USB,
start a stream, or require a connected NVIDIA device merely to build.

Optional variables: `GOGGLES_FFMPEG_WORK`, `GOGGLES_FFMPEG_OUTPUT`,
`GOGGLES_FFMPEG_SOURCE_TAR`, and `GOGGLES_FFMPEG_JOBS`. Use a work/source path
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

The patched DDA defaults are `precise_clock=1:acquire_timeout=0:clock_spin_us=500`.
The clock uses QPC and a high-resolution waitable timer, with a bounded 500 us
busy tail. At 100 fps this consumes at most 5% of one logical core for the tail.
It skips expired deadlines after a stall instead of replaying an unbounded
backlog. Texture ownership and release follow the upstream DDA implementation.

For a comparison using the same executable, set
`precise_clock=0:acquire_timeout=-1`; this selects the upstream-style sleep clock
and half-frame acquisition timeout. `clock_spin_us` accepts 0 through 1000.
The standalone test includes the actual clock header from the patched source;
run its generated `check_clock.exe --measure 500` for a timer-only measurement.

These controls act before capture/encoding. They do not delay completed H.264
pictures at the USB sender. Static desktop repeats, a 60 Hz source streamed at
100 fps, GPU scheduling, encoding, USB completion and headset scanout are separate
effects. Host timing tests do not establish optical latency or a universal 1%
variation bound.

See `NOTICE.txt` and `licenses/` for redistribution notices. Distribute the
complete source archive and this directory with the app's source release.

## Updating the local patch

Work on a checkout of the exact pinned FFmpeg commit. After editing capture,
scaler, NVENC or scheduling sources, run:

```sh
python packaging/windows/ffmpeg/refresh_patch.py --source-tree work/ffmpeg-src-n9.0.2
```

This includes changes throughout `libavfilter`, `libavcodec` and `fftools`,
including new source headers and the PowerShell mailbox test runner under
`fftools/tests`, verifies reverse application against the working tree, and
updates source and recipe hashes. It removes obsolete executable identities when
the patch or recipe changes. Use a fresh work directory for the subsequent build, validate it, then
record the final executable hashes in the release manifest's `release_binaries`
mapping, keyed by `ffmpeg.exe` and `ffprobe.exe`, each with `sha256` and `bytes`.
A successful patch
refresh is not evidence that an older executable contains the new changes.
