# G2 Bridge

Stream your Windows or Mac desktop to DJI Goggles 2 or DJI Goggles Integra over USB. The goggles use Virtual Flight mode with stock firmware. The simulator and controller run on the computer.

## DJI Goggles Streamer desktop client

This fork adds **DJI Goggles Streamer 0.2.4**, a Windows x64 graphical client.
It wraps the SDK with environment and firmware checks, integrated
driver setup, streaming controls, persistent settings and offline help.
It offers borderless primary/virtual desktop capture at 720p or 1080p, four frame
rates up to 100 fps, automatic USB streaming/display lifecycle and sender metrics.
The desktop adapter uses NVIDIA NVENC H.264 exclusively, without a software
fallback; the SDK's original encoder defaults remain unchanged. Window selection and a
macOS GUI are planned.
Version 0.2.4 retains one target-rate QPC capture clock, GPU BT.709 NV12 conversion
with correct letterboxing, asynchronous NVENC completion events, and a single
waiting raw-frame slot. Under overload, newer raw pictures replace waiting ones;
encoded H.264 references remain ordered. It does not promise zero drops, fixed
optical latency, or latency/bitrate variation within 1%. Primary and virtual
displays use the same pipeline, with their actual source refresh rates still
limiting how many distinct pictures they can supply. The default target remains
1080p100/20 Mbps/P4, with the SDK's qres rate control and VBV/frame-size guards.

The desktop enables source-phase alignment (`source_clock=1`,
`source_guard_us=3000`): consistent real desktop updates steer future capture
deadlines by at most 100 microseconds per correction. The 3 ms phase target
does not add an encoded-frame buffer or adaptive bitrate reduction. Native
FFmpeg keeps this option off by default; it does not synchronize to the
headset's unreported display clock.

The desktop client requests High GPU scheduling class 4 for its encoder instead
of Realtime class 5. The SDK exposes this as an optional per-engine policy;
its command-line default remains class 5. The request is best-effort and records
both the requested class and whether Windows accepted it.

Of the 70 recorded SDK files, 68 remain unchanged. Two exact audited patches
cover the engine's optional GPU scheduling hook and a test that incorrectly
required successful GPU scheduling without creating a D3D context. The engine
is the only changed runtime SDK file. Original baseline hashes are preserved,
and packaging verifies both exact patched hashes through
[sdk-patches.json](docs/desktop/sdk-patches.json). Native capture/encoder changes live
in a bundled minimal LGPL FFmpeg n9.0.2 build; its complete upstream source,
patch, build recipe, dependency manifest and notices accompany the installer
and source archive. Follow the [native build instructions](packaging/windows/ffmpeg/README.md)
before running the desktop packaging preparation step.

See the [Windows user and build guide](docs/desktop/USER_GUIDE.md),
[current implementation notes](docs/desktop/IMPLEMENTATION.md),
[0.2.4 validation record](docs/desktop/VALIDATION-0.2.4.md),
[VR timing design and sources](docs/desktop/VR_TIMING.md),
[protocol and performance limits](docs/desktop/PROTOCOL_LIMITS.md) and
[third-party notices](docs/desktop/THIRD_PARTY.md). The command-line SDK described
below retains its existing defaults. Upstream latency measurements below describe
the SDK's original hardware tests, not a new measurement of the desktop client.

The bridge detects the model when it connects:

| Goggles | Identity | Tested firmware |
| --- | --- | --- |
| DJI Goggles 2 | `E3T ZV900` | 01.11.00.00, 01.14.00.00 |
| DJI Goggles Integra | `E3T ZV901` | 01.09.00.00 |

We measured **about 12 ms median monitor-to-lens delay** at 1080p100. See [how we measured it](docs/LATENCY.md).

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

## Start streaming

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

Windows encoding uses gradual refresh to reduce periodic compression blur.
For details, see the [quality measurements and reproduction steps](docs/research/WINDOWS_QUALITY.md).

## Run tests

Run the tests from the repository root:

```powershell
python -m unittest discover -s tests -v
```

See the [video-delay measurement guide](docs/LATENCY.md), [PC protocol](docs/PROTOCOL.md), and [reverse-engineering data and tools](docs/research/README.md).

## Contributing

See the [contribution guide](CONTRIBUTING.md) to report bugs, submit changes, or share protocol research.

## License

Copyright (C) 2026 G2 Bridge contributors.

The original code and documentation are licensed under the [GNU General Public License v3.0 only](LICENSE) (`GPL-3.0-only`). Third-party materials retain their own licenses.
