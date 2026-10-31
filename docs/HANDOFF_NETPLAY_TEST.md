# Online co-op step 1: two players on one test machine (2026-10-31)

Part of the online co-op plan (`docs/HANDOFF_ONLINE.md`, on PR #12's branch). Labels: **Confirmed** = measured,
**Strongly inferred** = follows from measurements, **Unknown** = not measured yet.

## What the test does
`.github/workflows/netplay.yml` runs on GitHub's Windows machine on every push that touches the test. It does not
build or change the Game Night app, and nothing goes to the internet.
- `tools/e2e/make_netplay_rom.py`: a tiny NES test cartridge. Every frame it reads both controllers and keeps a frame
  number, a running "fingerprint" of every frame so far, the last 256 fingerprints and the last 256 button changes in
  its RAM. `check_netplay_rom.py` checks the cartridge on a 6502 simulator first (1,000 frames, every byte).
- `tools/e2e/netplay_test.py`: two pretend Xbox pads (A and B), two copies of the pinned RetroArch 1.22.2 with fceumm.
  The "host" copy reads only pad A and is player 1; the "friend" copy reads only pad B and joins as player 2 over the
  machine's own loopback address. Netplay's public lobby, NAT punching and relay servers are off. RetroArch's own
  desync repair (`netplay_check_frames`) is off, so a desync can't be quietly patched.
- Each round: connect; hold every NES button on each pad and read players 1 and 2 in both copies; 90 seconds of
  random presses on both pads while comparing every finished frame's fingerprint between the copies; then compare
  the whole button-change history, check each player's states came only from their own pad, and re-add the
  fingerprint chain in Python.
- Rounds: "direct", and "delayed" through a relay in the test that holds data back 50 ms ± 20 ms each way
  (RetroArch measured the ping as ~150 ms).
- A yardstick for speed: the same two copies side by side, not connected.
- Results (numbers, both RetroArch logs, button histories, screenshots) are the `netplay-results` download of each run.

## Results: run 41165197880 (commit ab46317), all green
| | direct | delayed (50 ± 20 ms each way) |
|---|---|---|
| Connected (friend took the host's game) | 0.3 s | 0.6 s |
| Every button on the right player, in both copies | yes (16 of 16 + both at once) | yes |
| Frames compared / played | 4,296 / 4,103 | 4,293 / 4,097 |
| Frames out of sync | **0** | **0** |
| Button changes, host vs friend | 971 = 971, histories identical | 858 = 858, identical |
| Any player 1 state not from pad A (or 2 not from B) | none | none |
| Speed, connected pair (two unconnected copies: 45.2) | 45.6 / 45.5 | 45.5 / 45.5 |
| Frame gap between copies, biggest / average | 4 / 2.5 | 6 / 1.4 |

- **Confirmed**: connect, sync and right-player all pass, straight and with internet-like delay. Same in runs
  41163295993 and 41164417046 (0 different frames there too).
- **Confirmed**: fceumm drops Up+Down and Left+Right held together (its default "Allow opposing directions" is off).
  Run 2's "crossed buttons" were exactly that; the test now expects it.
- **Strongly inferred**: netplay itself costs no speed. The connected pair runs as fast as two unconnected copies; the
  45-59 frames a second seen across runs is the CI machine (no graphics card, two windows drawn in software, no sound
  so a plain speed limit paces it). **Unknown**: speed on real PCs with sound pacing.

## Not covered yet (Unknown)
- SNES (snes9x). Same test with a SNES test cartridge is the next small job.
- Two different PCs over the real internet, NAT/routers, a relay server, and Game Night's own app launching netplay
  (today the app switches netplay off: `games.rs` `retroarch_config`).
- Real Xbox/DualSense pads and Jayden's idle Razer pad (the controller thread's real-pad check covers player 1).
- Long sessions (rounds are 90 s; `workflow_dispatch` takes a longer time for a soak run once this is on main).

## Settings that mattered (for when the app turns netplay on)
`netplay_public_announce=false`, `netplay_nat_traversal=false`, `netplay_use_mitm_server=false` (nothing public),
`pause_nonactive=false` (a window not in front keeps playing), each copy's player 1 bound to its own pad
(`input_player1_joypad_index`), separate `network_cmd_port`s. The client's own pad goes to the player netplay gives it
(RetroArch reads its local port 1 for that player, `get_self_input_state`).

## Decision (Jayden, 2026-10-31)
First real friend test goes through **libretro's public relay** (no router or NAS changes). Measure delay and
reliability through it; those numbers decide whether our own relay on the NAS is worth building later.

# Online co-op step 2: libretro's public relay, measured (2026-10-31, PR #16)

Same test, same NES cartridge and checks, now also through libretro's relay servers over the real internet.
Both copies still run on one GitHub Windows machine (a US data centre), so every relay round is
machine -> relay -> same machine: the relay's distance counts twice, like two friends who both live near
the GitHub machine. Runs: 41167800601 (1), 41169114880 (2), 41170468355 (3, re-run), **41174375748 (4, all green,
commit f55c16a)**.

## Two ways to use the relay
- **Listed** (stock RetroArch, `relay-listed-*`): `netplay_use_mitm_server` + `netplay_public_announce`. The host
  asks libretro's lobby for the relay, gets a session, and lists the game in libretro's **public** game list; the
  friend reads the session from that list and joins (`--connect <relay> --port 55435 --mitm-session=<id>`).
- **Private** (`relay-private-*`): `TunnelBridge` in the test holds the relay session for the host (same messages
  RetroArch's host sends: RATS/RATL/RATA/RATP, read from RetroArch 1.22.2 `netplay_frontend.c`) and hands the
  friend the session id directly. The host copy only listens on 127.0.0.1. **Nothing is listed anywhere.**
  In the app this bridge would live in the Rust side and the session id would go through Game Night's own server.
- **Decision (Jayden, 2026-10-31 06:11)**: use the private way, "if it doesn't break functionality".

## Results
| Round | Plain connect to relay (median) | Joined after | Extra delay for the other player (median) | Frames compared, different |
|---|---|---|---|---|
| direct (same machine) | - | 0.3-0.6 s | 0-16 ms | ~5,300 per run, 0 |
| pretend 50 +/- 20 ms each way | - | 0.6-0.8 s | 33-95 ms | ~5,300 per run, 0 |
| listed, New York (90 s) | 49-75 ms | 0.8-1.1 s (listed after ~6 s) | 33-80 ms | 3 runs, 0 |
| private, New York (90 s + 5 rejoins) | 41-79 ms | 0.8-1.1 s | 33-127 ms | 3 of 4 runs 0; run 2 dropped (below) |
| listed, New York, **5 minutes** | 48-77 ms | 0.8 s | 33-66 ms | 17,404 and 17,390, **0** (runs 3, 4) |
| private, New York, **5 minutes** | 77 ms | 1.1 s | 65-95 ms | 17,496, **0** (run 4; run 3: test crash, below) |
| private, Madrid (30 s) | 119-158 ms | 1.6-1.9 s | 113-146 ms | 4 runs, 0 |
| private, Sao Paulo (30 s) | 155-190 ms | 1.9-2.2 s | 143-161 ms | 4 runs, 0 |
| private, Singapore (30 s) | 190-222 ms | 2.2-2.7 s | 160-224 ms | 4 runs, 0 |

"Extra delay for the other player" = how much later a press shows in the other player's game than in the presser's
own game (accurate to about one frame, ~17 ms, so single numbers jump around). The presser's own game showed a
press after ~45-60 ms in every round, relay or not: netplay never delays your own buttons.

- **Confirmed**: both ways work through libretro's relay with stock RetroArch 1.22.2 and no ports opened. Every
  button reached the right player, button histories matched, and there were 0 frames out of sync in every round
  that stayed connected. That includes both 5-minute rounds (about 17,400 frames each).
- **Confirmed**: the private way works as well as the listed way. Run 4: same sync, same speed, same delay range,
  over 5 minutes and in the short rounds.
- **Confirmed**: leave and rejoin through the same private session: 20 of 20 rejoins in 0.5-1.1 s (4 runs), and
  the friend was still player 2 each time.
- **Confirmed**: speed. Relay rounds ran as fast as two unconnected copies (within ~4%).
- **Confirmed**: in runs 3 and 4 the relay never closed a connection itself. Every link ended only when the test
  ended it (the bridge logs who closes each link).
- **Unknown, seen once each**: (a) run 2, `relay-private-nyc` disconnected ~60 s into play with no RetroArch
  error; frames matched up to the drop, and after it the two games ran on their own (1,711 frames differed). That
  run had no link logging yet, so the cause is unknown: the relay, the internet or the bridge. (b) Run 3, the 5-minute
  private round stopped after ~30 s with `OSError: [WinError 10022]` raised inside the test's own Python code
  (no traceback was recorded then; run 4 records one, and it didn't happen again). Neither happened in runs 3-4's
  other rounds or in run 4 at all. Watch for them in the app's own tests.
- **Confirmed**: the listed way puts the host in libretro's public list, readable by anyone at
  `lobby.libretro.com/list`, with nickname, game file name, country and the host's **home internet address**
  (field `ip`). Seen on our own test entry and on other people's live entries.
- **Confirmed**: a password doesn't fit Game Night. RetroArch's joining side ignores `netplay_password` from its
  settings and always pops up a box to type it (`netplay_handshake_init`, `menu_input_dialog_start`). Run 1's
  listed round stalled on that box. The listed rounds now use no password and `netplay_max_connections=1`.
  The private way needs no password: the 12-byte session id is the secret, shared only through Game Night.
- **Strongly inferred**: delay grows with distance to the relay, about one extra relay round trip. For friends near
  each other and near a relay, the relay adds roughly 50-80 ms, like the pretend 50 ms round. At Singapore-level
  distance it adds ~200 ms, which most players feel in action games.
- **Unknown**: delay between two real homes (their own internet adds to this), which relay is nearest to Jayden
  and his friends, sessions longer than 5 minutes, and real controllers.

## Next (for the app; one job each)
- Rust side: hold the relay session (port of `TunnelBridge`), start RetroArch as host on 127.0.0.1 only, pass the
  session id to the friend through Game Night's own server (needs the server online, `docs/HANDOFF_ONLINE.md`).
- The join screen needs a mockup and Jayden's OK first.
- SNES (snes9x) version of this test.

## Update: the "private way" drops were a test bug (2026-10-31, PR #21)
- **Confirmed**: the two private-way drops (runs 41169114880 and 41178763017) came from the test's own bridge, not
  from libretro's relay. Python's asyncio holds tasks only weakly, and `TunnelBridge` didn't keep the link
  task, so the garbage collector could throw a live link away mid-game. Both runs print "Task was destroyed but
  it is pending! ... TunnelBridge.open_link()" at the moment of the drop. Locally, forcing `gc.collect()` killed
  a link with the old code; with the fix (link tasks kept in `self.tasks`) it survives. Found together with the
  Couch Play lobby thread, which hit the same thing.
- **Confirmed**: with the fix, hand-started run 41181226222 had every relay round clean: listed and private
  New York (90 s and 5 minutes, ~17,300 frames each), Madrid, Sao Paulo and Singapore, plus 5 of 5 rejoins.
  0 different frames and no drops.
- **For the app's Rust port**: keep a handle to every link task, and never let one be dropped while it runs.
- Workflow change: pushes and merges run only the local rounds (`direct`, `delayed`). The relay rounds run when
  started by hand (Actions > Online co-op test > Run workflow) and are reported as warnings.
- Test fixes: a history entry past the game's final change count is dropped. Run 41178763017's "fingerprint chain"
  failure came from one such entry, while both games agreed at the end. History entries corrected by a later
  read are reported (`history_corrections`, cause Unknown). The speed floor for local rounds is 90%: measured
  94-97% of two unconnected copies at ~59 frames a second.
