#!/usr/bin/env python3
"""CI only (GitHub's Windows machine): does a game start cleanly, with none of RetroArch's own pop-up messages?
(Jayden, 2026-10-31: "disable all the popups ... so it just boots the game cleanly".)

    python popup_test.py <player folder> <work folder> <results folder>

<player folder> is what tools/player/fetch_player.py builds. Nothing is installed or changed outside <work folder>
and <results folder>, and nothing goes to the internet (the two copies play on this machine only).

The test cartridge (make_test_rom.py) draws nothing, so its picture is one flat colour. Anything else in the
game's window is a pop-up. Each copy's window is photographed about 4 times a second, and for each photo we count
the "pop-up pixels": pixels clearly different from the picture's main colour. Three moments, each measured twice,
once with RetroArch's normal settings ("before") and once with Game Night's quiet settings added ("after",
app/src-tauri/src/quiet_retroarch.cfg, the same file the app uses):
  1. boot:    the game starts ("loading", "controller connected" messages).
  2. plug-in: a pretend Xbox pad is plugged in mid-game ("... configured in port" message).
  3. join:    a friend's copy joins over netplay (host and friend both: "netplay: ... joined" messages).
Passes when "after" has no pop-up pixels at all in any moment, and "before" shows pop-ups at boot (which proves the
photos can see them). Results: popups.json (numbers) and the photo with the most pop-up pixels per moment.
"""
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import couch_lobby_test as cl  # noqa: E402  (same command line: player, work, results)
import netplay_test as np  # noqa: E402

from netplay_test import WORK, OUT, say  # noqa: E402

QUIET_FILE = Path(__file__).resolve().parents[2] / "app" / "src-tauri" / "src" / "quiet_retroarch.cfg"
PORT = 55447
THRESHOLD = 40  # how different (0-255, any colour channel) a pixel must be from the main colour to count
results = {"rounds": {}}


def quiet_settings():
    out = {}
    for line in QUIET_FILE.read_text(encoding="utf-8").splitlines():
        k, sep, v = line.partition("=")
        k = k.strip()
        if sep and k and not k.startswith("#"):
            out[k] = v.strip().strip('"')
    return out


def popup_pixels(img):
    """Pixels clearly different from the picture's main colour (the test cartridge's flat screen)."""
    small = img.convert("RGB")
    colours = small.getcolors(small.width * small.height)
    main = max(colours)[1]
    return sum(n for n, c in colours if max(abs(c[i] - main[i]) for i in range(3)) > THRESHOLD)


class Watch:
    """Photographs each copy's game area (inside its window frame) and keeps the worst photo per copy."""

    def __init__(self, label, copies):
        self.label, self.copies = label, copies
        self.worst = {c.name: (0, None) for c in copies}
        self.photos = 0

    def look(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            shot = cl.grab()
            self.photos += 1
            for c in self.copies:
                wins = cl.windows_of(c.proc.pid) if c.proc else []
                if not wins:
                    continue
                x, y, w, h = cl.client_screen_rect(wins[0])
                if w < 32 or h < 32:
                    continue
                crop = shot.crop((x, y, x + w, y + h))
                n = popup_pixels(crop)
                if n > self.worst[c.name][0] or self.worst[c.name][1] is None:
                    self.worst[c.name] = (n, crop)
            time.sleep(0.25)

    def save(self):
        out = {}
        for name, (n, crop) in self.worst.items():
            if crop is not None:
                crop.save(OUT / f"{self.label}-{name}.png")
            out[name] = n
        say(f"  {self.label}: most pop-up pixels in one photo {out} ({self.photos} photos)")
        return out


def run(variant, quiet, rom):
    extra = dict(quiet) if variant == "after" else {}
    host, friend = np.Copy(f"host-{variant}", 55460, 0), np.Copy(f"friend-{variant}", 55461, 1)
    host.write_config(40, extra)
    friend.write_config(600, extra)
    r = {}
    pads = []
    try:
        host.start(rom, ["--host", "--port", str(PORT)])
        w = Watch(f"{variant}-1-boot", [host])
        w.look(7)
        r["boot"] = w.save()

        pads.append(np.plug(f"{variant} (mid-game)")[0])
        w = Watch(f"{variant}-2-plug-in", [host])
        w.look(6)
        r["plug_in"] = w.save()

        friend.start(rom, ["--connect", "127.0.0.1", "--port", str(PORT)])
        w = Watch(f"{variant}-3-join", [host, friend])
        w.look(10)
        r["join"] = w.save()
        joined = "[Netplay] Received input from" in host.log_text() or "[Netplay] Received mode change" in friend.log_text()
        r["friend_joined_log"] = joined
        say(f"  friend joined (from the logs): {joined}")
    finally:
        for c in (friend, host):
            c.quit()
        pads.clear()  # unplugs the pretend pad
        for c in (host, friend):
            (OUT / f"{c.name}-retroarch.log").write_text(c.log_text(), encoding="utf-8")
    return r


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    rom = WORK / "test.nes"
    subprocess.run([sys.executable, str(Path(__file__).parent / "make_test_rom.py"), str(rom)], check=True)
    quiet = quiet_settings()
    say(f"Game Night's quiet settings ({QUIET_FILE.name}): {quiet}")
    results["quiet"] = quiet
    problems = []
    try:
        for variant in ("before", "after"):
            say(f"\n=== {variant}: {'RetroArch normal settings' if variant == 'before' else 'with Game Night quiet settings'} ===")
            results["rounds"][variant] = run(variant, quiet, rom)
            time.sleep(2)
    except Exception:
        traceback.print_exc()
        problems.append("the test itself stopped with an error (see above)")
    before, after = results["rounds"].get("before", {}), results["rounds"].get("after", {})
    if before and not any(before.get("boot", {}).values()):
        problems.append("BEFORE showed no pop-ups at boot, so the photos may not be able to see them (test not valid)")
    for moment in ("boot", "plug_in", "join"):
        for name, n in after.get(moment, {}).items():
            if n > 0:
                problems.append(f"AFTER: {n} pop-up pixels in {name}'s window at '{moment}'")
    if after and not after.get("friend_joined_log"):
        problems.append("AFTER: the friend's copy didn't join, so the 'join' moment wasn't really tested")
    results["problems"] = problems
    (OUT / "popups.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    say("\n" + json.dumps({k: results["rounds"].get(k) for k in ("before", "after")}, indent=2))
    if problems:
        for p in problems:
            print(f"::error::{p}", flush=True)
        sys.exit(1)
    say("\nPASS: with Game Night's settings no RetroArch pop-ups showed at boot, on plug-in or when a friend joined")


if __name__ == "__main__":
    main()
