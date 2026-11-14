<!-- Local draft, not submitted. Suggested title: perf(capture): add bounded desktop duplication capture on windows -->
<!-- This describes the proposed native-backend scope, not every change on the fork's release branch. Prepare the focused branch and replace the validation placeholders before publishing. -->

## Changes

The Windows stream sender should not wait for GUI event handling or synchronous diagnostic storage, and capture should not accumulate stale raw frames under load. This change proposes an optional native DDA/NVENC path with bounded queues, explicit DXGI adapter/output selection, GPU NV12 conversion on NVIDIA-owned outputs, and capture-clock delivery deadlines.

The encoder and capture preflight use the same command policy. Encoded reference frames are not dropped to catch up. The existing USB packet/session protocol and frame-size guards are retained. Windows-specific integration stays outside the shared protocol modules, and existing CLI/macOS defaults remain unchanged.

The native FFmpeg changes include corresponding source, a pinned patch/build manifest, and independent timing/mailbox tests. This PR should not include the fork's installer branding, release version, update channel, or virtual-display driver management.

Compatibility choices and defaults: **replace this line with the exact options and default behavior of the focused PR branch**. Coordinate overlapping encoder experiments with #14 before finalizing this scope.

## Validation

- Exact branch/commit tested: **fill in after preparing this focused branch**.
- Offline regression command and result: **fill in**.
- Native build/hash and timing/mailbox checks: **fill in the results for this patch**.
- Existing CLI/macOS command-contract checks: **fill in; identify untested platforms**.
- Hardware A/B test: **record matched source, motion workload, resolution, fps, bitrate, preset, driver, headset firmware, duration, and results; or state not performed**.

Previous integrated-fork evidence is available in the [0.3.0 validation record](https://github.com/zjmdong/g2-bridge-desktop/blob/2c471821120f83569f4f8921f40fa628a8dbc621/docs/WINDOWS-0.3.0-VALIDATION.md): RTX 4060 Laptop, G2 01.14.00.00, short 1080p100/40 Mbps sender test. It is background evidence, not validation of a newly extracted PR branch. Sender counters and USB send time do not establish optical latency or headset frame pacing. No zero-jitter or universal no-drop guarantee is claimed.
