# Generated-picture cadence checks

These optional Windows research tools measure **which generated source pictures
arrive**, not just whether an encoder outputs about 100 access units per second.
They are not imported by the desktop application. No tool here installs a driver,
changes a display mode, or starts a source renderer automatically. The identity
probe has no USB path; the separate USB timing helper requires explicit `--run`.

Run them manually with an explicit source/output selection and a new report path.
The caller must first supply the matching synthetic renderer, leave it visible on
the selected output, and keep it running beyond the complete capture interval.
Do not run a capture over ordinary private desktop content. Stop the installed
streamer and other GPU tests before measuring; never compile during a timed run.

## Fixture geometry and meaning

The two C++ source fixtures deliberately preserve the measured geometry rather
than silently adapting to another desktop layout. They refuse a mismatched output:

| Fixture | Required existing display | Duration | Encoded barcode crop |
| --- | --- | --- | --- |
| `renderer-extended-latency2.cpp` | Nonprimary 1920×1080 at (3440, 0), nominal 100 Hz | 5–600 s | `512:48:16:8` |
| `renderer-primary-latency2.cpp` | Primary 3440×1440 at (0, 0), nominal 100 Hz | 5–30 s | `512:48:16:146` |

Both show without activation and support close/Escape/Ctrl+C or their duration
limit. A physical or virtual output's configured 100 Hz is **not evidence of 100
unique source pictures**. Their own QPC and presentation logs establish the
actual source cadence. Present return is not physical display completion.

Both published fixtures are temporarily topmost, without activation, so ordinary
application windows cannot cover its generated picture or identity barcode. Its
window is destroyed on exit, removing that topmost state; Escape and the maximum
duration remain available (30 seconds primary, 600 seconds extended). Keep both
sources unobscured: a valid barcode alone does not
establish that the rest of the source picture remained visible. Earlier primary
runs using ordinary `HWND_TOP` are not acceptance evidence when occlusion cannot
be excluded. Failed marker validation always invalidates the identity result.

The fixtures use three swapchain buffers and MaximumFrameLatency 2 to avoid the
observed source starvation with a one-frame source queue. This is a **test fixture
choice**, not a new buffer in the streamer. It can increase source render-to-DWM
age, which the identity measurement includes. Do not compare its source-render
age directly against an earlier fixture with different swapchain settings.

The primary fixture transforms its marker coordinates for the production aspect
fit: 3440×1440 becomes 1920×802, with an even-aligned top margin of 138. Its
original marker location (16, 8) consequently appears at encoded (16, 146).
The 32-bit frame ID and 64-bit render-start QPC occupy three rows of 16-pixel cells.

## Compile only, then explicitly launch the chosen source

Use the pinned MSYS2 UCRT64 GCC toolchain from the native build instructions, or
pass `--compiler`. These commands compile only and do not open a window:

```powershell
.venv/Scripts/python.exe packaging/windows/frame_cadence/build_renderer.py --source extended --output work/cadence-source/extended.exe
.venv/Scripts/python.exe packaging/windows/frame_cadence/build_renderer.py --source primary --output work/cadence-source/primary.exe
```

Choose new paths and create the log directory before launching. For example,
with the required extended display already active and an absolute new JSON path:

```powershell
.venv/Scripts/python.exe -c "from pathlib import Path; import subprocess; info=subprocess.STARTUPINFO(); info.dwFlags|=subprocess.STARTF_USESHOWWINDOW; info.wShowWindow=1; subprocess.Popen([str(Path('work/cadence-source/extended.exe').resolve()), '--mode', 'texture', '--seconds', '90', '--output', str(Path('work/cadence-source/extended-renderer.json').resolve())], creationflags=subprocess.CREATE_NO_WINDOW, startupinfo=info)"
```

`CREATE_NO_WINDOW` suppresses the console; explicit `STARTF_USESHOWWINDOW` with
`wShowWindow=1` (`SW_SHOWNORMAL`) prevents an inherited hidden startup state from
hiding the synthetic source. `CREATE_NO_WINDOW` alone was insufficient when the
parent already had hidden startup settings. Running the executable normally is
also supported. Do
not launch a renderer with PowerShell `Start-Process -WindowStyle Hidden`: the
resulting hidden-window startup state interfered with the primary fixture's
visibility/topmost behavior in the recorded investigation. Confirm that the
source window is visible and unobscured; for either fixture, verify its
`WS_EX_TOPMOST` style and that marker-point hit testing resolves to the owned
source window before timing. Then run a short identity preflight. A request to make a window foreground can
be refused by Windows, and neither a request nor a successful launch proves
foreground status. Source visibility and marker validation are still required.
Earlier occluded runs are excluded from acceptance evidence.

