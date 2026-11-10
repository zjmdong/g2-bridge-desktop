# Windows implementation history

## 0.2.0 stream lifecycle and compatibility

The application adapter selects the DXGI adapter/output by display identity,
captures without WGC's yellow border, samples at 240 Hz and converts wall-clock
timestamps to the selected frame rate before RGB-to-NV12 conversion. It encodes
with libx264 and zero lookahead: optical A/B testing found grey-block corruption
in NVENC output despite neutral decoded source pixels. Keyframes at 0, 1 and 2
seconds bootstrap the goggles; periodic forced IDRs caused visible pulses, and
omitting the bootstrap produced a black display. Transport pacing absorbs short
scheduling bursts without dropping H.264 references. This adds up to 20 ms of
initial lead; it is not a claim of sub-20 ms end-to-end latency.

USB presence uses SetupAPI in a separate worker without claiming the device.
Probing has its own controller and never toggles the main task's busy state.
Manual stop suppresses automatic restart until the next insertion. Streaming
owns the virtual desktop through a finally-protected context; normal stop,
unplug and capture failures retract it. The GUI recovers after a killed worker.
The signed driver stays installed. A configuration update adds eight modes,
using the existing ownership and elevated-install boundary.

The USB writer publishes a constant-size counter snapshot. A separate thread
samples it every 100 ms; a bounded IPC writer coalesces statistics, so a stalled
GUI cannot block video. USB duration excludes pacing and is explicitly not
capture-to-eye latency. The unmodified SDK log still reports its original
settings; application capture_source/starting events describe the adapter.

## 0.1.1 reattachment fix

On the acceptance host, legacy ChangeDisplaySettingsEx rejected a detached IDD
with status -1, even though its enumerated 1080p60 mode was supported. Detached
attachment now uses QueryDisplayConfig and SetDisplayConfig. It preserves the
exact active paths and mode bytes, adds only the unique requested virtual target,
validates before applying and never sets SDC_ALLOW_CHANGES or a global extend
topology. Original paths are retained for rollback. Physical refresh rate joins
resolution, position and primary status in post-change verification. The video
adapter, USB protocol, driver binaries and settings schema are unchanged.

See VALIDATION-0.1.1.md for regression and installed-build checks.

## 0.1.0 extension

Add a Windows encoder-command adapter through SDK injection points, with
explicit desktop RGB-to-NV12 conversion, square pixels and recurring IDRs.
Resolve primary/virtual monitor handles at capture setup. Bundle a pinned,
signed MIT VDD package with a dedicated elevated driver operation; normal
display layout and streaming stay unprivileged. Protect existing VDD settings
and unrelated display drivers. Add source/setup controls and targeted tests.
See VALIDATION-0.1.0.md for hardware evidence and remaining acceptance items.

## 0.0.1 original implementation

Baseline SDK: a34690a58d48f0cd9b43cdeddf39b5efaf024b9c.

1. Freeze the SDK and add an independent desktop application package.
2. Add persistent settings, compatibility policy, device/environment probes,
   and a cancellable subprocess adapter using the SDK's public entry points.
3. Add a Chinese native Qt interface with a fixed desktop source, verified settings,
   device details, live statistics, driver setup and offline firmware help.
4. Bundle Python, Qt, PyUSB and a pinned FFmpeg; build a per-user Windows installer.
5. Verify offline behavior, lifecycle/error paths, GUI and installer launch,
   SDK integrity and packaging. Keep hardware checks explicitly separate.

## Release policy

Initial release: 0.0.1. Features/major changes: increment minor and reset patch.
Behavior-preserving fixes/tests: increment patch. CLI versioning is independent.

## Boundaries

Do not modify existing goggles_bridge/, scripts/, tools/research/ or tests/ files.
New tests live in desktop_tests/. Only desktop sources are exposed in this release.
The SDK defaults remain 1920x1080. The application adapter can output 720p;
its hardware acceptance evidence is tracked independently of the SDK baseline.
Third-party driver binaries are not committed or redistributed without permission.
An integrated official installer workflow replaces manual terminal setup.

## Original 0.0.1 validation record

Before development: 89 upstream tests, 87 passed, 1 failed (environment-dependent
GPU scheduling assertion), 1 macOS-only test skipped. No goggles hardware has
been exercised in this session.
