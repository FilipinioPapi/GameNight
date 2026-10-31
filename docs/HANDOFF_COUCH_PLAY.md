# Handoff: Couch Play online (2026-10-31)

Thread "Build Couch Play online in the app". Read `docs/STATUS.md` first. Design: approved boards CQ1-CQ6
(project files `gamenight/couch-play/HANDOFF-couch-play-design.md`). Contract: `docs/COUCH_PLAY_SPEC.md`.
Measured groundwork: `docs/HANDOFF_NETPLAY_TEST.md` (relay, private way) and the lobby proof
(`tools/e2e/couch_lobby_test.py`, project files `gamenight/couch-play/HANDOFF_COUCH_PLAY_TEST.md`).

## How it fits together
- Server (`server/gamenight/lobbies.py`, routes in `app.py`): lobbies in memory, codes, seats, heartbeats
  (3 s; 10 s quiet = dropped; seat held 120 s; host quiet 30 s = lobby ends). Relay session only to members.
- Windows side: `couch.rs` (commands, heartbeat, RetroArch start-up per role), `relay.rs` (the private-way
  bridge: holds libretro's relay session, splices each friend to 127.0.0.1, closes silent links early),
  `gamebox.rs` (RetroArch's borderless window owned by ours, over the box; full screen by resizing).
- Screens: `lib/couch.svelte.ts`, `screens/CouchPlay.svelte`, `Lobby.svelte`, `JoinCode.svelte`, plus the
  OPEN LOBBIES tab on the main menu and the Library's host-pick mode. `gamepad.ts` got `setPadLock()`: while
  your own game runs and you have a play seat, the lobby ignores the pad; hold VIEW + MENU 1 s for lobby controls.
- Logs on each PC: cache folder `player/logs/couch.log` and `relay.log`.

## Labels
- Confirmed: unit tests and browser checks (see STATUS). Windows whole-chain test: see PR #24's `couch-app` run.
- Strongly inferred: silent-link thresholds (player 3 s, watcher 7 s, anything 20 s); Windows Firewall may ask
  on the first host and Cancel is fine (friends come in through our bridge on 127.0.0.1).
- Unknown: real PCs in different homes, display scaling and several monitors for the box, SNES games with
  3-4 players on real pads, NES Four Score (not built).

## Next
- Jayden's go-online steps, then one real friend test (write the test request first).
