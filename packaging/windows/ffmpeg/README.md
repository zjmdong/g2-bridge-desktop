# Windows capture build

This directory contains the corresponding source patch, pinned build recipe,
native tests and redistribution notices for the Windows desktop's FFmpeg.
It adds GPU Desktop Duplication capture and scaling, asynchronous NVENC output,
a bounded raw-frame mailbox, and capture-clock delivery deadlines. It leaves
the goggles USB protocol unchanged. The application uses NVIDIA H.264 encoding;
there is no software H.264 fallback.

## Pinned inputs

`manifest.json` identifies FFmpeg tag `n9.0.2`, commit
`946fcce07b6dcd0331c8cc609192aeff5e1924f8`, the patch, build/test inputs,
MSYS2 packages, and validated executable hashes. Use MSYS2 UCRT64, GCC 16.2.0,
NASM 3.02 and ffnvcodec headers 13.0.19.0. The dependency archives were installed
with MSYS2 signature verification enabled. Building requires neither a CUDA
SDK installation nor administrator privileges.

The release source bundle includes the complete upstream archive at
`vendor/ffmpeg/source/ffmpeg-upstream-n9.0.2.tar.gz` (not tracked by Git).
To reconstruct it from the official repository in a new directory:

```sh
git clone --depth 1 --branch n9.0.2 https://github.com/FFmpeg/FFmpeg.git ffmpeg-upstream
git -C ffmpeg-upstream rev-parse HEAD
git -C ffmpeg-upstream archive --format=tar.gz --prefix=ffmpeg-n9.0.2/ \
    -o ../ffmpeg-upstream-n9.0.2.tar.gz n9.0.2
sha256sum ffmpeg-upstream-n9.0.2.tar.gz
```

Check the commit and archive hash against the manifest before placing the
archive at the vendor path. Git/compressor versions can change archive bytes;
use the release source bundle for the exact validated archive rather than
ignoring a mismatch. Install the exact manifest versions of `make`, `diffutils`,
`patch`, UCRT64 GCC, NASM, pkgconf, ffnvcodec headers and their dependencies.

## Build and verify

From an MSYS2 UCRT64 shell at the repository root:

```sh
bash packaging/windows/ffmpeg/build.sh --prepare-only
bash packaging/windows/ffmpeg/build.sh
```

The script verifies the source hash, applies the patch, builds FFmpeg/ffprobe,
then runs native clock arithmetic, source-phase, bounded fresh-acquisition,
delivery-deadline and raw-frame mailbox tests. A tiny synthetic CPU rawvideo
encode checks the executable; building does not capture the desktop, open USB,
or require a connected NVIDIA device. The patched native test sources and the
mailbox runner are included in `ffmpeg-n9.0.2-goggles.patch`.

Output defaults to `work/ffmpeg-repro-n9.0.2/install/bin`; the script does not
replace the application's vendor binary. Optional variables are
`GOGGLES_FFMPEG_WORK`, `GOGGLES_FFMPEG_OUTPUT`, `GOGGLES_FFMPEG_SOURCE_TAR`,
`GOGGLES_FFMPEG_JOBS`, and `GOGGLES_FFMPEG_PYTHON`. Set the latter to a Windows
Python interpreter when `.venv/Scripts/python.exe` is unavailable. Use source
and work paths without spaces. Select a fresh work directory for changed
inputs; the script deliberately does not delete an existing build tree.

The recipe disables third-party autodetection and records `ffmpeg -buildconf`.
Optional PNG/negate research paths can be disabled when their dependencies are
absent; production uses DDA, D3D11 scaling, NVENC and AVI. Fixed
`SOURCE_DATE_EPOCH`, PE timestamps, remapped source paths and a generic install
prefix reduce build-environment differences. Compare clean-build hashes with
pinned toolchains before claiming bit-for-bit reproducibility.

## Timing behavior

The desktop adapter in `goggles_bridge/app/windows/video.py` uses the same
pipeline for physical and virtual displays:

- QPC capture deadlines with a high-resolution waitable timer; expired slots
  are skipped rather than replaying a backlog.
- Source-phase alignment with a 3 ms guard, and a shared 2 ms fresh-image retry
  budget using nonblocking `AcquireNextFrame(0)` calls.
- A one-slot mailbox that replaces stale **unencoded** images. Encoded reference
  pictures remain ordered and are not dropped by the mailbox.
- GPU SDR RGB to limited-range NV12 conversion on NVIDIA outputs, followed by
  asynchronous NVENC. A foreign GPU requires an explicit transfer to NVIDIA.
- Delivery at scheduled capture slot plus 8 ms, waiting only the remaining
  budget after encoding. Late access units go immediately; they do not shift
  subsequent deadlines. This is bounded buffering, not an extra 8 ms sleep
  after encoding or a Python USB pacer.

Native `fresh_wait_us` and `delivery_delay_us` default to zero for other callers.
The live retry budget is also capped by the next source slot. Source-clock and
delivery tests exercise timeout, reference ownership, missed slots and invalid
metadata. The native delivery summary is emitted once at shutdown, without
per-frame logging or device feedback.

OS/GPU scheduling, source rendering, USB completion and headset scanout still
affect timing. Repeating a 60 Hz source at 100 fps cannot create 100 distinct
images. These tests do not establish optical latency, a universal 1% jitter
bound, or lossless monitor-equivalent transport.

## Updating the patch

Edit a checkout of the exact pinned FFmpeg commit, then run:

```sh
python packaging/windows/ffmpeg/refresh_patch.py --source-tree work/ffmpeg-src-n9.0.2
```

This collects changes under `libavfilter`, `libavcodec`, `libavutil` and
`fftools`, verifies reverse patch application, and refreshes source/recipe
hashes. Changed inputs invalidate old executable identities. Build and validate
again before recording `release_binaries` hashes and sizes; refreshing a patch
does not establish that an older binary contains it.

Include `NOTICE.txt`, `licenses/`, this recipe and the complete corresponding
upstream archive when distributing the executable and its source release.
