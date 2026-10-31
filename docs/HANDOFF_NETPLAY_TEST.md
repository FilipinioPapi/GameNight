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
