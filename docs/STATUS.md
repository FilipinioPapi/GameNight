# Game Night status

Every thread reads this first and keeps its own section current. Labels: Confirmed (measured),
Strongly inferred, Unknown.

## Library screen (thread "Build the Library screen design")
- Done: the approved Library design, both layouts, favourites, recently played, button guide,
  Settings › Layout (PR #10, merged into PR #8's branch). Retro glow style (banded background, VT323,
  pulsing glows) approved 2026-10-31, in review on branch `claude/project-thread-yyq3jl`.
  Details: `docs/HANDOFF_LIBRARY.md`.
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

## Online co-op (thread "Plan quickest online co-op for NES and SNES")
- Plan agreed: build in proven layers, stability before speed. Details: `docs/HANDOFF_ONLINE.md`.
- Merged: PR #12. Anyone in Jayden's Discord server can sign in, and the role is optional.
- Next: step 1, two players in sync on GitHub's Windows runner.
- Going-online server notes live in the project's private notes, not the repo (see HANDOFF_ONLINE.md).

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
