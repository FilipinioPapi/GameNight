# Handoff: smooth, console-like controller movement

Read `docs/STATUS.md` first. Approved by Jayden 2026-10-31 from the demo
https://claude.ai/artifact/NorZSydMr8mSb5TinLbsMY ("Now" vs "Smooth").

## What changed
- `app/src/lib/focusring.ts` (new): one glowing frame that glides to whatever the controller highlights
  (eases in about a sixth of a second), and gentle scrolling that keeps the highlighted thing in view with
  some of the next row showing. Shows only in pad mode. A small "bump" when there's nowhere to go.
  Respects Windows' "reduce animations" setting (snaps instead).
- `app/src/lib/gamepad.ts`, `moveFocus`: rows and columns instead of "nearest thing that way".
  Left / right stay in the same row of the same list (end of a row = bump, never a jump to a console tab).
  Up / down go to the next row and keep your column. Up into the console tabs lands on the console showing.
  Left / right can still cross to a list beside you (a settings page's side menu).
  Moving along console tabs shows that console straight away, and the games slide in from that side.
  LB / RB from the games keeps you in the games (first game of the new console).
  Highlighting never makes the page jump (`focus({ preventScroll: true })`).
  Holding a direction: 0.34 s pause, then repeats that speed up a little (140 ms down to 85 ms).
  Left stick has to come back near the middle (under 0.45) before it counts again.
  Each move is written to pads.txt ("menus: move down: ... -> ...") for checking on Windows.
- `app/src-tauri/src/pads.rs`: each controller reading carries a number (`seq`). The menus ignore an
  older reading that arrives late (the "pad" event and the every-frame answer travel separately).
  Strongly inferred risk (a press counting twice), not measured on Jayden's PC; pads.txt notes when it happens.
- `app/src/app.css`: the frame's look (same gold glow as the Library, gentle pulse), the highlighted
  thing lifts a little, and each thing's own static highlight steps aside while the frame shows.
- `app/src/App.svelte`: screens fade in (0.2 s) instead of cutting.
- Main menu: PLAY now reads LIBRARY.

## Checked (Confirmed)
- `npm run check`, `npm run build`: no errors.
- Pretend controller in Chromium on the main menu, Library (all tabs) and Settings: moves as above,
  scroll eases over about 0.25 s, held direction repeats, stick wobble around the edge counts once.

## Not checked yet (Unknown)
- On Windows with a pretend Xbox pad: needs the cloud controller test from PR #9 (not on this branch).
- On Jayden's PC with his real pad.
