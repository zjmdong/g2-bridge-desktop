<!-- Local draft, not submitted. Suggested title: feat(app): manage an owned virtual display during windows streams -->
<!-- Prepare the focused branch and replace validation placeholders before publishing. Use the upstream English label/copy agreed during review; the fork's requested Chinese source label need not become an upstream localization change. -->

## Changes

Windows users currently need a separate desktop if they want a simulator in the goggles without occupying their physical primary screen. This adds an optional virtual-display source to the existing app, with 720p/1080p modes at 60/75/90/100 Hz.

The stream worker leases a display managed by this app, applies the selected mode, resolves its current DXGI output, and releases the display on normal stop, disconnect, capture failure, or graceful shutdown. A session-local named Windows mutex prevents concurrent workers/maintenance from managing the same display. Failed activation rolls back; cleanup refuses an unexpected replacement, primary display, sole active display, or unrelated VDD configuration.

Physical-display settings and the author's existing advanced controls remain available. Switching source must not destroy those saved preferences. The UI additions reuse the existing rows, guide, and status presentation; macOS retains the upstream path.

Driver distribution/installation policy: **state the maintainer-approved scope here**. The fork currently uses a pinned signed MTT package and normal UAC. It does not modify certificate trust or test-signing policy. Keep fork-specific updater, version, and old-client migration changes out unless explicitly included in the agreed scope.

Dependencies on a native capture PR: **state whether this branch is independent, depends on an already merged commit, or remains a draft pending that change**.

## Validation

- Exact branch/commit tested: **fill in**.
- Offline lifecycle/ownership tests and results: **fill in**.
- UI scenarios: **fill in physical/virtual switching, saved settings, missing display, and driver setup failures**.
- Hardware activation/capture checks: **fill in Windows/GPU/driver, headset firmware, modes, duration, and cleanup result**.
- Untested environments and failure cases: **fill in explicitly**.

The integrated fork previously verified all eight virtual modes on Windows with an RTX 4060 Laptop GPU and the owned MTT 25.7.23 driver, and restored the physical layout after stream teardown. That evidence does not establish performance for every game, hybrid-GPU topology, or headset display. A forcibly terminated process cannot run Python `finally`; the subsequent owner must detect and recover the previously owned display.
