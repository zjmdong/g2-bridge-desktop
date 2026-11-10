---
name: DJI Goggles Streamer
description: A calm native Windows workspace for connecting and streaming a desktop to DJI goggles.
colors:
  primary: "#146b64"
  primary-hover: "#0e5852"
  primary-disabled: "#d9e3de"
  primary-disabled-text: "#526b66"
  rail: "#153f46"
  rail-hover: "#24515a"
  rail-selected: "#32646a"
  rail-text: "#d4e4e3"
  rail-note: "#c4d9d9"
  workspace: "#f6f7f3"
  surface: "#ffffff"
  surface-border: "#d7e1de"
  readiness-surface: "#e9f1ed"
  readiness-border: "#ccded6"
  text: "#20363c"
  text-muted: "#526a70"
  heading: "#183c43"
  statistic: "#174f57"
  control-border: "#b9cac9"
  control-hover: "#edf4f1"
  control-hover-border: "#36706f"
  control-pressed: "#daeae4"
  control-disabled: "#edf0ec"
  control-disabled-text: "#7c898b"
  control-disabled-border: "#d7dfda"
  focus: "#257b7b"
  selection: "#d5eae2"
  selection-text: "#173e43"
  positive: "#126558"
  attention: "#815414"
  failure: "#a13c32"
  idle: "#203e44"
  progress-track: "#e6ece7"
  progress-fill: "#18786f"
  icon-line: "#f1f6ec"
  icon-accent: "#80cbb1"
typography:
  title:
    fontFamily: "Microsoft YaHei UI, Segoe UI"
    fontSize: "26px"
    fontWeight: 650
  section:
    fontFamily: "Microsoft YaHei UI, Segoe UI"
    fontSize: "16px"
    fontWeight: 600
  status:
    fontFamily: "Microsoft YaHei UI, Segoe UI"
    fontSize: "20px"
    fontWeight: 600
  statistic:
    fontFamily: "Microsoft YaHei UI, Segoe UI"
    fontSize: "21px"
    fontWeight: 600
  brand:
    fontFamily: "Microsoft YaHei UI, Segoe UI"
    fontSize: "20px"
    fontWeight: 650
  body:
    fontFamily: "Microsoft YaHei UI, Segoe UI"
    fontSize: "13px"
  navigation:
    fontFamily: "Microsoft YaHei UI, Segoe UI"
    fontSize: "14px"
  action:
    fontFamily: "Microsoft YaHei UI, Segoe UI"
    fontSize: "15px"
    fontWeight: 600
  label:
    fontFamily: "Microsoft YaHei UI, Segoe UI"
    fontSize: "12px"
rounded:
  progress: "4px"
  control: "6px"
  reader: "8px"
  panel: "10px"
spacing:
  control-gap: "8px"
  field-row: "9px"
  panel-gap: "12px"
  footer-block: "14px"
  nav-inline: "16px"
  section-gap: "18px"
  form-column: "20px"
  panel-inline: "22px"
  page-bottom: "24px"
  page-top: "26px"
  footer-inline: "28px"
  page-inline: "30px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    typography: "{typography.action}"
    rounded: "{rounded.control}"
    padding: "12px 28px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-primary-disabled:
    backgroundColor: "{colors.primary-disabled}"
    textColor: "{colors.primary-disabled-text}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  combobox:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "9px 12px"
  panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.panel}"
    padding: "18px 22px"
  readiness:
    backgroundColor: "{colors.readiness-surface}"
    rounded: "{rounded.panel}"
    padding: "18px 22px"
  navigation:
    backgroundColor: "{colors.rail}"
    textColor: "{colors.rail-text}"
    typography: "{typography.navigation}"
    rounded: "{rounded.control}"
    padding: "12px 16px"
  navigation-selected:
    backgroundColor: "{colors.rail-selected}"
    textColor: "{colors.surface}"
  footer:
    backgroundColor: "{colors.surface}"
    padding: "14px 28px"
---

# Design System: DJI Goggles Streamer

## Overview

**Creative North Star: "The Connection Field Guide"**

A calm connection workspace pairs a deep petrol navigation rail with warm white
working surfaces. The field-guide character comes from aligned information,
clear route markers, restrained color, and readable Chinese copy. Device
readiness leads to one useful action; status is evidence rather than decoration.

This documents the built Windows/PySide6 0.0.1 interface in Operate mode. The
visual language is an implementation decision made under the user's delegated
authority, not a claim that the user selected a brand identity. The direction
contract is `.impeccable/surfaces/desktop.md`; source values and behavior come
from `desktop_app/ui.py` and `desktop_app/assets/help.html`. The token frontmatter
is normative for new screens; native Qt behavior remains authoritative.

**Key Characteristics:**
- Deep petrol navigation and a quiet, light workspace.
- Native controls, Chinese-first copy, and visible keyboard focus.
- Flat bordered panels, aligned settings, and persistent transport actions.
- Evidence-backed status text with semantic title colors.

