# Windows 0.1.1 validation

## Change and reproduced failure

0.1.0 primary and independent extended-screen output were both optically confirmed
by the user on 2026-11-10 (Goggles 2 01.14.0000, RTX 4060 Laptop, 3440×1440
primary). See VALIDATION-0.1.0.md for the actual observations and USB statistics.
During the follow-up disconnect/re-enable check, legacy ChangeDisplaySettingsEx
returned -1 for the detached virtual display, including its enumerated 1080p60
mode. Merely adding CDS_UPDATEREGISTRY did not consistently resolve the failure.

The patch uses explicit CCD paths for detached attachment, preserving all active
paths and mode data. It validates the exact configuration without allowing Windows
to change supplied modes, and retains a snapshot for rollback. Only the owned
virtual display is disconnected; other inactive displays are never enabled.
See Microsoft's [SetDisplayConfig API](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setdisplayconfig)
and [QueryDisplayConfig API](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-querydisplayconfig).

## Verification

- Three actual detach/reattach cycles passed with the patched source. Each restored
  1920×1080 / 60 Hz at (3440, 0), using a fresh monitor handle; the primary stayed
  3440×1440 / 60 Hz at (0, 0) and remained primary and active.
- 34 desktop tests passed, including detached-source routing, exact preservation
  of active paths and opaque target timings, exclusion of unrelated inactive
  displays, no apply after validation failure, rollback after apply failure and
  rollback when the primary refresh rate changes.
- The SDK's 70 protected files remain unchanged. The video compatibility adapter,
  encoder settings, USB framing and signed display-driver package are unchanged.

- Packaged-worker environment smoke passed with bundled FFmpeg, NVENC and the
  verified DJI USB driver. The 0.1.0 -> 0.1.1 installer upgrade returned code 0,
  required no restart and preserved settings byte-for-byte. Both installed EXE
  version fields report 0.1.1. The existing VDD installation was reused.
- The installed 0.1.1 GUI then disconnected and re-enabled the display successfully.
  It gated streaming while disconnected and restored the start action after
  reattachment. The virtual monitor received a new HMONITOR and the physical
  primary remained unchanged. Pre-existing non-VDD adapter and monitor identity,
  active and primary states matched the inventory taken before driver installation.

Driver removal, forced rollback on real hardware, actual simulator performance
and other GPU models remain outside this acceptance run. Unit-test rollback
coverage is not a claim that a hardware failure was induced.
