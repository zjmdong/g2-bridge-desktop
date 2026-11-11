#!/usr/bin/env bash
# Build only the pinned FFmpeg capture/encode tool, without touching vendor binaries.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
WORK="${GOGGLES_FFMPEG_WORK:-$ROOT/work/ffmpeg-repro-n9.0.2}"
OUTPUT="${GOGGLES_FFMPEG_OUTPUT:-$WORK/install}"
ARCHIVE="${GOGGLES_FFMPEG_SOURCE_TAR:-$ROOT/vendor/ffmpeg/source/ffmpeg-upstream-n9.0.2.tar.gz}"
SOURCE="$WORK/src/ffmpeg-n9.0.2"
PATCH="$HERE/ffmpeg-n9.0.2-goggles.patch"
SOURCE_SHA=c1d85f248a1c5e0a106f501f6893b2cdfe902607446d39df562e5f82eefc910e
# Pinned upstream commit time, not the local checkout/build time.
export SOURCE_DATE_EPOCH=1789687190
export TZ=UTC
export LC_ALL=C

if [[ -d "$ROOT/work/toolchain/msys64/ucrt64/bin" ]]; then
    export PATH="$ROOT/work/toolchain/msys64/ucrt64/bin:$PATH"
fi
if [[ "${MSYSTEM:-}" != UCRT64 ]]; then
    echo 'Run this script inside an MSYS2 UCRT64 shell.' >&2
    exit 1
fi
for program in gcc g++ make nasm pkg-config patch tar sha256sum cygpath; do
    command -v "$program" >/dev/null || { echo "Missing build tool: $program" >&2; exit 1; }
done
[[ "$(gcc -dumpmachine)" == x86_64-w64-mingw32 ]] || { echo 'An x86_64 MinGW-w64 compiler is required.' >&2; exit 1; }
[[ "$(gcc -dumpfullversion)" == 16.2.0 ]] || { echo 'Use the pinned GCC 16.2.0 toolchain from manifest.json.' >&2; exit 1; }
[[ "$(pkg-config --modversion ffnvcodec)" == 13.0.19.0 ]] || { echo 'Use ffnvcodec headers 13.0.19.0.' >&2; exit 1; }
[[ -f "$ARCHIVE" ]] || { echo "Missing corresponding source archive: $ARCHIVE; see README.md." >&2; exit 1; }
printf '%s  %s\n' "$SOURCE_SHA" "$ARCHIVE" | sha256sum --check --status
PATCH_SHA="$(sha256sum "$PATCH" | cut -d ' ' -f 1)"
INPUT_ID="$SOURCE_SHA $PATCH_SHA"

if [[ -d "$SOURCE" ]]; then
    [[ -f "$SOURCE/.goggles-build-inputs" && "$(cat "$SOURCE/.goggles-build-inputs")" == "$INPUT_ID" ]] || {
        echo 'This build directory has different or unfinished source inputs. Set GOGGLES_FFMPEG_WORK to a new directory.' >&2
        exit 1
    }
else
    mkdir -p "$WORK/src"
    tar -xzf "$ARCHIVE" -C "$WORK/src"
    patch --batch --forward -d "$SOURCE" -p1 < "$PATCH"
    printf '%s\n' "$INPUT_ID" > "$SOURCE/.goggles-build-inputs"
fi

if [[ "${1:-}" == --prepare-only ]]; then
    echo "Verified and patched corresponding source: $SOURCE"
    exit 0
fi
[[ $# == 0 ]] || { echo 'Usage: build.sh [--prepare-only]' >&2; exit 1; }

mkdir -p "$WORK/build" "$OUTPUT"
OUTPUT="$(cd "$OUTPUT" && pwd)"
cd "$WORK/build"
# Generic prefix keeps the configure string independent of the build directory.
../src/ffmpeg-n9.0.2/configure \
  --target-os=mingw32 --arch=x86_64 --cc=gcc --cxx=g++ --pkg-config=pkg-config \
  --prefix=/ \
  --disable-everything --disable-autodetect --disable-network --disable-doc --disable-debug \
  --disable-shared --enable-static --enable-w32threads \
  --enable-ffmpeg --enable-ffprobe --disable-ffplay \
  --enable-avdevice --enable-swscale --enable-ffnvcodec --enable-nvenc --enable-d3d11va \
  --enable-indev=lavfi \
  --enable-protocol=file,pipe \
  --enable-demuxer=avi,h264,rawvideo,image2 \
  --enable-muxer=avi,h264,null,rawvideo,framemd5,framehash,md5,image2 \
  --enable-parser=h264 \
  --enable-decoder=h264,rawvideo,wrapped_avframe,png \
  --enable-encoder=h264_nvenc,rawvideo,wrapped_avframe,png \
  --enable-bsf=filter_units,h264_metadata,h264_mp4toannexb,trace_headers \
  --enable-filter=ddagrab,scale_d3d11,hwupload,hwdownload,format,scale,pad,setsar,setparams,setpts,settb,select,testsrc2,testsrc,color,drawbox,null,split,psnr,ssim,trim,negate,framestep \
  --extra-ldflags='-static -Wl,--no-insert-timestamp' --extra-libs=-lwinmm \
  --extra-version=goggles-streamer-clock
# FFmpeg resolves out-of-tree source paths to absolute paths. Remap __FILE__
# through make's extra C flags, outside the embedded configure command string.
REMAP_FLAGS="-ffile-prefix-map=$(cygpath -m "$SOURCE")=ffmpeg -ffile-prefix-map=$(cygpath -m "$WORK/build")=build"
make -j "${GOGGLES_FFMPEG_JOBS:-8}" ECFLAGS="$REMAP_FLAGS"
make install DESTDIR="$OUTPUT" ECFLAGS="$REMAP_FLAGS"
gcc -O2 -static -I "$SOURCE/libavfilter" "$HERE/check_clock.c" -o check_clock.exe -lwinmm
./check_clock.exe
gcc -std=c17 -O2 -static -I "$SOURCE/libavfilter" \
    "$SOURCE/libavfilter/tests/ddagrab_source_clock.c" -o check_source_clock.exe -lwinmm
./check_source_clock.exe
gcc -std=c17 -O2 -Wall -Wextra -Werror \
    -Wno-unused-parameter -Wno-cast-function-type -U__STRICT_ANSI__ -DWIN32_LEAN_AND_MEAN \
    -I . -I "$SOURCE" "$SOURCE/fftools/tests/thread_queue_mailbox.c" \
    "$SOURCE/fftools/thread_queue.c" libavcodec/libavcodec.a libavutil/libavutil.a \
    -static -lm -luser32 -lbcrypt -latomic -lole32 -lwinmm -o check_mailbox.exe
./check_mailbox.exe
"$OUTPUT/bin/ffmpeg.exe" -hide_banner -v error -filter_complex 'color=size=16x16:rate=100' \
    -frames:v 3 -c:v rawvideo -f framemd5 pipe:1
(cd "$OUTPUT/bin" && sha256sum ffmpeg.exe ffprobe.exe) > "$OUTPUT/SHA256SUMS"
echo "Build complete: $OUTPUT/bin (vendor binaries were not changed)."
