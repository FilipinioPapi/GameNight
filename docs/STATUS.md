# Game Night status

Every thread reads this first and keeps its own section current. Labels: Confirmed (measured),
Strongly inferred, Unknown.

## Library screen (thread "Build the Library screen design")
- Done: the approved Library design, both layouts, favourites, recently played, button guide,
  Settings › Layout (PR #10, merged into PR #8's branch). Retro glow style (banded background, VT323,
  pulsing glows) approved 2026-10-31, in review on branch `claude/project-thread-yyq3jl`.
  Details: `docs/HANDOFF_LIBRARY.md`.
- Box art in its real shape per console, RomM style (approved 2026-10-31): branch
  `claude/project-thread-n4n7r0`, see `docs/HANDOFF_LIBRARY.md`. Confirmed in Chromium with 181 of Jayden's
  real covers and a pad test; Windows CI on the PR. Unknown: how it looks on his PC.
- Smooth, console-like menu movement on every screen: its own thread ("Make menu movement smooth and console-like").
- Confirmed: builds, screenshots, pretend-controller test in the browser, GitHub Windows CI.
  Unknown: how it looks and feels on Jayden's PC with his real controller.

## Smooth controller movement (thread "Make menu movement smooth and console-like")
- Jayden approved the "Smooth" demo (https://claude.ai/artifact/NorZSydMr8mSb5TinLbsMY) on 2026-10-31 and
  asked for the main menu's PLAY to read LIBRARY. Built on branch `claude/project-thread-3l4865`.
  Details: `docs/HANDOFF_MENU_MOVEMENT.md`.
- Confirmed: pretend-controller test in Chromium (same engine as Windows' WebView2): moves, eased
  scrolling, gliding frame, stick and hold-repeat. Unknown: how it feels on Jayden's PC with his pad.
- Not in this thread: new main menu concepts and game-art backdrops ("Design a livelier main menu").

## Main menu (thread "Build the approved main menu")
- Jayden approved design A21 on 2026-10-31 (card icons left out for now). Built on branch
  `claude/project-thread-tdlf5x`. Details: `docs/HANDOFF_MAIN_MENU.md`.
- Confirmed: browser check against the approved picture. Windows pretend-controller run: see the PR.
  Unknown: feel on Jayden's PC with his real pad. Waiting on Jayden: the card icons (later).

## Online co-op (thread "Plan quickest online co-op for NES and SNES")
- Plan agreed: build in proven layers, stability before speed. Details: `docs/HANDOFF_ONLINE.md`.
- Merged: PR #12. Anyone in Jayden's Discord server can sign in, and the role is optional.
- Next: step 1, two players in sync on GitHub's Windows runner.
- Going-online server notes live in the project's private notes, not the repo (see HANDOFF_ONLINE.md).

## Couch Play lobby test (thread "Prove the Couch Play lobby can work")
- Design CQ1-CQ6 approved 2026-10-31. Cloud test only, app unchanged. Details: `docs/HANDOFF_COUCH_PLAY_TEST.md`.
- Confirmed (runs 41181330618 and 41183819291, both all green): live game in a lobby box and full screen and back (app must do full screen
  itself); 4 SNES players (multitap) + 4 watchers in sync on one machine and through the relay the private way;
  play/watch switching and drop/rejoin without pausing, except a silent internet drop freezes everyone ~5 s.
- Confirmed, cause Unknown: RetroArch sometimes closes by itself (0xc0000005) right after starting, 0-6 times
  a run; a second try always worked, so the app should retry once.
- Unknown: real PCs and internet, real pads, the real app window.

## Updates (thread "Fix auto-update progress and restart")
- In review: the update box now shows the download to 100%, then Downloaded (checked), then Installing; the
  installer's own progress window runs; Game Night comes back in front and says Updated. Branch
  `claude/project-thread-2i2092`, PR #17 into main, ships as 0.3.4. Details: `docs/HANDOFF_UPDATES.md`.
- Confirmed: GitHub Windows test (log of every step, window in front, screenshots). Jayden's last real
  update (0.3.1 to 0.3.2) installed fine; it reopened behind other windows (strongly inferred from the test).
- Unknown: the "stops halfway" he saw; the new log will show it if it happens again.
- Waiting on Jayden: a real update on his PC after this ships. The new behaviour shows from the update
  *after* the release that contains it.

## Keeping secrets out / going public (thread "Check if Game Night code is safe to make public")
- Confirmed 2026-10-31: no passwords, tokens or private keys anywhere in the repo or its history.
  Not yet clean enough to go public: Jayden's email on merge commits, server-setup notes in the docs,
  and picture rights. Details and verdict: `docs/HANDOFF_SECURITY.md`. Rules: `docs/SECURITY_RULES.md`.
- New: secret check on every push and PR, plus a pre-commit check (`git config core.hooksPath .githooks`).
- Waiting on Jayden: whether to go public, his GitHub email setting, the pictures, and any history rewrite.

## Game window in front (thread "Minimize Game Night when a game starts")
- Built on branch `claude/project-thread-sh0idr` (PR #18, into #17's branch; ships in 0.3.4): when a game starts, Game Night
  waits for RetroArch's window, makes sure it's in front, then minimizes. When the game closes, Game Night comes
  back to the front (it already tried to; now measured). Each step is logged to `player/logs/window.txt` in the
  cache folder.
- Confirmed (CI runs 96 and 97, commit 518dc85): game test and all three pretend-controller game tests saw
  RetroArch in front, Game Night minimized, and Game Night back in front after the game closed.
- Unknown: Jayden's PC. If it misbehaves there, `window.txt` shows which step went wrong.
- Waiting on Jayden: whether Game Night should come back by itself after a game (built as "yes", the recommended choice).

## Couch Play online (thread "Build Couch Play online in the app")
- Merged: PR #22, the server side (lobbies, 6-letter codes, 4 play + 4 watch seats, held seats, relay hand-off,
  optional `BASE_PATH`). The container publishes from main.
- In review: PR #24 (0.3.5), the app side: private relay bridge, live game box, Couch Play / Host / Lobby / Join
  screens. Contract: `docs/COUCH_PLAY_SPEC.md`. Details: `docs/HANDOFF_COUCH_PLAY.md`.
- Confirmed: unit tests (Rust 48, server 31), 52 browser pretend-controller checks. The Windows whole-chain test
  (`couch-app.yml`) is on PR #24.
- Waiting on Jayden: the go-online steps (project files `gamenight/couch-play/GO-ONLINE-STEPS.md`), the
  lobby-controls decision card, and a real test with a friend.

## In-game display and menu (thread "Build the in-game menu and bezels")
- Built (branch claude/project-thread-x0w0gw): 12 looks (shaders, each PC its own; 0 desync measured), bezels
  B (default) / A / C and whole-pixel scaling for solo games, look and bezel choice in Settings, and an installer
  firewall rule that keeps other PCs off Game Night's RetroArch (Jayden's choice; proven in firewall.yml).
- Built (branch claude/project-thread-rhmybd): the in-game menu (Xbox / PS button or hold L3 + R3), RetroArch's own
  quick menu hidden, "Back to lobby" in the menu, friends' "Pause for everyone" through the server, bezels in Couch
  Play. Proven on GitHub's Windows machine (menu, Back to lobby, Refresh, bezel, host's and friend's pause for
  everyone held 15-20 s and back in sync). Ships in the same release as the lobby and bezel work (Jayden is
  holding the release). Waiting on Jayden after merge: update the Game Night container in Unraid (the server now
  times pauses: `paused.ago`, `resumed_ago`). Not built yet: the GAME and CONTROLLER tabs of the menu.
  Details: `docs/HANDOFF_INGAME_MENU.md`.

