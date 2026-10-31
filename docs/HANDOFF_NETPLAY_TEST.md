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
machine → relay → same machine: the relay's distance counts twice, like two friends who both live near
the GitHub machine. Runs: 41167800601 (run 1, commit ec2c5a4) and 41169114880 (run 2, commit 5871137).

## Two ways to use the relay
- **Listed** (stock RetroArch, `relay-listed-nyc`): `netplay_use_mitm_server` + `netplay_public_announce`. The host
  asks libretro's lobby for the relay, gets a session, and lists the game in libretro's **public** game list; the
  friend reads the session from that list and joins (`--connect <relay> --port 55435 --mitm-session=<id>`).
- **Private** (`relay-private-*`): `TunnelBridge` in the test holds the relay session for the host (same messages
  RetroArch's host sends: RATS/RATL/RATA/RATP, read from RetroArch 1.22.2 `netplay_frontend.c`) and hands the
  friend the session id directly. The host copy only listens on 127.0.0.1. **Nothing is listed anywhere.**
  In the app this bridge would live in the Rust side and the session id would go through Game Night's own server.

## Results
| Round | Plain connect to relay (median) | Joined after | Extra delay for the other player (median, both pads) | Frames compared / different |
|---|---|---|---|---|
| direct (same machine) | - | 0.6 s | 0-15 ms | 4,578 / 0 and 5,295 / 0 |
| pretend 50±20 ms each way | - | 0.6 s | 33-95 ms | 4,582 / 0 and 5,279 / 0 |
| listed, New York | 75 ms | 1.1 s (listed 5.7-6.3 s after start) | 65-80 ms | run 2: 5,340 / 0 |
| private, New York | 45 / 79 ms | 0.8 / 1.1 s | 48-76 ms | run 1: 4,673 / 0; run 2: dropped at ~60 s (below) |
| private, Madrid | 120 / 158 ms | 1.6 / 1.9 s | 114-146 ms | 1,729 / 0 and 1,888 / 0 |
| private, Sao Paulo | 155 / 190 ms | 1.9 / 2.1 s | 157-161 ms | 1,721 / 0 and 1,880 / 0 |
| private, Singapore | 203 / 190 ms | 2.7 / 2.2 s | 162-224 ms | 1,768 / 0 and 1,862 / 0 |

"Extra delay for the other player" = how much later a press shows in the other player's game than in the presser's
own game (accurate to about one frame). The presser's own game showed a press after ~45-60 ms in every round
(pad + one or two frames + reading), relay or not: netplay never delays your own buttons.

- **Confirmed**: both ways work through libretro's relay with stock RetroArch 1.22.2 and no ports opened. Every
  button reached the right player, button histories matched, 0 frames out of sync in every round that stayed
  connected (8 relay rounds over 2 runs).
- **Confirmed**: leave and rejoin through the same private session: 10 of 10 rejoins in 0.6-1.1 s, friend still
  player 2 each time.
- **Confirmed**: speed. Relay rounds ran as fast as the yardstick (two unconnected copies), within a few percent.
- **Confirmed (run 2)**: one drop. `relay-private-nyc` disconnected ~60 s into play with no error from RetroArch
  ("has disconnected" / "Netplay disconnected"); after that the two games ran on their own, so 1,711 frames
  differed. That is a dropped connection, not a sync bug: frames matched up to the drop. **Unknown**: whether
  the relay, the internet or the test's bridge closed it. Commit 8ff6ccf logs how every relay link ends and adds
  two 5-minute New York rounds (listed and private) to tell these apart; it has **not run yet** (see below).
- **Confirmed**: the listed way puts the host in libretro's public list, readable by anyone at
  `lobby.libretro.com/list`, with nickname, game file name, country and the host's **home internet address**
  (field `ip`). Seen on our own test entry and on other people's live entries.
- **Confirmed**: a password doesn't fit Game Night. RetroArch's joining side ignores `netplay_password` from its
  settings and always pops up a box to type it (`netplay_handshake_init`, `menu_input_dialog_start`). Run 1's
  listed round stalled on that box. The listed round now has no password and `netplay_max_connections=1`.
- **Strongly inferred**: delay grows with distance to the relay, about one extra relay round trip. For friends near
  each other, the nearest relay (New York for the US east) adds roughly 50-80 ms, similar to the pretend 50 ms
  round. Singapore-level distance adds ~200 ms, which most players feel in action games.
- **Unknown**: the delay between two real homes (their own internet adds to this), which relay is nearest to
  Jayden and his friends, and long sessions (rounds were 30-90 s).

## Suggestion for the app (needs Jayden's OK)
Use the private way: Game Night's Rust side holds the relay session and passes the session id to the friend
through Game Night's own server. Nothing public, no home addresses listed, no password box, no router changes.

## Blocked
From 04:55 UTC on 2026-10-31 GitHub refuses to start any job in this repository: "The job was not started because
recent account payments have failed or your spending limit needs to be increased" (all workflows, all branches).
Jayden needs to check GitHub → Settings → Billing and plans. Until then the 5-minute rounds can't run.
