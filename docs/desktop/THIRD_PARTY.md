# Third-party components — 0.1.1

DJI Goggles Streamer and the unchanged G2 Bridge SDK are GPL-3.0-only. The
application installer includes LICENSE and this notice. A source archive is
delivered alongside the installer. No DJI executable, driver or firmware is
redistributed in the installer or project source.

| Component | Version | License / upstream source |
| --- | --- | --- |
| G2 Bridge | a34690a58d48f0cd9b43cdeddf39b5efaf024b9c | GPL-3.0-only, https://github.com/Ammaar-Alam/g2-bridge |
| Python | 3.11.9 | PSF license, https://www.python.org/downloads/release/python-3119/ |
| PySide6 / Qt | 6.10.3 | LGPL-3.0 / GPL; dynamically loaded libraries, https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.3-src/ and https://download.qt.io/archive/qt/6.10/6.10.3/submodules/ |
| PyUSB | 1.3.1 | BSD-3-Clause, https://github.com/pyusb/pyusb/tree/v1.3.1 |
| FFmpeg (Gyan essentials) | 9.0.2 | GPL-3.0-or-later build, https://www.gyan.dev/ffmpeg/builds/ and https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2 |
| innoextract | 1.9 | zlib, Boost Software License, LGPL runtime exception; bundled upstream license files, https://constexpr.org/innoextract/ and https://github.com/dscharrer/innoextract/tree/1.9 |
| PyInstaller bootloader | 6.22.3 | GPL with bootloader exception, https://github.com/pyinstaller/pyinstaller |
| Inno Setup installer engine | 6.7.4 | Inno Setup license, https://github.com/jrsoftware/issrc/tree/is-6_7_4 |
| Virtual Display Driver | 25.7.23 package, driver 11.30.4.434 | MIT, https://github.com/VirtualDrivers/Virtual-Display-Driver/tree/25.7.23 ; bundled VDD-LICENSE.txt |

FFmpeg is an unmodified standalone executable, invoked as a separate process.
Its original LICENSE and README, including build provenance, are retained in
`_internal/vendor/ffmpeg`. Qt libraries remain separate and replaceable in
`_internal/PySide6`. Wheel notices and Python's license are retained in
`_internal/vendor/licenses`. innoextract and its original notices live in
`_internal/vendor/innoextract`. The build script records binary archive URLs
and SHA-256 hashes in `build-inputs.json`; it never downloads a floating latest
build. Preserve these notices when redistributing the application.

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
The release archive is pinned by SHA-256. The app writes its own 1080p/60 Hz SDR
configuration only on a new installation, registers its own root display device,
and never uses VDD's unsafe `RELOAD_DRIVER`/`SETDISPLAYCOUNT` pipe paths.
No certificate-store or signature-enforcement settings are changed.
