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
- Backup shortcut: NOT Start + Select. Jayden reported 2026-10-31 16:15 that Start + Select opens Windows' Alt-Tab switcher
  on his PC (cause Unknown: Windows' own controller features or Steam's desktop controls; to find out on his PC).
  Proposed instead: hold both stick clicks (L3 + R3) ~1 s. NES/SNES games never use them, and they're not a known
  Windows, Game Bar or Steam shortcut (Strongly inferred; Steam's chords all use the Guide button).

## Recommendations (for Jayden)
- Menu opens LOCALLY in Couch Play (game keeps going, your player stands still), with "Pause for everyone" as its second item.
  Solo games: the menu simply pauses. If the "stand still" part can't be made reliable, fall back to pausing for everyone.
- No RetroArch menu for players at all. Everything people need gets a Game Night setting; Game Night writes RetroArch's settings
  fresh each launch, so nothing can get broken permanently. Optional later: a hidden "advanced" switch for Jayden only.
- Quit moves into the menu ("Quit" with a confirm). Holding both stick clicks (L3 + R3) opens the menu as backup to the Xbox/PS button.
- Menu tabs: HOME (resume, pause for everyone, back to lobby, switch to watching, end game/quit), MY SCREEN (look/shader,
  bezel, pixels, screen shape, FPS), GAME (my volume; host: reset, game options; solo: save/load state, rewind, fast forward),
  CONTROLLER (my pad, hand pad to a friend, button layout). Lobby panel on the right in Couch Play.
- Shader list to start: Off, Scanlines (light), CRT Lottes or CRT Geom (medium), CRT Royale (heavy). Shaders are GPL-licensed
  slang files shipped with the player (licence files included).

## Next (only after Jayden's OK)
1. Windows CI test: shaders differ between players, 0 desync; pause-for-all; each "stand still" candidate; stdin SET_SHADER.
2. Build integer scaling + bezels (solo first), then the menu (solo), then Couch Play menu.

## Bezel packs (checked 2026-10-31, after Jayden approved IG1-IG3)
Jayden wants ready-made open-source bezels for NES/SNES, picked per player. Pictures (fitted to whole-pixel 4x at 1080p):
project files `gamenight/ingame-menu/bezel-options/`.
- Confirmed (read the files): libretro/overlay-borders, MIT. NES + SNES in two styles: "Nosh01" (console photo strips,
  2560x1440) and "NyNy77" (dark TV frame with logos, 1920x1080). Contains Nintendo logos and console photos (the MIT licence
  covers the authors' work, not Nintendo's trademarks).
- Confirmed: libretro/common-overlays, CC BY 4.0 (credit needed). Animated NES pad border (buttons light up when pressed),
  animated Super Famicom border, old-TV photo border made for 4x scaling, game-themed borders (Mario/Castlevania art:
  not ours to ship, skipped).
- Confirmed: Duimon's Mega Bezel graphics, CC BY-NC-ND (non-commercial, no edits, credit). Needs the Mega Bezel shader
  (GPL3, libretro/slang-shaders), which needs RetroArch's integer scaling OFF (does its own) and a strong graphics card.
  Also koko-aio and uborder (GPL3): shader bezels, generic TV/monitor frames, lighter than Mega Bezel.
- Confirmed (measured): the picture-style bezels have a full-height hole (game stretched), not a whole-pixel one. At 4x on
  1080p the game is 896 tall, so Game Night shrinks the bezel to fit the game exactly and fills the edge black (allowed by
  MIT and CC BY). Strongly inferred: done in Rust at game start for each screen size.
- Confirmed (code): RetroArch 1.22.2 has no "overlay sets the game area" option, so Game Night places the game itself.
- Picture bezels (overlays) and shaders are separate in RetroArch, so bezel and CRT look are two independent per-player choices.
  Shader bezels (Mega Bezel, koko-aio) would be one combined choice.

## Jayden's bezel pick (2026-10-31 16:30)
- Default: B (NyNy77 dark TV frame). Alternatives: C (NES controller, buttons light up; Super Famicom one for SNES) and A (Nosh01 console photos). Each player picks their own. Our own minimal IG1 bezel and D (old TV) not chosen.
- Jayden chose 2026-10-31 16:31: KEEP the Nintendo logos on A and B (his call, risk explained).

## Build progress (thread "Build the in-game menu and bezels", branch claude/project-thread-x0w0gw)

Measured on GitHub's Windows machine (tools/e2e/ingame_menu_test.py, workflow ingame-menu.yml):
- A different look per player in Couch Play: 0 frames out of sync, also when switched live (SET_SHADER on the
  command port). stdin commands don't work in RetroArch 1.22.2. "Look off" = SET_SHADER nearest.slangp.
- Whole-pixel scaling at 1080p SNES: TV shape 1196x896 at (362, 92), square 1024x896 at (448, 92). Bezel sits exactly.
- RetroArch's own menu, opened hidden (see-through RGUI theme, kiosk mode, menu_pause_libretro=false online)
  stops your presses while the game keeps going for everyone = how Game Night's menu holds your player still.
- Host PAUSE_TOGGLE pauses/resumes everyone; a friend's can't be resumed (RetroArch). Jayden chose (17:30):
  friends' "Pause for everyone" goes through the Game Night server (server update; he installs it on Unraid).
- Heavy looks on a PC without a graphics card slow everyone (Royale ~5 fps on CI). Warn when a PC drops below full speed.
- Bezel C: a mouse click on its pictured buttons presses them. Re-check inside the real app.
- SECURITY: RetroArch's command port binds 0.0.0.0 and answers on the PC's network address (run 41224303485).
  Netplay host port: being measured. Affects Couch Play 0.3.5.

Built so far:
- app/src-tauri/src/display.rs: looks, whole-pixel rect, bezel fitting to the screen (cached in the cache
  folder), RetroArch lines for scaling/bezel/hidden menu. games.rs uses it at game start (bezel noted in
  logs/bezel.txt). Settings: 12 looks and a bezel choice per console. Default: 4:3 whole-pixel + bezel B ("tv").
- Not built yet: the in-game menu window (transparent owned window over the game), the pad watcher (Xbox
  button / L3+R3 hold, must work with Steam open), command port for solo games (wait for the security fix),
  the server route for friends' pause, the app-level Windows test.
- Jayden 18:17: "Back to lobby" is an in-game menu item (Couch Play only), replacing the lobby popup's Y shortcut.

## Menu build (branch claude/project-thread-rhmybd, 2026-10-31 evening)
Built:
- `app/src-tauri/src/ingame.rs` + `app/menu.html` / `src/menu/InGameMenu.svelte`: a see-through window over the game
  (own capability `capabilities/menu.json`, events only). IG2 layout with HOME and MY SCREEN tabs (GAME and CONTROLLER
  tabs not built yet). IG3 "Paused by" uses the same window.
- Opening it: Xbox button (XInputGetStateEx guide bit), PS button (gilrs Mode), or holding L3 + R3 for 1 s, from
  `pads.rs`, whatever window is in front. Never Start + Select. No controller combo quits a game any more.
- Blocking your presses: RetroArch's own menu opens hidden behind it (MENU_TOGGLE on the local command port; solo now
  gets a random free port too). Solo: the game pauses. Couch: the game keeps going for everyone.
