<!-- Local proposal only. Review the current upstream discussions and edit the scope before publishing. Suggested title: feat(windows): discuss native capture and virtual display contributions -->

I have been extending a fork of Goggles Bridge for Windows FPV simulator use. I would like to contribute focused improvements while retaining the upstream desktop interface and existing advanced settings.

The main use case is a separate 720p/1080p virtual desktop at 60/75/90/100 Hz, so the simulator can run in the goggles while the physical screen remains available. The fork also has a native DDA/NVENC backend and bounded background logging/UI events. USB framing and the headset session protocol remain based on the upstream implementation.

Before proposing a large patch, would you be interested in reviewing these separately?

1. Small, independently useful app/backend fixes or optional interfaces, with regression tests.
2. An optional Windows native capture backend with corresponding source, reproducible build instructions, and explicit compatibility boundaries.
3. An owned virtual-display lifecycle that creates the selected mode for a stream and releases it on stop/disconnect/failure, without replacing unrelated VDD configurations or altering the physical primary display.

The virtual display currently uses a pinned signed MTT driver. It does not change certificate trust, test-signing policy, or flash headset firmware. Any upstream packaging policy for third-party drivers should be agreed before proposing installer changes. Fork-specific versioning and update-channel changes can remain outside these PRs.

I saw the existing decoder-buffer/keyframe experiments in #14 and Windows encoder work in #26. I would like to avoid duplicating those efforts or changing your capture/encoder defaults without agreement.

Hardware checks on the integrated fork used Windows, an RTX 4060 Laptop GPU, and Goggles 2 firmware 01.14.00.00. Eight virtual modes passed capture/encoding preflights and the original display layout was restored. A short 1080p100/40 Mbps USB stream ran successfully at the sender. These checks do not measure optical latency, headset display cadence, or FPV game performance; I am not claiming zero jitter or a better monitor-to-lens result than upstream.

Would you prefer starting with a small backend change or with the virtual-display lifecycle, and are there constraints you want the contribution to follow?
