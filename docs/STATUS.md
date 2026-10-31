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

## Updates (thread "Fix auto-update progress and restart")
- In review: the update box now shows the download to 100%, then Downloaded (checked), then Installing; the
  installer's own progress window runs; Game Night comes back in front and says Updated. Branch
  `claude/project-thread-2i2092`, PR #17 into main, ships as 0.3.4. Details: `docs/HANDOFF_UPDATES.md`.
- Confirmed: GitHub Windows test (log of every step, window in front, screenshots). Jayden's last real
  update (0.3.1 to 0.3.2) installed fine; it reopened behind other windows (strongly inferred from the test).
- Unknown: the "stops halfway" he saw; the new log will show it if it happens again.
- Waiting on Jayden: a real update on his PC after this ships. The new behaviour shows from the update
  *after* the release that contains it.
