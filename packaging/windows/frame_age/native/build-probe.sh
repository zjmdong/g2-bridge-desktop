#!/usr/bin/env bash
# Independent research build only. Never writes vendor binaries or installed apps.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
STAGE="${1:-source-clock-v2}"
case "$STAGE" in
  before-source-clock|source-clock-v1|source-clock-v2)
    BASE="$HERE/base-0.2.3-goggles.patch"
    PROBE="$HERE/probe-$STAGE.patch" ;;
  production-v024)
    BASE="$ROOT/packaging/windows/ffmpeg/ffmpeg-n9.0.2-goggles.patch"
    PROBE="$HERE/instrument-production-v024.patch" ;;
  *) echo 'Stage must be before-source-clock, source-clock-v1, source-clock-v2 or production-v024.' >&2; exit 1 ;;
esac
[[ $# -le 1 ]] || { echo 'Usage: build-probe.sh [stage]' >&2; exit 1; }
WORK="${G2_PROBE_WORK:-$ROOT/work/frame-age-rebuild-$STAGE}"
SOURCE="$WORK/src/ffmpeg-n9.0.2"
ARCHIVE="${GOGGLES_FFMPEG_SOURCE_TAR:-$ROOT/vendor/ffmpeg/source/ffmpeg-upstream-n9.0.2.tar.gz}"
SOURCE_SHA=c1d85f248a1c5e0a106f501f6893b2cdfe902607446d39df562e5f82eefc910e
export SOURCE_DATE_EPOCH=1789687190 TZ=UTC LC_ALL=C
if [[ -d "$ROOT/work/toolchain/msys64/ucrt64/bin" ]]; then
  export PATH="$ROOT/work/toolchain/msys64/ucrt64/bin:$PATH"
fi
[[ "${MSYSTEM:-}" == UCRT64 ]] || { echo 'Run inside MSYS2 UCRT64.' >&2; exit 1; }
for program in gcc g++ make nasm pkg-config patch tar sha256sum; do
  command -v "$program" >/dev/null || { echo "Missing $program" >&2; exit 1; }
done
[[ "$(gcc -dumpmachine)" == x86_64-w64-mingw32 && "$(gcc -dumpfullversion)" == 16.2.0 ]] || {
  echo 'Use the pinned x86_64 MinGW-w64 GCC 16.2.0 toolchain.' >&2; exit 1;
}
[[ "$(pkg-config --modversion ffnvcodec)" == 13.0.19.0 ]] || {
  echo 'Use ffnvcodec headers 13.0.19.0.' >&2; exit 1;
}
(cd "$HERE" && sha256sum --check --status SHA256SUMS)
printf '%s  %s\n' "$SOURCE_SHA" "$ARCHIVE" | sha256sum --check --status
INPUT_ID="$SOURCE_SHA $(sha256sum "$BASE" "$PROBE")"
if [[ -d "$SOURCE" ]]; then
  [[ -f "$SOURCE/.g2-probe-inputs" && "$(cat "$SOURCE/.g2-probe-inputs")" == "$INPUT_ID" ]] || {
    echo 'Existing source differs; select a fresh G2_PROBE_WORK directory.' >&2; exit 1;
  }
else
  mkdir -p "$WORK/src"
  tar -xzf "$ARCHIVE" -C "$WORK/src"
  patch --batch --forward -d "$SOURCE" -p1 < "$BASE"
  patch --batch --forward -d "$SOURCE" -p1 < "$PROBE"
  printf '%s\n' "$INPUT_ID" > "$SOURCE/.g2-probe-inputs"
fi
mkdir -p "$WORK/build"
cd "$WORK/build"
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
# Historical probe builds used the above exact configure options without the
# production ECFLAGS path remapping. Keep measured-source fidelity here; an
# alternate build path can change diagnostic strings and therefore binary hash.
make -j "${G2_PROBE_JOBS:-8}" ffmpeg.exe
sha256sum ffmpeg.exe > SHA256SUMS
echo "Research binary: $WORK/build/ffmpeg.exe"