Inspect the actual DXGI adapter/output inventory;
output 1 below is an example, not a persistent monitor identity. For a primary
capture, explicitly launch the primary fixture for 30 seconds, wait until it is
ready, use `--primary --output-index 0 --seconds 20`, and confirm the inventory
matches. The primary fixture's 30-second ceiling must cover the entire capture.

## Measure the actual release binary

The probe calls the current desktop command adapter and asserts the frozen
1080p100 / 20 Mbps policy: NVIDIA NVENC High/CABAC, Cb/Cr offsets -4, qres, no
B frames and no lookahead. `--preset p1|p4` selects the hardware preset. The actual
command, its hash, adapter source hash and executable hash are saved in the report.
Native filter capabilities and offline crop availability are checked before timing.

```powershell
.venv/Scripts/python.exe packaging/windows/frame_cadence/production_identity.py --ffmpeg vendor/ffmpeg/ffmpeg.exe --output-index 1 --seconds 60 --warmup 3 --preset p4 --fresh-wait-us 2000 --delivery-delay-us 8000 --output work/cadence-candidate.json
```

For a disabled-option reference, explicitly select
`--fresh-wait-us 0 --delivery-delay-us 0`. Zero omits the optional native flags, allowing an older
reference binary without those options. A nonzero request fails before capture
when the binary lacks the corresponding DDA capability. Use the intended pinned
reference executable with `--ffmpeg`; never assume the current vendor executable
still represents an older version.

While capture runs, the probe retains only complete encoded AUs, their arrival
QPC and bounded diagnostic stderr **in RAM**. It writes no per-frame disk log,
performs no live image decode/readback and has no USB path. Limits are 60 seconds,
6,500 AUs and 256 MiB of encoded data. After the owned encoder gracefully stops
and drains, a single-threaded CPU H.264 decoder extracts the marker. CPU decoding
here is research verification, not software encoding or a product fallback.

All frames, including startup and drain, are validated for decoder errors, exact
counts, marker confidence, monotonic identity/QPC and causal timestamps. Warmup
and drain are excluded only from the measurement summary. Video, screenshots and
decoded pixels are not saved; only numeric JSON and the completed encoder log
are written. Local raw reports contain paths and device metadata; review/redact
them before publishing. The probe never invents native capture timestamps: its
age is **source render-start to host AU arrival**, not capture-to-photon latency.

## Compact comparisons and exact renderer correlation

After the renderer exits and writes its log:

```powershell
.venv/Scripts/python.exe packaging/windows/frame_cadence/summarize_identity.py --renderer work/cadence-source/extended-renderer.json --runs work/cadence-reference.json work/cadence-candidate.json --output work/cadence-comparison.json
```

The summarizer also accepts earlier instrumented `check_frame_age.py` reports.
Without `--renderer` it produces compact identity/arrival summaries. With it,
every decoded `(frame ID, render QPC)` tuple is matched to an actual source row,
including drain, and the source's own gaps are reported separately. Source IDs
generated but absent from encoded output may have been lost during composition,
capture readiness or encoding admission; they are not automatically capture drops.
Sampled DXGI presentation statistics narrow this uncertainty but do not prove
optical display or isolate every missing picture.

## Optional actual USB host timing

`measure_usb_host.py` uses the current production command and complete
`VerifiedTransport.write` calls at 1080p100 / 20 Mbps / NVENC P4, including the
current native delivery policy. It does not apply historical experiment wrappers
or override production pacing. It measures host write completion, **not goggles
decode, scanout, or optical latency**, and does not decode source identity.

By default it only validates arguments. Choose an already active output and a new
report path explicitly. Add `--run` only when the goggles are connected and in
DJI Virtual Flight, and the installed streamer is stopped:

```powershell
.venv/Scripts/python.exe packaging/windows/frame_cadence/measure_usb_host.py --source 1 --duration 20 --output work/usb-host-check.json
.venv/Scripts/python.exe packaging/windows/frame_cadence/measure_usb_host.py --source 1 --duration 20 --output work/usb-host-check.json --run
```

This helper opens the real DJI USB transport only with `--run`. It does not
create, enable, disable, remove or reconfigure a display. Use the manually
started synthetic source for comparable measurements. Per-write timing and SDK
events stay in bounded, preallocated RAM until streaming and cleanup finish;
the completed numeric report is then written. The ordinary production encoder's
warning-only stderr may use a temporary log. No screen video is saved. Results
separate whole-frame wire duration from one-second encoded-payload estimates;
neither constant average bandwidth nor successful USB writes prove smooth
optical display.

## Separate complete-AU arrival from USB writes

`instrument_usb.py` optionally wraps the unchanged USB helper. It records when
the existing AVI parser returns a complete encoded access unit (AU), then compares
that time with the SDK's video-write begin and completion times. This distinguishes
an AU that reaches Python late from a delay after arrival. AU arrival includes
native pipe, reader and parsing time; it is **not a native encoder-completion
timestamp**. AUs returned in the same parser call share one timestamp.

```powershell
.venv/Scripts/python.exe packaging/windows/frame_cadence/instrument_usb.py --source 1 --duration 60 --output work/usb-arrival-check.json
.venv/Scripts/python.exe packaging/windows/frame_cadence/instrument_usb.py --source 1 --duration 60 --output work/usb-arrival-check.json --run
```

It requires a new output path and writes a companion `-host.json` report. Live
sampling uses preallocated arrays with capacity 20,000 AUs, one clock query per
nonempty parser batch, no sleeps, no new queue and no per-frame file I/O. Alignment
requires one parser, no restart/oversize/overflow, exact sequential payload lengths
and causal timestamps. It never searches forward by size to hide mismatches.
Only a chronological unwritten shutdown tail is permitted. Equal packet lengths
alone do not establish frame identity; the reported matching policy also depends
on the unchanged SDK's ordered send path.

With the extended synthetic fixture already visible and running for the entire
measurement, `--decode-synthetic-extended` additionally retains the existing AU
byte objects in bounded RAM (6,500 AUs, 256 MiB) and decodes marker identity **after**
streaming stops successfully with confirmed cleanup. A nonzero run result,
incomplete stop, recorded failure, or cleanup error suppresses offline decoding
and preserves a failed exit status. It refuses an inactive, primary, or
non-1920×1080/100 Hz output;
the caller must still ensure the source contains only the synthetic fixture.
It does not save video or decoded pixels and does not change a display mode.
The default invocation does not retain encoded frames or open USB. Raw JSON
contains local diagnostic paths and numeric per-frame records; publish only
reviewed aggregates. Research native binaries that print extra mux snapshots
must be identified separately from clean release binaries.

## CPU-only checks and provenance

```powershell
.venv/Scripts/python.exe packaging/windows/frame_cadence/test_frame_cadence.py
.venv/Scripts/python.exe packaging/windows/frame_cadence/test_instrument_usb.py
```

These Windows tests use small generated arrays and mocked subprocesses. They
never launch FFmpeg, compile a renderer, open a GPU, capture a display or use USB.

`provenance.json` records original research and published source hashes separately.
The production probe and USB helpers' repository-root lookups change during
migration. The arrival helper also removes ignored-only wording and requires
confirmed successful cleanup before offline decoding; its historical research
copy did not enforce that additional guard. The marker helper and summarizer are
byte-identical copies. Both published fixtures additionally change `HWND_TOP` to
`HWND_TOPMOST` as described above. Its new source hash identifies only subsequent
measurements; historical runs retain their original source and executable hashes.
For the final clean-release USB investigation, the existing extended renderer
binary was not rebuilt: a controller selected its window by owning PID and
class and applied the same temporary topmost state without activation. A short
preflight verified generated markers before the full USB run; full-run marker
validation is still required. Earlier runs interrupted during offline decoding
or containing invalid/occluded markers are excluded from dynamic acceptance,
even when their USB writes completed successfully.
Historical measurements identify their original source hashes. They must not be
described as executions of the migrated probe. The new build helper and CPU tests
are publication additions. No fixture was rebuilt or GPU measurement repeated
as part of this source publication.