## Colors

The palette is cool and restrained, with warm white space and a teal action.
Token names below refer to the frontmatter rather than defining a second palette.
The sidecar includes synthesized eight-step OKLCH ramps for palette inspection;
these are design-panel previews, not additional colors implemented by the Qt UI.

### Primary

- **Working Teal** (`primary` / `primary-hover`) identifies the persistent next
  action. Its disabled pair clearly marks a temporarily unavailable operation.
- **Petrol Rail** (`rail`, `rail-hover`, `rail-selected`) anchors navigation;
  `rail-text` and `rail-note` provide its two text levels.
- **Focus Teal** (`focus`) draws the keyboard focus border. The softer selection
  pair is reserved for combo popup selection.

### Secondary

- **Verified Green** (`positive`) marks a ready or streaming status title.
- **Setup Amber** (`attention`) marks a check, preparation, or recoverable step.
- **Problem Red** (`failure`) marks a problem title. `idle` is the neutral status.
- `progress-fill` communicates measured or indeterminate driver preparation
  against `progress-track`. It is not a decorative accent.

### Neutral

- `workspace` sits behind white `surface` panels; `surface-border` separates them.
- `readiness-surface` and `readiness-border` distinguish the connection summary.
- `text`, `text-muted`, `heading`, and `statistic` establish information hierarchy.
- The control border, hover, pressed, and disabled tokens define native control
  states. Icon line and accent colors belong to the app's original identity mark.

**The Evidence Rule.** Change readiness copy only in response to real controller
results. The shipped three checkpoints use muted text; semantic color is applied
to the status title. Do not describe the checkpoints as colored indicators.

## Typography

**Display and body family:** Microsoft YaHei UI, with Segoe UI as the declared
fallback. No font is downloaded or bundled. Qt resolves the installed family and
native metrics; the help reader uses the same family with a sans-serif fallback.

This is the deliberate **native system typography exception for Operate mode**.
The field-guide character is expressed through hierarchy and spacing instead of
a decorative display family. Windows language support, familiar control metrics,
and native rendering take priority. Font substitution and DPI can change wraps.

The hierarchy is title, section, status/statistic, body, and small label. The
brand and navigation have dedicated roles; the primary action is slightly larger
and semibold. Exact roles are in the frontmatter. Body and label weight inherit
Qt's normal weight; no letter-spacing or fixed body line-height is imposed by the
main QSS. The embedded help document sets a 1.6 line-height, with local heading
sizes (19px and 15px). These reader details are not a new application-wide scale.

**The Native Legibility Rule.** Retain system font fallback and text wrapping;
never use display typography that makes device details or recovery steps harder
to read.

## Layout

The built window opens at 1120 × 800 logical pixels and has a 920 × 680 minimum.
These implemented dimensions supersede the provisional 1100 × 760 first-view
sketch. A fixed 200px navigation rail sits beside a flexible workspace. Each of
the three pages scrolls independently inside the workspace, above a persistent
footer. There is no responsive breakpoint or collapsed rail in 0.0.1.

Page margins are 30px horizontally, 26px at the top, and 24px at the bottom. The
page's section gap is 18px; panel insets are 22px horizontally and 18px vertically,
with 12px internal spacing. These are the built values, rather than a claim that
every gap follows the direction contract's provisional 24px rhythm.

The basic settings grid has two equally stretched columns, 20px between columns,
and 9px between rows. The statistic group has three equal columns. The footer
uses 28px horizontal and 14px vertical margins, with a wrapping notice taking
remaining width and a minimum 150px action button. Smaller windows retain this
structure and use vertical scrolling; lower panels need not fit above the fold.

## Elevation & Depth

The application is flat. Solid color, one-pixel panel borders, and tonal grouping
supply depth; no custom shadow, blur, gradient, or animated elevation is defined.
Qt/Windows may render native popup, menu, dialog, or focus details. Those platform
effects are not additional application tokens. State changes are immediate;
progress and periodic controller updates carry activity without ornamental motion.

## Shapes

Controls use softly rounded corners, panels a slightly larger radius, and the
help reader an intermediate radius. The frontmatter records their actual values.
Panels and most controls use a one-pixel border; focus uses a two-pixel teal
border. Checkbox indicators are native 17px squares. The slim vertical scrollbar
is 10px wide with a rounded handle; the progress bar is 8px high.

The app mark is original geometric artwork drawn by `app_icon()` in
`desktop_app/ui.py`: two outlined rounded lenses, a connecting bridge, and a mint
underline on a rounded petrol square. Its 128px QPainter raster supplies the
window/tray icon and the 48px rail rendering. `packaging/windows/prepare.py`
rasterizes the same function into `build/app.ico` for the two executables and
installer. It is project-authored geometry, not a downloaded DJI logo, icon
library, stock asset, or generated image. Preserve the independent-project notice.

