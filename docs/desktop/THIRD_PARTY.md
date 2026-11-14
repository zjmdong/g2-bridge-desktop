# Third-party components — 0.2.6

DJI Goggles Streamer and G2 Bridge, including its audited local SDK patches, are GPL-3.0-only. The
application installer includes LICENSE and this notice. A source archive is
delivered alongside the installer. No DJI executable, driver or firmware is
redistributed in the installer or project source.

| Component | Version | License / upstream source |
| --- | --- | --- |
| G2 Bridge | a34690a58d48f0cd9b43cdeddf39b5efaf024b9c | GPL-3.0-only, https://github.com/Ammaar-Alam/g2-bridge |
| Python | 3.11.9 | PSF license, https://www.python.org/downloads/release/python-3119/ |
| PySide6 / Qt | 6.10.3 | LGPL-3.0 / GPL; dynamically loaded libraries, https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.3-src/ and https://download.qt.io/archive/qt/6.10/6.10.3/submodules/ |
| PyUSB | 1.3.1 | BSD-3-Clause, https://github.com/pyusb/pyusb/tree/v1.3.1 |
| FFmpeg, locally modified minimal build | n9.0.2, upstream commit 946fcce07b6dcd0331c8cc609192aeff5e1924f8 | LGPL-2.1-or-later configuration, [upstream source](https://github.com/FFmpeg/FFmpeg/tree/n9.0.2), [pinned build recipe](../../packaging/windows/ffmpeg/README.md) |
| NVIDIA codec API headers | 13.0.19.0 | NVIDIA permissive license; retained in the native build's `licenses/NVENC-headers-LICENSE`; NVIDIA driver is not bundled |
| GCC runtime / MinGW-w64 winpthreads | Pinned dependencies in the native manifest | GCC GPLv3 with Runtime Library Exception 3.1; winpthreads notices retained under the native build's `licenses/` |
| innoextract | 1.9 | zlib, Boost Software License, LGPL runtime exception; bundled upstream license files, https://constexpr.org/innoextract/ and https://github.com/dscharrer/innoextract/tree/1.9 |
| PyInstaller bootloader | 6.22.3 | GPL with bootloader exception, https://github.com/pyinstaller/pyinstaller |
| Inno Setup installer engine | 6.7.4 | Inno Setup license, https://github.com/jrsoftware/issrc/tree/is-6_7_4 |
| Virtual Display Driver | 25.7.23 package, driver 11.30.4.434 | MIT, https://github.com/VirtualDrivers/Virtual-Display-Driver/tree/25.7.23 ; bundled VDD-LICENSE.txt |

FFmpeg is a modified standalone executable, invoked as a separate process; its
libraries are not linked into the desktop application. Version 0.2.6 rebuilds
the minimal LGPL native binary and patch with opt-in bounded fresh-image
acquisition and source-clock delivery deadlines. The live fresh-image path uses
zero-timeout DXGI acquisition, with at most 250 microsecond timer intervals
inside one shared 2 ms budget; it does not bundle a new runtime library.
Both options default to zero
in FFmpeg; the desktop explicitly selects `fresh_wait_us=2000` and
`delivery_delay_us=8000`. The 8 ms deadline is relative to the capture slot,
not an extra 8 ms after encoding. The 0.2.5 High/CABAC policy and symmetric
chroma QP offsets of -4 are retained without adding a runtime dependency.
The remaining native changes cover the QPC DDA clock with opt-in source-phase
alignment, D3D11 SDR conversion/letterboxing, opt-in NVENC completion events,
and the single-slot raw-frame mailbox. Of the 70 recorded G2 Bridge SDK files, 68 match their
original hashes. Two exact audited patches recorded in `sdk-patches.json` cover
the engine's optional GPU scheduling policy and correction of an invalid D3D
context assumption in an existing test. The engine is the only modified SDK
runtime file. The original baseline and goggles USB protocol are preserved.

The installer includes FFmpeg's license and notice under
`_internal/vendor/ffmpeg`, plus the complete upstream archive
`source/ffmpeg-upstream-n9.0.2.tar.gz`, local patch, build script, dependency
manifest and license texts under `source/`. The separately delivered Source.zip
contains the same upstream archive at `vendor/ffmpeg/source/`, with the patch,
recipe, manifest and notices in `packaging/windows/ffmpeg/`. Preserve these
materials when redistributing the executable. The source archive is deliberately
not tracked in Git; the build guide explains how to reconstruct and verify it.

Before preparing a release, follow the [native build instructions](../../packaging/windows/ffmpeg/README.md).
`prepare.py` checks the selected FFmpeg/ffprobe binaries against the manifest's
release hashes and checks the corresponding-source archive. It does not download
an older stock FFmpeg to replace missing or mismatched native binaries.

Qt libraries remain separate and replaceable in
`_internal/PySide6`. Wheel notices and Python's license are retained in
`_internal/vendor/licenses`. innoextract and its original notices live in
`_internal/vendor/innoextract`. The build script records binary archive URLs
and SHA-256 hashes in `build-inputs.json`; it never downloads a floating latest
build. Native FFmpeg source, patch, dependency and executable identities are
recorded separately in `packaging/windows/ffmpeg/manifest.json`.

See the [current implementation notes](IMPLEMENTATION.md),
[0.2.6 validation record](VALIDATION-0.2.6.md) and
[protocol/performance limits](PROTOCOL_LIMITS.md) for the scope of the changes
and evidence. The modified build does not establish a new optical latency or
USB hardware capability merely by retaining these provenance records.

The app icon is original geometric artwork drawn by `desktop_app.ui.app_icon`;
it contains no DJI logo or externally sourced raster image.

The optional driver installer downloads DJI Assistant 2 Consumer Drones 2.1.42
from DJI's official CDN at runtime, verifies its pinned SHA-256 and Windows
signature, extracts the original signed 5.0.0.7 driver, verifies each driver
file, and invokes Windows PnPUtil. The package and driver remain subject to
their original vendor terms. Windows elevation is requested only for driver
installation, never for normal video streaming. No firmware is flashed.

The optional virtual display driver is redistributed under MIT in
`_internal/vendor/vdd`, with its original INF/DLL/catalog and SignPath signature.
The release archive is pinned by SHA-256. The app writes its own SDR configuration
for 720p/1080p at 60/75/90/100 Hz on installation or an explicit owned-device
configuration update, registers its own root display device,
and never uses VDD's unsafe `RELOAD_DRIVER`/`SETDISPLAYCOUNT` pipe paths.
No certificate-store or signature-enforcement settings are changed.
