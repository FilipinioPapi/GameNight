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

## Keeping secrets out / going public (thread "Check if Game Night code is safe to make public")
- Confirmed 2026-10-31: no passwords, tokens or private keys anywhere in the repo or its history.
  Not yet clean enough to go public: Jayden's email on merge commits, server-setup notes in the docs,
  and picture rights. Details and verdict: `docs/HANDOFF_SECURITY.md`. Rules: `docs/SECURITY_RULES.md`.
- New: secret check on every push and PR, plus a pre-commit check (`git config core.hooksPath .githooks`).
- Waiting on Jayden: whether to go public, his GitHub email setting, the pictures, and any history rewrite.
