<p align="center">
  <img src="goggles_bridge/app/ui/icon.svg" width="96" alt="">
</p>

<h1 align="center">Goggles Bridge</h1>

<p align="center">Your screen, in your DJI goggles.</p>

<p align="center">
  <a href="https://github.com/Ammaar-Alam/goggles-bridge/releases/latest">Download</a> ·
  <a href="docs/LATENCY.md">Latency</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

https://github.com/user-attachments/assets/273c06b9-3275-4446-9f38-1e03a633cfc1

Goggles Bridge streams a Windows or Mac display to DJI Goggles 2 or DJI Goggles Integra over a USB cable. The goggles keep their stock firmware and show the stream in Virtual Flight mode. Your simulator and controller run on the computer.

The desktop app for Windows and Mac includes a setup guide and installs updates from its window.

This integration branch adds a Windows-only native NVENC path and automatic
virtual display lifecycle to the upstream app. See [Windows desktop integration](docs/WINDOWS-DESKTOP.md)
for bitrate recommendations, setup, and the scope of the performance changes.

At 1080p100, the median monitor-to-lens delay is about 12 ms on Windows and about 10 ms on macOS. For more information, see [Measure video delay](docs/LATENCY.md).

## Supported goggles

The bridge detects the model when it connects:

| Goggles | Identity | Tested firmware |
| --- | --- | --- |
| DJI Goggles 2 | `E3T ZV900` | 01.11.00.00, 01.12.00.00, 01.14.00.00 (latest) |
| DJI Goggles Integra | `E3T ZV901` | 01.09.00.00 |

## Requirements

On Windows, you need the following hardware and software:

- 64-bit Windows and Python 3.10 or later.
- An NVIDIA GPU with NVENC support.
- FFmpeg with `gfxcapture` and `h264_nvenc`. To install it, run `winget install Gyan.FFmpeg`.
- [DJI Assistant 2 (Consumer Drones Series)](https://www.dji.com/downloads/softwares/dji-assistant-2-consumer-drones-series), which installs the DJI USB driver 5.0.0.7. See [USB and driver requirements](docs/PROTOCOL.md#usb-and-session).

Tests used FFmpeg build `2026-11-05-git-0893feba65` and NVIDIA driver 610.74.

On macOS, you need the following:

- macOS and Python 3.10 or later.
- Apple's command-line developer tools, which build the screen capture helper on the first run.
- [Homebrew](https://brew.sh), for libusb. Before macOS 12.3, the bridge also needs FFmpeg.
- A USB-A-to-USB-C cable. If the Mac has only USB-C ports, add a USB-C-to-USB-A adapter. Over a USB-C-to-USB-C cable, the goggles take the USB host role and the Mac can't detect them.

The stream script offers to install whatever is missing. Tests used an M2 Pro MacBook Pro with macOS 27.0, Swift 6.4.2, and Homebrew FFmpeg 8.1.1.

## Use the desktop app

To stream from Windows without installing Python or FFmpeg, use the Goggles Bridge app:

1. Install [DJI Assistant 2 (Consumer Drones Series)](https://www.dji.com/downloads/softwares/dji-assistant-2-consumer-drones-series) for its USB driver.
2. Download `GogglesBridge-VERSION-Setup.exe` from [Releases](https://github.com/Ammaar-Alam/goggles-bridge/releases), and then run it. The installer isn't signed, so Windows might show a SmartScreen warning.
3. Open Goggles Bridge, and then follow the setup guide.

The app requires 64-bit Windows 10 or 11, an NVIDIA GPU, and the Microsoft Edge WebView2 Runtime, which Windows 11 includes.

On a Mac with Apple silicon and macOS 12.3 or later, download `GogglesBridge-VERSION.dmg` from [Releases](https://github.com/Ammaar-Alam/goggles-bridge/releases), and then drag Goggles Bridge to Applications. The setup guide asks for screen recording permission. Connect the goggles with a USB-A-to-USB-C cable.

![The Goggles Bridge window on a Mac, asking for screen recording permission. The numbers are simulated.](docs/images/app-window-mac.png)

To update the app, select **Update to VERSION** at the bottom of the window.

![The Goggles Bridge window while streaming. A drawing shows a computer connected to goggles, next to the stream settings. The numbers are simulated.](docs/images/app-window.png)

To run the app from the repository, install its dependencies and start it:

```powershell
python -m pip install -r requirements-app.txt
python scripts/goggles_bridge_app.py
```

To build the installer or the Mac app, see the [packaging notes](packaging/README.md).

## Start streaming from the command line

1. Power on the goggles, connect a USB data cable, and open **More > DJI Virtual Flight**. On a Mac, when macOS asks whether the accessory can connect, select **Allow**.
2. From the repository root, install the Python dependencies.

   On Windows, run:

   ```powershell
   python -m pip install -r requirements.txt
   ```

   On macOS, run:

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   ```

3. Start the stream.

   On Windows, run:

   ```powershell
   python scripts/stream_desktop.py
   ```

   On macOS, run:

   ```bash
   .venv/bin/python scripts/stream_desktop.py
   ```

   On Windows, the script finds the DJI driver and FFmpeg automatically. If either is installed somewhere else, pass `--dll` or `--ffmpeg` with the file path.

   On a Mac, the script offers to install anything that's missing, and it builds the screen capture helper on the first run. If the screen can't be captured, go to **System Settings > Privacy & Security** and allow screen recording for your terminal.

The default output is **1920x1080** at a **100 fps encoder target**. Windows uses **32 Mbps**, or automatically selects **24 Mbps at 60 fps** and **30 Mbps at 75 fps**. macOS uses **20 Mbps**. To stop streaming, press **Ctrl+C**. The bridge writes logs to `work/logs/`.

Use these options to adjust the stream:

| Option | Values |
| --- | --- |
| `--fps` | `60`, `75`, `90`, `100` |
| `--bitrate-mbps` | `8`, `10`, `12`, `16`, `20`, `24`. On Windows, also `30`, `32`, and `40` |
| `--display` | Monitor index, starting at `0` |
| `--hide-cursor` | Hide the mouse pointer |
| `--capture` | Windows: `gfxcapture` or `ddagrab`. macOS: `screencapturekit` or `avfoundation` |

Run `python scripts/stream_desktop.py --help` for all options.

For example, use `python scripts/stream_desktop.py --fps 90` to target 90 fps.
These values set the stream rate, not the goggles' panel refresh rate. Lower
rates provide more bits per frame at the same bitrate, but increase the time
between frames. The 100 fps target has the shortest frame interval.

Windows encoding uses gradual refresh to reduce periodic compression blur. It
also sends a keyframe every three seconds, and more often in the first three,
so the goggles can start decoding at any point. To change the interval, use
`--keyframe-seconds`.
For details, see the [quality measurements and reproduction steps](docs/research/WINDOWS_QUALITY.md).

FFmpeg 9.0 and earlier capture a frame only when the screen changes. On a still
desktop, the bridge then reports only a few frames per second. Motion restores
the full rate.

## Run tests

Run the tests from the repository root:

```powershell
python -m unittest discover -s tests -v
```

See the [video-delay measurement guide](docs/LATENCY.md), [PC protocol](docs/PROTOCOL.md), and [reverse-engineering data and tools](docs/research/README.md).

## Contributing

See the [contribution guide](CONTRIBUTING.md) to report bugs, submit changes, or share protocol research.

## License

Copyright (C) 2026 Goggles Bridge contributors.

The original code and documentation are licensed under the [GNU General Public License v3.0 only](LICENSE) (`GPL-3.0-only`). Third-party materials retain their own licenses.
