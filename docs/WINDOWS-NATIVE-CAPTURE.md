# Native Windows capture in the personal edition

Personal release installers enable this backend by default on NVIDIA and also use
it for leased virtual screens. See [the personal release guide](PERSONAL-RELEASE.md).

This opt-in backend uses Desktop Duplication and NVIDIA NVENC. It keeps one
replaceable raw frame, GPU scaling on NVIDIA displays, asynchronous encoding,
and delivery deadlines tied to the capture clock. USB framing is unchanged.
A worker isolates capture and USB sending from the WebView; a bounded background
writer keeps UI and diagnostic storage stalls off the sender thread.

Build the native FFmpeg using [the pinned recipe](../packaging/windows/ffmpeg/README.md),
then set `GOGGLES_NATIVE_FFMPEG` to its absolute path and choose **Desktop
Duplication** in Advanced. Missing native inputs are reported as errors.
Windows Graphics Capture, CLI defaults and macOS keep their existing paths.
AMD AMF also keeps the stock backend, even in a native-enabled package.
Periodic keyframes and the existing advanced preferences remain available;
the native encoder disables intra refresh.

For a native installer, place the rebuilt executable and upstream archive at
the manifest's `vendor/ffmpeg` paths, run `python packaging/verify_native.py`,
then `python packaging/build_windows.py --native`. It includes the worker,
stock FFmpeg for WGC, and the native sources and licenses. The normal build
command remains stock and overwrites the build-mode marker so leftover native
files cannot activate this backend after a stock upgrade.

The 3 ms source guard, 2 ms acquisition budget and capture-slot delivery offset
(6 ms at 100 fps on NVIDIA displays, otherwise 8 ms) are scheduling policies,
not optical latency measurements.
Late encoded frames are sent immediately and remain ordered. A non-NVIDIA
capture adapter needs a CPU transfer to NVENC. Diagnostics may lose old events
if storage or the UI stalls. Test streaming changes on goggles and record a
matched before/after measurement using [the latency method](LATENCY.md).