- Solo items: resume, save state, load state, restart, quit to Library (asks first, KEEP PLAYING picked). Couch:
  resume, pause/resume for everyone, back to lobby / full screen, watch/play, refresh game, end game / leave lobby.
  MY SCREEN: look (left/right), applied live with SET_SHADER.
- The lobby's L3 + R3 lobby controls and the Y "back to lobby" shortcut are gone (Jayden 18:16: in the menu instead).
- Pause for everyone: `POST /api/lobbies/{code}/pause` on the server (ends by itself after 10 min or when the pauser
  leaves). The host's app does the actual PAUSE_TOGGLE. Needs the server update on Unraid.
- Couch Play bezels: the bezel file has 2 pages, page 0 fitted to the full screen game, page 1 empty for the small
  box; Game Night flips with OVERLAY_NEXT. Bezel C falls back to B (TV frame) in Couch Play. Whole-pixel scaling now
  in Couch Play too.

CI checks (to be proven): `pad_test.py ingame` (solo: menu opens with Guide and L3+R3, game pauses, look change,
quit with confirm), `couch_app_test.py` (menu over full screen game, host presses blocked while the friend's work,
pause for everyone both ways, IG3 shown, bezel lit around the full screen game and not in the box).
Unknown until measured: whether RetroArch's own pad config also reacts to the Xbox button (double toggle), whether
the PS button reaches Game Night while a game is in front (needs Jayden's real DualSense).

### Couch Play findings (2026-10-31 late, all measured in CI)
- Confirmed: the host's RetroArch crashes (0xc0000005) were caused by the TEST asking RetroArch `GET_STATUS`
  (cdb attached by `couch_app_test.py`, run 41246455248: null read at retroarch+0x1af761 inside the GET_STATUS
  handler). Game Night never sends GET_STATUS. Never use it in tests either.
- Confirmed: a command sent right after MENU_TOGGLE can be lost (Quit, Refresh's SAVE_STATE, bezel page flips).
  `ingame::ra_menu` tracks RetroArch's hidden menu per command port; `ra_menu_settled()` is false for 0.5 s after a
  toggle; Refresh waits and re-sends SAVE_STATE once; bezel flips wait and are re-checked every second.
- Confirmed (in-game menu test part 3, 20 s pauses through the nyc relay, run 41253096478): RetroArch 1.22.2 netplay
  only survives a long pause when EVERY copy pauses inside its own hidden menu (MENU_TOGGLE then PAUSE_TOGGLE), so
  netplay never sees a pause. The host alone (menu open: friend dropped after ~10 s; menu closed: stuck after resume)
  and RetroArch's own netplay pause (both copies, either order) all broke. Source: netplay_frontend.c stall limits
  (host 5 s, client 10 s) and runloop.c (in the menu, PAUSE isn't passed to netplay).
- Confirmed (run 41254795377): friends 2.5 s after the host both times came back, even after 90 s; a friend resuming
  2.5 s BEFORE the host was dropped. So: every PC follows the server's pause (`couch.rs follow_pause`), the host at
  once, everyone else at `FOLLOW_AFTER` (3.5 s) after the change; the server's lobby view gives `paused.ago` and
  `resumed_ago` (needs the server update). `ingame::pause_for_everyone` applies the newest wish once, in turn;
  `PAUSE_HOLD` keeps the hidden menu open until resume. With the OLD server (no `ago`), everyone acts at once
  (works only when friends happen to hear it after the host).
- Measured: with the host's menu open the game runs slower on GitHub's machine (software graphics): about 50 to 36
  frames a second in full screen. Unknown on a real graphics card; check with Jayden's PC.
- Confirmed (Couch Play app test run 41256780032): Game Night's own relay bridge (`relay.rs`) closed the friend's
  link during a pause (silent for 7 s). It now skips its silence rules while this PC holds a pause for everyone and
  for 8 s after resuming (`Limits::hold` = `ingame::paused_for_everyone`); a new RetroArch forgets old pauses
  (`ingame::pause_reset`).
- Confirmed (run 41263774912): host pause and friend pause, 20 s and 15 s, both come back with the right players
  and in sync. The test's pretend friend must use `menu_pause_libretro = false` like a real friend's Game Night
  (with RetroArch's default the host stayed frozen after resuming, run 41262669675).
- Debug aids kept in CI only: WER LocalDumps + cdb as crash debugger (couch-app.yml), cdb attached to each host
  RetroArch (`watch_host_crashes`, now only with `COUCH_TRACE_CRASHES=1`: attaching froze the host's start for
  ~30 s, run 41261525120), summary in the "Where RetroArch crashed" step.

## Game control lost after the menu (thread "Fix game controls after the pause menu", 2026-11-01)
Jayden (0.3.7, real Xbox pad): after the menu he couldn't control the game, and "Back to lobby" seemed to press A.
- Confirmed (in-game menu test part "guide", run 41328147992, RetroArch alone): RetroArch's own controller profiles
  bind the Xbox button to RetroArch's menu (`input_menu_toggle_btn`, 136 profiles; DualSense too). A setting can't
  undo that (`nul` falls back to the profile). Xbox button + Game Night's MENU_TOGGLE within the press = one flip
  (why CI passed); MENU_TOGGLE arriving after the button is let go = TWO flips: RetroArch's menu closed while Game
  Night's was open (presses reach the game: the "stray A"), then Resume opened it (game locked).
- Confirmed (same run): a button still held when RetroArch's menu closes reaches the game (pad 1 = 8000 while held).
- Confirmed (same run): two MENU_TOGGLEs 100 ms apart both count (none lost).
- Fix: `fetch_player.py` leaves every shortcut line out of Game Night's copy of the profiles (the game's own buttons
  stay). Only the Xbox / PS button opens the menu (L3 + R3 hold removed); while open it does nothing; B only cancels
  a question; only RESUME (or an item that leaves the game screen) closes it. `close()` hides the menu, then waits
  (max 2 s) until no button is down (`pads::ANY_HELD`) before giving RetroArch's input back. `ra_menu` keeps
  toggles 0.5 s apart.
- Proof: in-game menu test part "guide" (Xbox button no longer opens RetroArch's menu; a late toggle leaves it open),
  `pad_test.py ingame` and `couch_app_test.py` (B / Xbox don't close, the A held on RESUME never reaches the game,
  control comes back). Unknown until Jayden tries: his real pad and DualSense (PS button) with Steam open.
