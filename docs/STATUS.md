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
- play.jjsnas.xyz = Roof Rage's ntfy board; Game Night plan: its own /gamenight/ custom location, checked before and after (HANDOFF_ONLINE.md).

## Game window in front (thread "Minimize Game Night when a game starts")
- Built on branch `claude/project-thread-sh0idr` (PR #18, into the 0.3.3 branch): when a game starts, Game Night
  waits for RetroArch's window, makes sure it's in front, then minimizes. When the game closes, Game Night comes
  back to the front (it already tried to; now measured). Each step is logged to `player/logs/window.txt` in the
  cache folder.
- Confirmed (CI runs 96 and 97, commit 518dc85): game test and all three pretend-controller game tests saw
  RetroArch in front, Game Night minimized, and Game Night back in front after the game closed.
- Unknown: Jayden's PC. If it misbehaves there, `window.txt` shows which step went wrong.
- Waiting on Jayden: whether Game Night should come back by itself after a game (built as "yes", the recommended choice).
