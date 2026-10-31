# Controllers: handoff (updated 2026-10-29)

Labels: **Confirmed** = measured. **Strongly inferred** = follows from measurements. **Unknown** = not measured yet.

## Where things stand
- Code: PR #8 (0.3.3, branch `claude/project-thread-wdks34`) plus PR #9 (branch `claude/project-thread-7arnv6`, targets #8's branch).
- PR #9 adds the cloud controller test and changes no real-app behaviour except one extra log line per
  menu press ("after button N: screen ...; focused ...").

## The cloud controller test (GitHub's Windows machine, every push)
- `.github/workflows/app.yml` step "Add a pretend Xbox controller": installs ViGEmBus (from the vgamepad
  0.2.0 sdist, fingerprint-checked) and Microsoft's Xbox 360 pad driver (Update Catalog cab,
  fingerprint-checked). **Confirmed**: windows-latest is Windows Server 2025 with no Xbox 360 driver, so
  without the cab a pretend Xbox pad fails with `VIGEM_ERROR_TARGET_NOT_PLUGGED_IN`.
- `tools/e2e/pad_test.py menus`: two pretend pads like Jayden's PC (an idle one in slot 1, the one we
  press in slot 2). Opens the real app (e2e build, test player, no sign-in) and presses D-pad right, right, left, left,
  A, B. Reads `pads.txt` after each press.
- `tools/e2e/pad_test.py game`: presses A in the menus, Game Night starts the test game, then holds each
  button and asks the game (RetroArch's local command port, on only in the e2e build) which NES buttons
  player 1 and player 2 have down. The test ROM (`make_test_rom.py`) keeps them in RAM $10/$11.
  Runs three ways: one pad; idle pad + pad; idle pad + pad with RetroArch's "dinput" reader forced
  (`GAMENIGHT_E2E_READER=dinput`, e2e build only).

## Results (run 51, commit a92d0a3) - all Confirmed in the cloud
- Main menu: down moves to Settings, up back to Play, A opens the library, B goes back.
- Game, all three ways: every button (A, B, View, Menu, D-pad x4) reached **player 1** as the right NES
  button (Xbox A = NES B spot, Xbox B = NES A spot). The idle pad's A went to player 2.
- RetroArch's log: the idle pad is configured first, then Game Night's Player 1 reservation moves the
  used pad to player 1 ("reserved for player 1, updating").

## What the cloud can't copy from Jayden's PC (Unknown)
- His hidden Razer pad (046d:0000) is XInput-only (not in DirectInput's list). CI's idle pad is visible
  to both, so in CI Game Night keeps the "xinput" reader; the dinput path was tested by forcing it.
- His real pad is an Xbox Series pad (045e:0b12 USB, 045e:02ff in XInput), which may reach Windows
  through a different driver than the pretend Xbox 360 pad.
- Whether the main menu reacts on his PC with this build. The earlier "no visible change" on the main
  menu was seen on an older build (before the menus also asked for the pad every frame).

## Real-controller check for Jayden (one session)
What we know: menus and games work in the cloud with the same setup as his PC except the two points above.
Steps (his hands only; no pretend presses on his PC):
1. Install the PR #9 build (`Game-Night-windows` from the latest green run).
2. Main menu: D-pad right, right, left, left across the cards, A (Library opens), B (back, lands on LIBRARY).
3. Library: pick a game with A; on its page press B to go back (don't press Remove).
4. Play a game: does it react to A and the D-pad? Quit with Esc.
Then send (or let Claude read, with his OK) `%LOCALAPPDATA%\xyz.jjsnas.gamenight\player\logs\pads.txt`
and `controllers.txt`.
What would change the code:
- Menus don't react: pads.txt shows whether presses reach Rust ("press button ..."), reach the menus
  ("menus: button ..."), and what they did ("after button ...").
- Game ignores the pad or the wrong player moves: controllers.txt shows which reader and Player 1 were used.
