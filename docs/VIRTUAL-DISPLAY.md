# Virtual Display on Windows

Choose **Virtual Display** under Source to run a simulator on its own desktop.
In **Setup guide**, install the optional display driver, then connect the goggles,
open DJI Virtual Flight, and start streaming. Move the game with Win+Shift+Left/Right.
Stopping, disconnecting, or closing the app releases the virtual screen.

Desktop resolution can be 1280 × 720 or 1920 × 1080, at 60/75/90/100 Hz.
Both send a **1920 × 1080** picture. The personal NVIDIA build uses native Desktop
Duplication and GPU scaling to enlarge the 720p source before NVENC encoding,
filling the goggles' panel. Other configurations retain stock capture. The selected
rate is requested display timing, not a measured game or headset frame rate.
A physical primary monitor must remain active. Other encoding settings still apply.

The pinned Virtual Display Driver 25.7.23 is MIT-licensed and signed by SignPath
Foundation. Driver setup needs administrator approval. The GUI stays per-user;
the optional driver and its maintenance runtime live in Program Files and are
shared by all Windows users. Existing third-party VDD installations are not adopted.
New devices have random instance IDs; an older installation's sequential ID may
have been reused by another app. Uninstall that driver through its original app
or Windows uninstall entry before installing this version. Setup will not adopt
or automatically replace an older device whose creation identity is unverified.
An upgrade stops before replacing the old app so its removal action stays available.
The native driver installer embeds its payload; Python is never elevated from the
per-user app or source tree. Windows release signing is not configured by this PR.

Use **Setup guide** to repair a missing/damaged configuration or remove the driver.
Uninstalling the app also removes its driver component. Active streams, a required
restart, or another application's dependency on its configuration block removal
and retain the cleanup tools. After resolving the problem, retry removal. Only a
driver-store package added by this component and no longer used is deleted;
pre-existing shared packages remain under their original installer's control.
A standalone **Goggles Bridge Display** uninstall entry is also available in Windows.

Forced termination cannot run display cleanup. Restarting a virtual stream verifies
the exact owned device before using it again. Setup diagnostics are in
`Program Files/Goggles Bridge Display/display-install.json`.

Build this personal edition with `python packaging/build_windows.py --native` (PyInstaller and Inno Setup required).
Run `python -m unittest discover -s tests -v` and
`node --test tests/test_virtual_ui.mjs` for offline regressions. Before release,
check installation, repair, cancellation, uninstall/reinstall, and 720p/1080p
streaming on Windows hardware; attach the commit, device/firmware, logs and a short
headset recording to the PR. Automated tests do not establish optical performance.
