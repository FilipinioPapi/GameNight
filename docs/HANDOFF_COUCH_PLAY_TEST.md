# Couch Play lobby: can it work? (cloud test, 2026-10-31)

Thread "Prove the Couch Play lobby can work". Design: Couch Play round 2, boards CQ1-CQ6, approved by Jayden
2026-10-31 (canvas https://claude.ai/artifact/KRmdN4XWGPiuvMzSGns2ko; design notes in the project files,
`gamenight/couch-play/HANDOFF-couch-play-design.md`). Test only: nothing in the app changed.
Labels: **Confirmed** = measured, **Strongly inferred** = follows from measurements, **Unknown** = not measured.

## Short answer
All three things the lobby needs work with stock RetroArch 1.22.2 on GitHub's Windows machine:
1. The live game in a box on the lobby screen, and full screen and back: **yes**, as long as Game Night does the
   full screen switch itself (RetroArch's own full screen button breaks it, see below).
2. 4 players on SNES (multitap) plus 4 watchers, in sync, on one machine and through libretro's relay the
   private way: **yes**, 0 frames out of sync.
3. Switching play/watch mid-game and dropping out/rejoining without pausing: **yes**, with one exception: if a
   player's internet goes silent (rather than their game closing), everyone's game freezes for about 5 seconds
   before carrying on without them. That's RetroArch's built-in limit.

## How it was tested
- `.github/workflows/couch-lobby.yml` runs on every push that touches the test; `tools/e2e/couch_lobby_test.py`
  does the measuring.
- `tools/e2e/make_snes_multitap_rom.py`: a tiny SNES test cartridge that reads pad 1 and a multitap (pads 2-5)
  every frame and keeps a frame number, a per-frame fingerprint, all pads and a button-change list in its RAM.
  `check_snes_multitap_rom.py` checks it on a 6502 simulator first (it runs in the SNES CPU's 6502-compatible
  mode). snes9x doesn't publish its RAM to RetroArch's READ_CORE_MEMORY, so the test finds the RAM inside each
  RetroArch process by a marker and reads it (read only) with ReadProcessMemory.
- Part 1 "box": one RetroArch with a stand-in lobby window (`lobby_standin.py`, tkinter, not the real app) that
  has a magenta box. Screenshots show whether the game covers the box and is moving; the game's frame number is
  read every 10 ms to see whether it ever stops.
- Parts 2-3: 8 copies of RetroArch: host P1, players P2-P4 (four pretend Xbox pads, one each), watchers W1-W4.
  Round "couch-direct" on this machine (each friend through a small pass-through that can go silent), round
  "couch-relay-nyc" through libretro's New York relay the private way (bridge, nothing listed).
  Each round: everyone joins; right-seat check (5 buttons per pad, read in all 8 copies); 90 s of random presses
  comparing every finished frame in all 8 copies; P4 switches to watching; W1 takes seat 4 with P4's pad; P4
  asks to play while seats are full; switch back; P2's game killed and rejoined; P3's connection goes silent,
  then P3 rejoins; W2 killed and rejoined; 30 s sync checks after each stage (the last one while the host's
  window goes into a box, full screen and back).

## Results, run 41181330618 (commit 7471f42), all green
Box part also the same in runs 41178993059, 41179703825, 41180494922. Earlier runs found the problems listed
under "Found on the way". Repeated in run 41183819291 (commit 1311aba, also all green, same numbers within a
few ms: 0 frames different in all six sync checks, 4,194 + 1,354 + 1,405 on this machine and 4,147 + 1,347 +
1,369 through the relay; silent drop froze the host 5,043 / 5,042 ms; 10 relay links, none failed).
Run 41182531780 in between had every sync check at 0 different too, but failed one seat reading, see below.

### 1. The game in a box
| | Way A: RetroArch's window made a child of the box | Way B: RetroArch's own borderless window kept over the box |
|---|---|---|
| Into the box | 109 ms | 72 ms |
| Box covered by the game / moving | 100% / 83% of pixels change in 0.3 s | 100% / 84% |
| Pad reaches the game with the lobby window in front | yes | yes |
| Our full screen (cover the screen) and back | 218 ms / 317 ms, lands exactly in the box | 84 ms / 86 ms, exactly in the box |
| Lobby window moves, game follows | (moves with it automatically) | 226 ms (app moves it) |
| Longest the game stopped in any of our steps | 41 ms | 32 ms |

- **Confirmed**: both ways put a live game exactly in the box and switch to full screen and back with the game
  never stopping more than about 2 frames.
- **Confirmed**: RetroArch's own full screen switch (its hotkey or the FULLSCREEN_TOGGLE command) throws its
  window away and makes a new one (4 of 4 runs). In way A the new window is no longer in the box; it comes back
  at the top-left. So **Game Night must do full screen itself** (resize the window) and keep RetroArch's own
  full screen hotkey off. RetroArch's own switch also stopped the game for ~200 ms each time; ours didn't.
- **Confirmed**: the pad drives the game even while the lobby window is in front. The app has to decide who
  listens to the pad in the lobby (for example: the game only gets input in full screen, the lobby otherwise).
- **Strongly inferred**: way B (owned borderless window over the box) is the safer choice for the app: it's a
  normal window of its own, so if RetroArch hangs it can't freeze the lobby. Way A ties the two programs' input
  queues together (that's how Windows child windows across programs work); not measured here.
- **Strongly inferred**: Game Night's real window (Tauri/WebView2) behaves like the stand-in: both are normal
  Windows windows. **Unknown** until the app does it: exact look in the real lobby, other screen sizes and
  scaling, multiple monitors.

### 2. 4 players + 4 watchers
| | On this machine | Through the New York relay (private way) |
|---|---|---|
| Joined (all 7 friends) | 7 of 7, 1.4 s each | 7 of 7, 1.4 s each |
| Host's game stopped while someone joined | at most 41 ms | at most 42 ms |
| Every button on the right seat in all 8 copies | yes (5 checks) | yes (5 checks) |
| Frames compared in all 8 copies, different | 4,255 + 1,384 + 1,371, **0** | 4,122 + 1,299 + 1,393, **0** |
| Button-change histories identical in all copies | yes (1,624 changes in the 90 s round) | yes (1,619) |
| Speed, all 8 connected (8 unconnected copies: 59.1) | 48 frames a second | 46-47 |

- **Confirmed**: 4 SNES players on a multitap plus 4 watchers stay in sync, both on one machine and through the
  relay the private way, with buttons on the right seats everywhere.
- **Confirmed**: the multitap can only be switched on through a RetroArch **remap file**
  (`input_libretro_device_p2 = "257"` in `<remaps>/Snes9x/Snes9x.rmp`, with `auto_remaps_enable`). RetroArch
  ignores that setting in retroarch.cfg (configuration.c reads it from remap files only). The app today has
  `auto_remaps_enable = false`, so it will need its own remap file for SNES 3-4 player games.
- **Strongly inferred**: the 8-copy group ran ~20% slower than 8 separate copies because all 8 share one 4-core
  test machine with no graphics card. On 8 separate PCs this shouldn't apply. **Unknown**: speed and delay with
  real PCs in different homes.
- Relay: no link dropped in run 41181330618 except the ones the test ended on purpose (~6 minutes, 10 links).

### 3. Switching seats, dropping out, rejoining
| Event | Host's game: longest stop | A watcher's game: longest stop |
|---|---|---|
| P4 switches to watching | 41-42 ms | 52-133 ms |
| W1 takes seat 4 | 41 ms | 71-195 ms |
| P4 asks to play, seats full | 42 ms | 53-83 ms |
| P2's game closes suddenly | 42-43 ms | 52-133 ms |
| P2 rejoins (same seat) | 41-45 ms | |
| **P3's internet goes silent** | **5,018-5,023 ms** | **6,176-6,286 ms** |
| W2 (watcher) closes and rejoins | 41-42 ms | |

- **Confirmed**: switching between playing and watching mid-game works and nobody's game pauses. When P4 moved
  to watching, pad D reached no seat; W1 then took seat 4 and pad D worked there in all 8 copies.
- **Confirmed**: asking to play while all 4 seats are taken is refused cleanly ("The input devices requested
  are not available") and the asker stays a watcher.
- **Confirmed**: a player whose game closes (crash or quit) drops out without pausing anyone; their seat is
  free; they rejoin in 1.4 s and get the same seat back by asking for it (`netplay_request_device_pN`).
- **Confirmed**: if a player's internet goes silent without closing, everyone's game freezes ~5 s, then the
  host drops that player and the game carries on. It's RetroArch's fixed limit (`MAX_SERVER_STALL_TIME_USEC`,
  5 s, in netplay_private.h). The silent player's own RetroArch keeps running on its own afterwards ("Netplay
  disconnected"), so the app must notice that and offer to rejoin.
- Closest options for the silent case (design CQ6 says "the game does NOT pause"): (a) accept a one-off ~5 s
  freeze; (b) Strongly inferred: Game Night's relay bridge can spot a silent link sooner (it sees every byte)
  and close it after ~1-2 s, so RetroArch drops the player straight away like a closed game. (b) is not built
  or measured yet.
- **Strongly inferred**: "seat held for 2:00" (CQ6) is app logic. RetroArch has no seat reservation, but the
  app can make the dropped player ask for their old seat when they rejoin, and keep others from asking for it.

## Found on the way
- **Confirmed (fixed, and fixed for the relay test in PR #21)**: the relay bridge's link tasks could be thrown
  away by Python's garbage collector mid-game ("Task was destroyed but it is pending!"), closing friends' links.
  This was the cause of the relay thread's private-way drops (that thread checked its logs and reproduced it).
  For the app's Rust bridge: keep a handle to every link task.
- **Confirmed (test fixed)**: a held button takes a while to show in the watchers' games: up to 508 ms for
  watcher W3 through the relay, ~260-400 ms usually, players 73-283 ms (run 41183819291). Run 41182531780 read
  every copy once at 0.45 s and caught W3 before the button arrived. The check now holds the button until each
  copy shows it (up to 2 s) and records the time. Watchers lagging a fraction of a second is normal for
  RetroArch watchers and doesn't affect players.
- **Confirmed, cause Unknown**: RetroArch sometimes closes by itself with 0xc0000005 (an invalid memory access)
  within about half a second of starting, before or just as it connects. Runs 2-4: the on-this-machine host
  every time plus 3 friends once; run 5: none; run 6: 6 friend starts (W1 twice, W3, P3, P4, W2 twice) across
  both rounds; run 7: 2 (W1, P2). Out of roughly 16-20 starts per run. A second try always worked. Windows
  saved no crash dump, and the debugger hook only covers the host, which hasn't crashed since. For the app:
  start RetroArch again once if it closes in the first few seconds, and show "starting again" rather than an
  error.
- The pretend pads' Xbox slot can't be read on this machine (ViGEm answers 0xe0000014); the test assumes A-D
  are slots 0-3, and the right-seat checks confirm it.

## Not covered (Unknown)
Real PCs and real internet between homes, real controllers, the real Game Night window, sessions longer than a
few minutes with 8 people, NES (fceumm) 4-player (Four Score), and how the lobby UI shares the pad with the game.

## For the app (each its own job, design already approved)
- Game box: way B (borderless window owned by the lobby window, kept over the box); full screen by resizing it;
  RetroArch's full screen hotkey off.
- SNES 3-4 players: write a Snes9x core remap file with the multitap on port 2.
- Seats: give each player `netplay_request_device_pN` for their seat; watchers `netplay_start_as_spectator`;
  switching = RetroArch's NETPLAY_GAME_WATCH command; host `netplay_max_connections = 8`.
- Drop-outs: notice a dead or silent RetroArch and offer rejoin; consider closing silent links early in the bridge.
