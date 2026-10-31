# Game Night status

Every thread reads this first and keeps its own section current. Labels: Confirmed (measured),
Strongly inferred, Unknown.

## Library screen (thread "Build the Library screen design")
- Done, in review: the approved Library design, both layouts, favourites, recently played, button guide,
  Settings › Layout. Branch `claude/project-thread-yyq3jl`, PR into `claude/project-thread-wdks34` (PR #8).
  Details: `docs/HANDOFF_LIBRARY.md`.
- Waiting on Jayden: OK on the banded background and VT323 lettering from the retro glow board.
- Confirmed: builds, screenshots, pretend-controller test in the browser, GitHub Windows CI.
  Unknown: how it looks and feels on Jayden's PC with his real controller.

## Updates (thread "Fix auto-update progress and restart")
- In review: the update box now shows the download to 100%, then Downloaded (checked), then Installing; the
  installer's own progress window runs; Game Night comes back in front and says Updated. Branch
  `claude/project-thread-2i2092`, PR into `claude/project-thread-wdks34`. Details: `docs/HANDOFF_UPDATES.md`.
- Confirmed: GitHub Windows test (log of every step, window in front, screenshots). Jayden's last real
  update (0.3.1 to 0.3.2) installed fine; it reopened behind other windows (strongly inferred from the test).
- Unknown: the "stops halfway" he saw; the new log will show it if it happens again.
- Waiting on Jayden: a real update on his PC after this ships. The new behaviour shows from the update
  *after* the release that contains it.