`desktop_app/assets/chevron.svg` is also original project geometry: a 14 × 10 SVG
with `M2 3l5 5 5-5`, a two-pixel rounded stroke, and no fill. Qt displays it in a
26px dropdown area. It is the visible select affordance, including on the disabled
resolution field. No external license attribution or AI-generation provenance is
required for these original shapes. Review screenshots in `.impeccable/review/`
are local evidence, not shipping artwork; upstream research plots in
`docs/images/` are not assets of this desktop UI.

## Components

### Buttons and the persistent action

The primary button is a solid teal control with white semibold text. Secondary
buttons are white with a subtle border; hover changes both fill and border, and
pressed state uses a stronger tint. Buttons, combos, and checkboxes receive the
explicit focus border. Disabled states use muted text and low-contrast surfaces.
The source QSS defines no separate primary pressed override, so do not invent one.

The footer action follows this priority whenever no job is active:

| Condition | Label | Result |
| --- | --- | --- |
| Environment not yet checked | 检测运行环境 | Open device page and check environment. |
| USB driver not verified | 安装 USB 驱动 | Open device page and start verified driver preparation. |
| Encoder or OS unsupported | 查看编码帮助 | Open the capture-help anchor. |
| No detected device | 重新检测设备 | Open device page and probe again. |
| Firmware not allowed | 查看固件教程 | Open the firmware-help anchor. |
| All requirements met | 开始串流 | Save settings and start capture/device validation. |

A stream job changes the action to **停止串流**; stopping shows **正在停止…** and
disables it. Download/import jobs use **取消准备驱动**. An active driver installer
uses **正在安装驱动…** and disables the action. During other background jobs the
current next-action label remains visible but disabled. Do not duplicate a
competing primary action inside the readiness card.

### Settings and selectors

Combos remain native Qt controls with an explicit original chevron. The four
basic fields have visible labels, Qt label buddies, and explicit accessible names
matching those labels. Advanced capture/encoder fields use QFormLayout's labels;
they do not add explicit accessible-name overrides in the source. Keep accessible
names aligned with visible text when adding controls.

Resolution is a disabled, readable field showing only the SDK-verified 1080p
output and a tooltip explaining the constraint. Presets and target frame rate
update the allowable bitrate choices; manual bitrate or encoder-preset changes
mark the quality preset as custom. The advanced section is a checkable button
that reveals its fields in place. Stream settings are disabled while the stream
job owns capture and USB; navigation and help stay available.

### Navigation and panels

Three left-aligned, checkable navigation buttons switch between desktop stream,
device/driver, and help/diagnostics pages. Selected state has a stronger teal fill,
white text, and semibold weight. Status and content panels share geometry but
use different background/border pairs. All three readiness checkpoints remain
present as text; they are neither controls nor success badges.

### Statistics, help, and progress

Statistics show sending fps, USB send p95, and queue-wait p95, initially as dashes.
They are PC-side measurements updated by worker events, not end-to-end display
latency. The help reader scrolls to recovery anchors and opens external links.
Driver preparation uses a determinate download bar, then an indeterminate bar
while extracting verified files. Diagnostics stay local until the user exports.

### Evidence and known limits

The final finish review returned **ship** after corrections to select chevrons,
contextual primary-action labels, and basic-field accessible names. The supplied
`desktop-stream.png` and `compact-device.png` show the implemented light UI at
1120 × 800 and 920 × 680 respectively, in the missing-driver state. They establish
those layouts, not hardware compatibility, live USB performance, or every state.

This build has a Chinese UI, one light color scheme, a fixed minimum width, and
no narrow/mobile layout. Full screen-reader behavior, every Windows scale/font
combination, and hardware streaming are not established by the visual review.
The SDK output remains fixed at 1920 × 1080 from its default desktop source;
window selection and an independent extended desktop are future capabilities.
The sidecar's HTML/CSS samples are illustrative translations for the design panel,
not replacement web implementations or pixel-equivalence promises for native Qt.

## Do's and Don'ts

### Do:
- **Do** keep the footer action aligned with the next executable recovery or streaming step.
- **Do** preserve native keyboard operation, visible focus, label associations, and readable disabled values.
- **Do** keep status and metrics tied to controller evidence and explain their measurement limits.
- **Do** retain the original icon and chevron provenance when packaging or reusing them.
- **Do** verify additions at the minimum window size and allow page content to scroll above the persistent footer.

### Don't:
- **Don't** imply successful hardware checks through decorative success colors or fabricated values.
- **Don't** show unsupported resolutions, window capture, or an extended desktop as available choices.
- **Don't** introduce a decorative font, shadow system, or animated elevation into the native Operate interface without a new design decision.
- **Don't** replace informative disabled controls with unexplained empty areas or remove their labels.
- **Don't** present the original goggles mark as DJI branding or remove the independent-project notice.
