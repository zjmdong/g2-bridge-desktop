# Windows 0.0.1 implementation plan

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
Resolution remains at the SDK's verified 1920x1080 output. The resolution control
must describe this constraint instead of exposing unverified decoder modes.
Third-party driver binaries are not committed or redistributed without permission.
An integrated official installer workflow replaces manual terminal setup.

## Validation record

Before development: 89 upstream tests, 87 passed, 1 failed (environment-dependent
GPU scheduling assertion), 1 macOS-only test skipped. No goggles hardware has
been exercised in this session.