## Hide non-game files from game lists (thread "Hide non-game files from game lists")
- Built: the Game Night server leaves anything that isn't a game file for its console out of the game
  lists (Windows' desktop.ini, Thumbs.db, readmes, pictures, save files). Game file types per console
  and a never-a-game list live in `server/gamenight/romm.py`. RomM and the NAS files are never changed.
- The server's log names what it left out ("Not games, left out of the game lists ..."), once per change.
- Confirmed: tests on Linux and GitHub's Windows machine (`server/tests/test_game_filter.py`).
  Strongly inferred: the "desktop" entry in every folder is Windows' desktop.ini (RomM names entries
  after the file name without its ending). Jayden can confirm by opening it in RomM.
- Waiting on Jayden after merge: update the Game Night container in Unraid so the new server runs.

## Clean game start, no RetroArch pop-ups (thread "Boot games cleanly without popups")
- Jayden asked 2026-10-31: no pop-ups when a game starts. All of RetroArch's own on-screen messages are off
  (`app/src-tauri/src/quiet_retroarch.cfg`, added by `games.rs`). Show FPS in Settings still works (it keeps the
  FPS counter, with every message type RetroArch lets us hide still hidden). Game Night's own messages are untouched.
- Proof: `tools/e2e/popup_test.py` (workflow "Pop-up test") photographs the game at boot, on pad plug-in and when a
  friend joins, before and after. Branch `claude/project-thread-nruv59`.
