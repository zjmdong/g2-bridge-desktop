# Windows display path and driver integration

The upstream desktop app uses the same Windows capture/encode path for physical and virtual sources. The Windows helpers live under `goggles_bridge/app/windows`; importing them does not enumerate displays, open a USB device, install a driver, or start an encoder.

## Integration API

- `display_session.capture_target(settings, emit=None)`: context manager. Settings expose `source`, `dimensions=(width,height)`, `fps`, and optional `display_device`.
- `display_session.lease(source, width=1920, height=1080, fps=60, emit=None, *, display_device=None)`: equivalent explicit API.
- Sources: `display` selects the exact GDI display device name. An empty selection uses the active primary display; a named device disappearing is an error, never a silent primary fallback. `virtual` activates only this application's owned MTT display. `primary` and `extended` remain accepted compatibility aliases.
- Yielded inventory fields include `device/id/name`, `hmonitor`, `x/y/width/height/hz`, `active/primary`, hardware/monitor identities, and `refresh_rate` (rational numerator, denominator, Hz when Windows supplies one).
- `displays.capture_diagnostics(target, output)`: pure startup diagnostic; `output` is resolved through the DXGI helper. Reports the capture GPU/LUID, source refresh, and whether CPU transfer to NVIDIA is needed. It deliberately does not claim to know the game's render GPU.
- `virtual_driver.status()`: lightweight startup/settings query. Returns `installed`, `owned`, `config_current`, `needs_update`, `displays`, `gpu_preference`, and `supported`. It uses display inventory, registry and a small XML file; it does not start PowerShell/CIM or an encoder. Do not poll it on the frame/send thread.
- `virtual_driver.VirtualInstaller(remove=False)`: verifies the bundled driver and opens normal Windows UAC through the worker. Poll its `poll()` method; `None` means running, `0` success, `3010` success with a Windows reboot request.
- `virtual_driver.maintenance_main(argv)`: receives only the arguments after `--windows-maintenance`. The complete accepted argument lists are `['install-display-driver']` and `['remove-display-driver']`. Any extra/unknown argument returns 64. This dispatch must occur before GUI initialization.
- Worker invocation comes from `paths.worker_command()`: the packaged worker executable or development Python worker script, followed by `--windows-maintenance`. No arbitrary command/path is accepted by display maintenance.
- `system.driver_status()`: checks the installed DJI USB DLL against the SDK's verified SHA-256. This is not a substitute for checking actual device interface/driver binding when opening USB.

Events use `emit(event, **fields)`: `preparing_display`, `display_status`, `releasing_display`, and `display_cleanup_error`. These are outside the video path. Exceptions from observational shutdown callbacks cannot prevent actual display cleanup.

## Session ownership and teardown

Only 1280×720 and 1920×1080 at 60/75/90/100 Hz are advertised and selected. The requested mode must exist. CCD attachment preserves physical modes, signal timings, positions and the physical primary display. It does not use topology-wide Extend, AllowChanges or SetPrimary. A failed attach is rolled back before the lease is considered acquired.

A Windows session-local named mutex, `Local\\GogglesBridge.VirtualDisplay.Lease`, prevents two worker processes from managing the same virtual screen. Driver maintenance takes the same mutex. Acquisition is nonblocking: another owner yields an actionable error. A worker crash produces an abandoned mutex that a later worker can acquire and recover from. The mutex cannot coordinate old client builds that predate this integration.

After successful activation, target identity is recorded before callbacks or later source checks run. Normal stop, unplug, capture failure and Python exceptions execute teardown in `finally`. Cleanup only detaches the leased identity, refuses a replacement/ambiguous/primary/sole active display, and accepts an already removed monitor. A process forcibly terminated by Windows cannot execute Python cleanup; the next worker can recover the existing owned display. Graceful worker shutdown should allow setup/cleanup to complete.

The original ownership key `HKLM\\SOFTWARE\\G2Bridge\\DJIGogglesStreamerDisplay`, MTT `VDDPATH` and original installation directory are retained so 0.1/0.2 installations remain manageable. Ownership requires the expected driver hardware registration and owned configuration path. Existing foreign VDD installations, ambiguous monitors or another consumer of the shared MTT configuration are not overwritten. Removal keeps the signed driver-store package because another application may use it.

## GPU path: what is known and what is not

MTT 25.7.23's `default` preference does **not** mean integrated GPU. It reads an optional adapter.txt override, otherwise chooses the GPU with most dedicated video memory. It requests that adapter with IddCxAdapterSetRenderAdapter. Windows can choose a different render adapter; the actual LUID arrives in the driver swapchain callback. An explicit XML GPU preference is preserved when this app updates display modes.

