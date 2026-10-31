# In-game display and the Xbox / PS button menu (design thread, 2026-10-31)

Thread "Design the in-game menu and display". DESIGN ONLY: nothing is built until Jayden OKs the mockups.
Mockups: main-menu canvas https://claude.ai/artifact/KRmdN4XWGPiuvMzSGns2ko, row "In-game" (IG1-IG3).
Labels: Confirmed (measured or read in RetroArch 1.22.2's own code), Strongly inferred, Unknown.
"Read in code" means read in RetroArch's source at tag v1.22.2 (the version Game Night ships), not yet run on Windows.

## What Jayden asked for (2026-10-31 15:29 and 15:32)
- Whole-pixel (integer) scaling for every console, plus a minimal bezel themed per console so there are no black bars.
- The Xbox / PS button opens Game Night's own menu (like RetroArch's quick menu), not RetroArch's.
- Per-player display settings (shaders like CRT Royale) on each person's own screen.
- Opening the menu should not pause the game for everyone; an option in it to pause for everyone, with a
  "paused by <name>" message. Open to pausing for all if that's better.
- The menu shows the lobby (who's in, seats) and has "back to lobby" (keeps your seat, game goes back in the box).
- A few essential emulator settings in the menu. Quit shortcut L1+R1+Start+Select → just Start+Select.
- His view on RetroArch's own menu: probably not available to players. Asked for an opinion.

## Feasibility

### Whole-pixel scaling, every console
- Confirmed (maths): whole-pixel scaling always leaves a border, so a bezel is needed to avoid black bars.
  At 1080p: NES/SNES/Genesis 4x = 1195x896 (83% tall, 62% wide); Game Boy 7x; GBA 6x; N64/PS1 4x.
  At 1440p: NES/SNES 6x (93% tall). At 4K: 9x (93% tall).
- Confirmed (code): RetroArch 1.22.2 has `video_scale_integer` plus `video_scale_integer_axis` and
  `video_scale_integer_scaling` (under/over/smart). Game Night already uses integer scaling for the "pixel" screen setting (games.rs).
- Strongly inferred: for exact bezel placement, Game Night should work out the game's rectangle itself
  (custom viewport, aspect index 23) from the screen size and the console's picture size, then draw the bezel to match.
- Strongly inferred: for 3D consoles (N64, PS1 3D, GameCube, Wii, PS2) whole-pixel scaling matters less; they
  look best with the emulator's own upscaling, still with a bezel. Only NES and SNES exist in the app today.
- Choice to make: NES/SNES pixels aren't quite square on a real TV. "Sharp" (square pixels, perfect) vs
  "TV shape" (height whole-pixel, width corrected). Recommend TV shape as default, sharp as an option.

### Bezels
- Confirmed (code): RetroArch overlays (`input_overlay`) can draw a full-screen picture over the game area's surroundings,
  shown on top of the shader output, so CRT effects stay inside the game.
- Strongly inferred: Game Night makes the bezel picture for each screen size at game start (in Rust, in its cache folder),
  so it lines up exactly with the whole-pixel game rectangle. Our own minimal designs, no console makers' logos.
- Not in the small lobby box: the box shows the plain game.

### Per-player shaders and display settings in Couch Play
- Strongly inferred (from how RetroArch netplay works, code): only button presses and game saves travel between players;
  shaders, bezels, scaling, smoothing and FPS counter are drawn on each PC after the game runs, so each player can differ
  without breaking sync. Must stay the same for everyone: core options (things that change the game itself) = host decides.
- Strongly inferred risk: a heavy shader (CRT Royale) on a weak PC that drops below 60 FPS slows the game for EVERYONE
  online (netplay waits for the slowest). Ship lighter CRT options too and warn when a PC can't keep up.
- To prove (Windows CI): two players, one with CRT Royale on, one plain → 0 frames out of sync (reuse couch_lobby_test RAM check).
- Changing shader live: Confirmed (code) a `SET_SHADER <path>` command exists. Its channel: stdin commands are in the
  Windows build files (Makefile.win, MSVC), Unknown whether the shipped 1.22.2 build has them. Network commands stay off
  (security). If no channel works: restart RetroArch and rejoin the same seat (already proven to work without pausing others).

### Menu without pausing others
- Confirmed (code): with `netplay_allow_pausing = false` (Game Night's setting today) RetroArch never pauses the game
  for a menu or focus loss in netplay.
- Unknown, the hard part: stopping YOUR button presses reaching the game while YOUR menu is open. RetroArch reads Xbox pads
  even when its window isn't in front (the Couch Play test confirmed the pad reaches the game with the lobby in front).
  No "block input" command exists (read the full command list). Candidate ways, to test in CI:
  1. Briefly switch the player to "watch" (`NETPLAY_GAME_WATCH`) and back on close (proven to work, but the seat is freed meanwhile).
  2. Open RetroArch's own menu hidden behind ours (RetroArch blocks game input while its menu is open, code) — risky.
  3. Fallback: in Couch Play the menu pauses for everyone.
- Pause for everyone: Confirmed (code) RetroArch netplay supports pausing for all ("Netplay peer "%s" paused") when
  `netplay_allow_pausing` is on; Game Night would show its own "Paused by Jayden" screen. Turning it on also needs
  `pause_nonactive = false` so a window switch never pauses everyone. To test in CI.

### Xbox / PS button on Windows
- Confirmed (code, pads.rs): Game Night already reads the Xbox button (XInputGetStateEx). But it ignores all pad input
  while it isn't the window in front, so during a game a small "watcher" just for the menu button is needed.
- Strongly inferred: Windows' Game Bar also opens on the Xbox button by default ("Open Game Bar using this button on a controller").
  Game Night can't and shouldn't change that setting; Jayden/friends can switch it off (Settings › Gaming › Xbox Game Bar).
  Steam, if running with Steam Input, may also take it.
- Unknown: DualSense PS button through gilrs while Game Night is in the background (Windows' WGI input may only deliver to the
  window in front). Test on CI isn't possible (pretend controller is Xbox-style); needs Jayden's real DualSense.
- Backup shortcut: hold Start + Select ~1 s (a hold avoids clashing with games that use Start+Select).

## Recommendations (for Jayden)
- Menu opens LOCALLY in Couch Play (game keeps going, your player stands still), with "Pause for everyone" as its second item.
  Solo games: the menu simply pauses. If the "stand still" part can't be made reliable, fall back to pausing for everyone.
- No RetroArch menu for players at all. Everything people need gets a Game Night setting; Game Night writes RetroArch's settings
  fresh each launch, so nothing can get broken permanently. Optional later: a hidden "advanced" switch for Jayden only.
- Quit moves into the menu ("Quit" with a confirm). Start+Select (held) opens the menu as backup to the Xbox/PS button.
- Menu tabs: HOME (resume, pause for everyone, back to lobby, switch to watching, end game/quit), MY SCREEN (look/shader,
  bezel, pixels, screen shape, FPS), GAME (my volume; host: reset, game options; solo: save/load state, rewind, fast forward),
  CONTROLLER (my pad, hand pad to a friend, button layout). Lobby panel on the right in Couch Play.
- Shader list to start: Off, Scanlines (light), CRT Lottes or CRT Geom (medium), CRT Royale (heavy). Shaders are GPL-licensed
  slang files shipped with the player (licence files included).

## Next (only after Jayden's OK)
1. Windows CI test: shaders differ between players, 0 desync; pause-for-all; each "stand still" candidate; stdin SET_SHADER.
2. Build integer scaling + bezels (solo first), then the menu (solo), then Couch Play menu.
