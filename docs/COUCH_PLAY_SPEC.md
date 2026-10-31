# Couch Play online: build spec (2026-10-31)

Thread "Build Couch Play online in the app". This is the contract between the three parts so they can be built
at the same time without touching each other's files. Design: approved boards CQ1-CQ6 (project files
`gamenight/couch-play/HANDOFF-couch-play-design.md`). Measured facts: `docs/HANDOFF_NETPLAY_TEST.md` and the lobby
proof (project files `gamenight/couch-play/HANDOFF_COUCH_PLAY_TEST.md`, branch `claude/project-thread-6m71fx`).

Rules that apply everywhere: private only (nothing listed publicly anywhere, `netplay_public_announce=false`), no
secrets in the app, the app only touches its own folders, controller-first, plain-English messages.

## Who owns which files
| Part | Files (only these) |
|---|---|
| Server | `server/gamenight/lobbies.py` (new), `server/gamenight/app.py` (routes + base path), `server/gamenight/config.py` (BASE_PATH), `server/tests/test_lobbies.py` (new) |
| Windows side | `app/src-tauri/src/couch.rs`, `relay.rs`, `gamebox.rs` (new), small additions in `account.rs` (send JSON) and `games.rs` (make shared helpers `pub(crate)`), `Cargo.toml` (tokio features / windows features if needed). `lib.rs` only to register the module and commands. |
| Screens | `app/src/screens/CouchPlay.svelte`, `Lobby.svelte`, `JoinCode.svelte` (new), `app/src/lib/couch.svelte.ts` (new), plus routes in `App.svelte`, `state.svelte.ts`, the OPEN LOBBIES tab in `MainMenu.svelte`, host-pick mode in `Library.svelte` |
| Test | `tools/e2e/couch_app_test.py`, `.github/workflows/couch-app.yml` (new) |

## Lobby rules (server is the source of truth)
- Code: 6 characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (no O/0/I/1). Case-insensitive on input.
- 8 places: seats 1-4 (play) + up to 4 watchers. Host is always seat 1.
- Open = every signed-in member sees it in the list; closed = code only. Host can switch any time.
- Only NES (`nes`) and SNES (`snes`) games can be hosted.
- Each member's app sends a heartbeat every 3 s. No heartbeat for 10 s = dropped. A dropped player's seat is
  **held for 120 s** for them (status `held`), then emptied. The host can: `hold` (keep holding, restarts 120 s),
  `give` (to a watcher, by user id), `empty`. A dropped player rejoining with the code within the hold gets the seat back.
- Host gone for 30 s (no heartbeat) or host ends = lobby closed for everyone.
- Lobbies live in memory on the server (a restart closes them). At most 1 lobby per host, 200 overall.
- The relay session id is only given to people who are in the lobby (joined with code or from the open list).

## Server API (all need the app's sign-in pass; base path aware)
`BASE_PATH` (env, e.g. `/gamenight`, default empty): the server answers on both `/x` and `BASE_PATH/x`, so
Nginx Proxy Manager can forward `/gamenight/` with or without stripping it. `PUBLIC_URL` then includes it.

| Call | Body | Answer |
|---|---|---|
| `GET /api/lobbies` | | `{"lobbies": [LobbySummary]}` open ones only |
| `POST /api/lobbies` | `{"game_id": "12", "open": true}` | `Lobby` (caller = host, seat 1). Game must exist in RomM list and be nes/snes |
| `GET /api/lobbies/{code}` | | `Lobby` if you're in it, else `LobbySummary` (404 if no such lobby) |
| `POST /api/lobbies/{code}/join` | `{"as": "play" \| "watch"}` | `Lobby`. `play` when seats are full = 409 "All 4 seats are taken. You can watch." |
| `POST /api/lobbies/{code}/switch` | `{"as": "play" \| "watch"}` | `Lobby` |
| `POST /api/lobbies/{code}/heartbeat` | `{"retroarch": "running" \| "starting" \| "stopped"}` | `Lobby` |
| `POST /api/lobbies/{code}/relay` | `{"server": "host", "port": 55435, "session": "base64"}` host only | `Lobby` |
| `PATCH /api/lobbies/{code}` | `{"open": bool}` host only | `Lobby` |
| `POST /api/lobbies/{code}/seat` | `{"seat": 2, "action": "hold" \| "give" \| "empty", "user": "discord id"}` host only | `Lobby` |
| `POST /api/lobbies/{code}/leave` | | `{"ok": true}` (host leaving = lobby ends) |

Rate limit lookups/joins by code: 20 a minute per user (stops guessing codes).

```
LobbySummary = {"code","open","game":{"id","title","console","players"},"host":{"id","name","avatar"},"players":n,"watchers":n,"started":bool}
Lobby = LobbySummary + {
  "you": {"id","role":"host"|"play"|"watch","seat":1-4|null},
  "seats": [{"n":1..4,"user":User|null,"status":"playing"|"held"|"empty","held_left":seconds|null}],
  "watchers": [User],
  "relay": {"server","port","session"} | null,     // only for members
  "ended": null | "host-left" | "host-ended"
}
```

## Windows side (Tauri commands for the screens)
All return a `Lobby` (above) unless said. Errors are plain-English strings, `"signed-out"` when the pass expired.
- `couch_list()` -> `LobbySummary[]`
- `couch_lookup(code)` -> `LobbySummary`
- `couch_host(root, game_id, open, settings)`: makes the lobby, opens the relay session (bridge), posts it,
  starts RetroArch as the netplay host on 127.0.0.1 only, inside the game box.
- `couch_join(root, code, as, settings)`: joins on the server, then starts RetroArch connecting through the relay
  (`--connect <server> --port <port> --mitm-session=<session>`), as player for its seat
  (`netplay_request_device_pN`) or as watcher (`netplay_start_as_spectator`). The game must already be on the PC.
- `couch_state()` -> `Lobby | null` (latest copy; the Windows side heartbeats by itself)
- `couch_switch(as)`, `couch_set_open(open)`, `couch_seat(seat, action, user)`, `couch_leave()`
- `couch_box(x, y, w, h)`: where the game box is, in CSS pixels of the main window (Windows side multiplies by
  the window's scale). `couch_fullscreen(on)`.
- Events: `couch-update` (Lobby) whenever it changes, `couch-ended` `{"reason": "..."}`.

Facts to follow (measured): game box = RetroArch's borderless window **owned** by Game Night's window and kept
over the box; full screen by resizing it ourselves, never RetroArch's fullscreen toggle. SNES 3-4 players: write
`<remaps>/Snes9x/Snes9x.rmp` with `input_libretro_device_p1 = "1"`, `input_libretro_device_p2 = "257"`,
`auto_remaps_enable = "true"`, `input_remapping_directory` set. Host `netplay_max_connections = 8`. Switching
play/watch = RetroArch network command `NETPLAY_GAME_WATCH` on 127.0.0.1. Keep a handle on every relay link task.
Close a link whose friend side has been silent for 3 s (so a silent player drops at once instead of freezing everyone 5 s).
Retry a RetroArch launch once if it exits within 2 s.