The current NVIDIA capture route keeps capture, conversion and NVENC on GPU. A non-NVIDIA capture output needs an explicit GPU→system-memory→NVIDIA transfer, which the diagnostic flags. Capture adapter identity does not prove which GPU a game uses, and DXGI adapter indices are not CUDA device indices.

Source findings:

- [Pinned MTT adapter selection](https://github.com/VirtualDrivers/Virtual-Display-Driver/blob/d437ebc9b44a14ce6e5cc9c8b7f6beb08d6faf77/Common/Include/AdapterOption.h#L57).
- [Microsoft preferred versus actual IDD render adapter](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/iddcx/nf-iddcx-iddcxadaptersetrenderadapter).
- [Sunshine hybrid-output reparenting handling](https://github.com/SunshineStream/Sunshine/blob/657f9b68bf0b2d34adf585b620775d19bb40d8a4/src/platform/windows/display_base.cpp#L449).
- [IDD metadata semantics](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/iddcx/ns-iddcx-iddcx_metadata): presentation QPC describes when a surface should be displayed; static desktops can stop producing new updates. It does not measure goggles display latency.

The MTT loop's 16 ms wait is an event timeout, not a fixed 16 ms sleep per frame. New surfaces wake it immediately. Higher bitrate can preserve motion detail but cannot create source frames that the game/DWM never produced.

## What Foundation Sunshine contributes

The qiin2333 fork is now [AlkaidLab/foundation-sunshine](https://github.com/AlkaidLab/foundation-sunshine). Its paired ZakoVDD exposes a dedicated shared-texture channel. The driver performs one GPU copy into a three-slot mailbox; the host can borrow the latest complete texture, with strict GPU-LUID matching and bounded ownership. Unread old frames can be replaced. Consumer-held slots can cause producer drops, and the host temporarily falls back to another GPU copy when borrowing hurts throughput.

This direct producer channel could avoid DDA recapture, but requires a new driver/capture backend, versioned IPC, texture lifetime synchronization and validated driver packaging. It is not enabled by changing MTT XML. This integration retains the pinned MTT package and does not change certificate stores, signature enforcement or test-signing policy.

- [Zako producer mailbox](https://github.com/qiin2333/zako-vdd/blob/abadb3ae0a802694f6095893df4c8826a5b9d0e0/ZakoVDD/Rendering/SharedFrameExporter.cpp#L330).
- [Foundation borrowed-frame limits/fallback](https://github.com/AlkaidLab/foundation-sunshine/blob/02bca1aa30cc3530d8ecea33878d2cd9ace0feae/src/platform/windows/display_vdd_vram.cpp#L354).
- [Sealed channel ABI and validation](https://github.com/AlkaidLab/foundation-sunshine/blob/02bca1aa30cc3530d8ecea33878d2cd9ace0feae/docs/windows_vdd_sealed_frame_channel.md).
- [Moonlight bounded receiver pacing](https://github.com/moonlight-stream/moonlight-qt/blob/29f121a7d33dacf200fa14840685a3f4534a1f10/app/streaming/video/ffmpeg-renderers/pacer/pacer.cpp#L232). Receiver VSync-based smoothing cannot be transplanted into a USB sender without control of the closed goggles receiver.

## DJI USB installation

DJI's proprietary installer is downloaded on demand from the pinned official CDN, not redistributed:

1. `drivers.download_assistant(stop, emit)` downloads the pinned DJI Assistant 2 Consumer 2.1.42 package to the app's cache. Redirects must remain HTTPS on dl.djicdn.com; size is bounded; SHA-256 and Windows Authenticode are checked.
2. `drivers.prepare_driver(installer, stop, emit)` uses the bundled innoextract helper to extract only the verified 5.0.0.7 USB driver and its license. Every required driver file has a pinned SHA-256.
3. `drivers.InstallerProcess(inf)` asks Windows to install that verified INF with PnPUtil. The user confirms the system UAC prompt. Poll completion and re-check USB readiness afterward.
4. For manual setup or download problems, use [DJI's official Assistant page](https://www.dji.com/downloads/softwares/dji-assistant-2-consumer-drones-series). A different/newer package is not silently accepted as the verified one.

No firmware is flashed by these helpers. Firmware compatibility checks and the Virtual Flight tutorial stay in the app's device/help flow.

## Validation scope

The display/driver unit tests mock every operating-system mutation, installer launch and download. They cover all eight modes, preservation of primary display timings, failed-attach rollback, teardown after callback/stream failure, cross-process mutex contention/abandonment, stale target protection, legacy ownership, foreign-installation refusal, fixed maintenance arguments and driver integrity checks. They do not establish physical goggles latency or game performance.
