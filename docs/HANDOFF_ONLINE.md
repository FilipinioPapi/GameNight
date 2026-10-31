# Handoff: online co-op (NES + SNES first)

Started 2026-10-31 in the thread "Plan quickest online co-op for NES and SNES". Read `docs/STATUS.md` first.

## Jayden's priorities (his words, 2026-10-31)
- Stability and proven function come first: "this would be the foundation for everything". No rush for a date.
- Sign-in: being in his Discord server is enough. The Game Night role is optional (PR #12).
- Go online through the domains he already has, play.jjsnas.xyz and updates.jjsnas.xyz, with no new NPM hosts.
  Nothing may break or get crossed with Roof Rage (utmost importance).

## The plan (approved shape: build in proven layers)
1. **Two players, one test machine (approved, next).** On GitHub's Windows runner: two copies of the pinned RetroArch
   (fceumm, then snes9x), one netplay host and one client on the same machine, each with its own pretend (ViGEm) pad.
   Prove: they connect, stay in sync, and each pad's presses reach the right player in the game. Use logs plus a test
   cartridge that reports players 1 and 2 (extend `tools/e2e/make_test_rom.py`).
   Build on the controller thread's branch `claude/project-thread-7arnv6` (has `tools/e2e/pad_test.py`, the ViGEm and
   Xbox driver setup in CI, and a test ROM that reports player 1's buttons). It's not merged yet: it's waiting on
   Jayden's real-controller check.
2. **Room codes.** Host picks a game, server makes a code, friend's app downloads the same file and joins. The join
   screen needs a mockup and Jayden's OK first (follow the smooth-menus style).
3. **Going online.** Game Night gets its own path, play.jjsnas.xyz/gamenight/, as one NPM custom location on the existing
   host. The server needs base-path support. Jayden does the NPM steps. Before and after: check Roof Rage's addresses
   answer exactly the same. Then one real test with a friend (write up the test request first).
4. **Later.** Controller handoff, rotation up to 6, spectators, group saves.

## Open questions
- **How games connect online** (Jayden: decide after step 1). The options are libretro's free public relay (no ports
  opened) or our own relay on the NAS. Game traffic can't go through NPM's web proxy.
- **What play.jjsnas.xyz does for Roof Rage** (Unknown). Jayden was asked for permission to read Roof Rage's setup notes
  (read only) or to describe it.

## Facts checked
- Confirmed: the app switches netplay off today (`games.rs` `retroarch_config`: `netplay_nat_traversal=false`,
  `network_cmd_enable=false`).
- Confirmed: the server is home-network only (`account.rs` `DEFAULT_SERVER = http://192.168.1.33:8094`).
- Strongly inferred: netplay needs the same ROM file and the same core version on both PCs. The pinned RetroArch and
  server downloads should give us that, but step 1 must check it.
