#!/usr/bin/env python3
"""CI only (GitHub's Windows machine): drives the real Game Night app with a pretend Xbox controller.

    python pad_test.py <GameNight.exe> <Game Night folder> <screenshot folder>

Uses ViGEmBus (installed on the CI machine only) through vgamepad. Like Jayden's PC, two pads are
plugged in: a "dead" one in the first slot that is never pressed (his Razer keyboard's hidden pad),
and the one we press in the second slot (his real Xbox pad). Each step presses a button, then reads
Game Night's own pads.txt log to see what the menus did, and takes a screenshot.
Any step that doesn't do what it should fails the test.
"""
import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

import vgamepad as vg

EXE, ROOT, SHOTS = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
TOOLS = Path(__file__).parent
CACHE = Path(os.environ["LOCALAPPDATA"]) / "xyz.jjsnas.gamenight"
PADS_LOG = CACHE / "player" / "logs" / "pads.txt"
B = vg.XUSB_BUTTON

failures = []


def say(m):
    print(m, flush=True)


def in_front():
    """The title of the window Windows has in front (presses only count when it's Game Night)."""
    user32 = ctypes.windll.user32
    w = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(w, buf, 256)
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(w, ctypes.byref(pid))
    return f'"{buf.value}" (process {pid.value})'


def log_lines():
    try:
        return PADS_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return []


def screenshot(name):
    out = SHOTS / f"{name}.png"
    subprocess.run(["pwsh", "-NoProfile", "-File", str(TOOLS / "screenshot.ps1"), str(out)], check=False)


def press(pad, button, hold=0.15):
    pad.press_button(button=button)
    pad.update()
    time.sleep(hold)
    pad.release_button(button=button)
    pad.update()


def step(pad, name, button, index, want_screen, want_focus=None):
    """Press, wait, then check the menus' own "after button N" note."""
    before = len(log_lines())
    say(f"\n--- {name}: window in front {in_front()}")
    press(pad, button)
    time.sleep(1.5)
    new = log_lines()[before:]
    for line in new:
        say(f"  | {line}")
    screenshot(name)
    after = [l for l in new if l.startswith(f"menus: after button {index}:")]
    if not after:
        failures.append(f"{name}: the menus never saw button {index}")
        say(f"  FAIL: the menus never saw button {index}")
        return
    got = after[-1]
    ok = f"screen: {want_screen};" in got and (want_focus is None or want_focus.lower() in got.lower())
    if ok:
        say(f"  ok: {got}")
    else:
        failures.append(f"{name}: wanted screen {want_screen}, focus {want_focus!r}; got {got}")
        say(f"  FAIL: wanted screen {want_screen}, focus {want_focus!r}")


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    say("plugging in two pretend Xbox pads (first one stays idle, like Jayden's Razer keyboard)")
    def plug(vid, pid):
        # Windows' Xbox 360 driver may only accept the standard Xbox 360 id (045e:028e).
        try:
            return vg.VX360Gamepad(vid=vid, pid=pid)
        except RuntimeError as e:
            say(f"  couldn't plug a pad with id {vid:04x}:{pid:04x} ({e}); using 045e:028e")
            return vg.VX360Gamepad()

    dead = plug(0x046D, 0xC21D)
    time.sleep(1)
    pad = plug(0x045E, 0x02FF)
    time.sleep(2)
    say(f"pads plugged: idle one index {dead.get_index()}, pressed one index {pad.get_index()}")

    env = dict(os.environ, GAMENIGHT_E2E="menus", GAMENIGHT_UPDATE_URL="http://127.0.0.1:9/")
    app = subprocess.Popen([EXE], env=env)
    try:
        # Wait for the menus to start and reach the main menu.
        for _ in range(60):
            time.sleep(1)
            if any("first pad_state answer" in l for l in log_lines()):
                break
        time.sleep(4)
        say(f"window in front once open: {in_front()}")
        say("pads.txt so far:")
        for line in log_lines():
            say(f"  | {line}")
        screenshot("0-main-menu")

        step(pad, "1-dpad-down", B.XUSB_GAMEPAD_DPAD_DOWN, 13, "menu", "settings")
        step(pad, "2-dpad-up", B.XUSB_GAMEPAD_DPAD_UP, 12, "menu", "play")
        step(pad, "3-a-opens-play", B.XUSB_GAMEPAD_A, 0, "library")
        step(pad, "4-b-goes-back", B.XUSB_GAMEPAD_B, 1, "menu")
    finally:
        app.kill()
        say("\nwhole pads.txt:")
        for line in log_lines():
            say(f"  | {line}")

    if failures:
        for f in failures:
            print(f"::error::controller test: {f}", flush=True)
        sys.exit(1)
    say("\nthe pretend controller drove the main menu: down, up, A opens Play, B goes back")


main()
