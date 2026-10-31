# Handoff: Library screen

Read `docs/STATUS.md` first. This file is the detail for the Library (the "Play" screen).

## What it is (built 2026-10-29, branch `claude/project-thread-yyq3jl`)
Built from Jayden's approved mockups (Design canvas "Game Night favourites and button guide",
https://claude.ai/artifact/GFMzHHexe5DtY1hH7oFxhs, boards Main, PlayStation, MouseKeyboard, LayoutSetting).

- `app/src/screens/Library.svelte`: both layouts.
  - Controller layout (default): "LIBRARY" title, console tab bar on top (LB / RB), Favourites first tab
    (3 recently played on top, then all favourites), bottom button guide.
  - Mouse and keyboard layout: consoles in a list on the left, hover a game for Open and the star,
    Play buttons on recently played, keys bar (Arrows, Enter, F, Ctrl+F, Q / E, Esc).
- `app/src/components/ButtonGuide.svelte`: the bottom bar. Uses the pixel prompts in `app/public/prompts/`
  (Xbox or PlayStation, following the pad in use), drawn at 2x with sharp pixels.
- `app/public/consoles/`: Jayden's 13 console tab pictures, copied unchanged from project files
  `gamenight/console-tab-assets/` (480x272, shown whole in an 88x50 box). Never crop, recolour or redraw.
- `app/public/prompts/`: the Xbox / PlayStation button prompts, copied unchanged from project files
  `gamenight/button-prompts/` (originally from Roof Rage with Jayden's OK, 2026-10-29).
- Settings › Layout: pick the layout, or "Switch layout automatically" (follows the last thing you touched).
- Saved on this PC only (`settings.ts`): `favourites`, `recent` (with minutes played), `layout`, `autoLayout`.
  `play.svelte.ts` records a game in Recently played when it starts and its minutes when it closes.

## Retro glow style (approved by Jayden 2026-10-31)
The controller layout follows the "Play: retro glow style (new)" board: banded red background with a
checkerboard blend where bands meet (`.dither` layers), VT323 lettering (bundled `@fontsource/vt323`) for the
count, section labels, search box and button guide, and slow pulsing glows on the selected tab and the
highlighted game (no pulse when Windows animations are turned off). No full CRT filter.
The mouse and keyboard layout keeps the plain look (no mockup for it in this style yet).

## Box art in its real shape (approved by Jayden 2026-10-31, thread "Clean up the Library screen box art")
Jayden asked for every cover to fit properly per console and per box style, like RomM, never cropped or
squeezed into a box it wasn't made for. Mockups: boards LB0-LB7 on the Design canvas
https://claude.ai/artifact/KRmdN4XWGPiuvMzSGns2ko ("big improvement", 2026-10-31).
- Measured (Confirmed) from 181 of his RomM covers, width / height: NES and arcade 0.73, Genesis, GameCube
  and PS2 0.71, GB/GBC and GBA 1.0, PS1 1.165 (jewel case with spine), SNES and N64 1.37. Wii: none saved
  yet (Unknown, assumed 0.71). A few region covers differ (e.g. a Super Famicom box in the SNES list).
  Kept in `BOX_SHAPE` (`app/src/lib/consoles.ts`); details in project files `gamenight/library-boxart/`.
- A console's own tab: neat columns in that console's box shape. Every console's boxes cover about the same
  area (`boxHeight()` in `boxart.svelte.ts`), so wide SNES boxes look as big as tall NES ones. A cover of
  another shape sits whole inside its column, on the same floor.
- Lists that mix consoles (Favourites, All games, search): justified rows. Every cover in a row is the same
  height and keeps its own width, and the row stretches to fill the screen (the last row keeps its size).
- Nothing is drawn on the art: the name (8-bit font), console / players / size chips, the favourite star and
  "ON PC" sit underneath. The download bar is the only thing on a cover. Covers use `object-fit: contain`.
- Recently played shows each whole cover in its shape. The header matches the main menu (CRT logo, crumb,
  glowing 8-bit LIBRARY).
- Mouse and keyboard layout uses the same shapes; hover shows a round play button and the star.
- `gamepad.ts`: "ahead" now has 2 px of leeway, because covers in a stretched row can differ by a fraction of
  a pixel; without it Down could pick a game in the same row (found by the browser pad test).
- Not changed: Couch Play's host picker grid (CQ3) and the game page layout.

## Controller buttons on the Library
A open · Y favourite / unfavourite · X search · LB / RB change console · Menu (Options) co-op only / show all
(not on Favourites) · B main menu (in the search box, B goes back to the games).
Screens claim buttons with `useScreenButtons()` in `gamepad.ts`; every other screen keeps the old behaviour.

## How it was checked (Confirmed)
- `npm run check` and `npm run build`: no errors.
- Screenshots of every state in Chromium (the same engine as Windows' WebView2) at 1280x800 and the
  smallest window, 1100x700.
- A pretend controller (the browser's gamepad reader) pressed D-pad, A, B, X, Y, LB, RB and Menu on the
  Library: each did what the guide says, focus came back to the same game after B from a game page.
- GitHub's Windows build and install / play / update test (CI).
- Not yet seen on Jayden's PC or with his real controller.

## Not done yet (ideas, need Jayden's OK or a mockup first)
- The button guide on the other screens (Guides board): main menu, game page (Y favourite there too),
  settings. Only the Library has it so far.
- Known (pre-existing, in `gamepad.ts`, controller thread's area): D-pad right from the last game in a short
  row can jump up to a console tab instead of staying put.
