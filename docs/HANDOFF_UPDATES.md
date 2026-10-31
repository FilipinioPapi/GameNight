# Handoff: in-app updates

Read `docs/UPDATES.md` first (how releases reach the NAS and the app, and the security model).

## 2026-10-31: progress and restart fix (thread "Fix auto-update progress and restart")
Jayden's report: the progress showed until about halfway, Game Night closed and didn't reopen.

What was measured:
- Confirmed (JJsPC's `update.log`, read with his OK): the last update, 0.3.1 to 0.3.2 on 2026-10-29,
  installed fine (installer code 0) and the helper ran its "reopen Game Night" step. So the install worked.
- Confirmed (GitHub Windows test, old code, update box driven like a person at 3 MB/s): the box did reach
  100%, then Game Night closed and nothing was on screen for about 12 s, and the new Game Night opened
  **behind** other windows (visible, not in front). That matches "doesn't reopen" and "hard to tell if it
  worked".
- Unknown: why Jayden saw it stop around halfway. The cloud test never reproduced that; the box tracked the
  download within 0.1 s every time. The new log records what the box shows next to what the download did,
  so the next update on his PC will show it if it happens again.

What changed:
- Two steps instead of one: `download_update` (download and check, Game Night stays open) then
  `start_install` (re-checks the file, starts the helper, waits until the helper is running, closes).
- The box shows Downloading NN%, Downloaded (100%, checked), Installing, and after the restart Updated to vX.
- The installer runs with `/P /UPDATE /R`: its own progress window, and it opens Game Night itself.
- The old version leaves `update\just-updated.txt`; the new version sees it, comes to the front (pinned on top
  for 1.5 s), logs "back after the update" and shows the Updated box.
- Proof: GitHub Windows test, every step in the log, the reopened window in front, and screenshots
  (artifact `update-screens`) showing the box at 53%, Downloaded, Installing, the installer's bar, Updated.

Test: `tools/e2e/windows_test.ps1` (update part), `tools/e2e/slow_server.py`. The e2e build's
`GAMENIGHT_E2E=update-ui` presses Update in the real box (`update_test_mode`).

Waiting on Jayden: one real update on his PC after this ships (the first update that uses the new code is
the one *after* the version containing it, because the old version runs the update).
