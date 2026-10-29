#!/usr/bin/env python3
"""CI only (GitHub's Windows machine): drives the real Game Night app with a pretend Xbox controller.

    python pad_test.py menus <GameNight.exe> <Game Night folder> <screenshot folder>
    python pad_test.py game  <GameNight.exe> <Game Night folder> <screenshot folder>

Uses ViGEmBus (installed on the CI machine only) through vgamepad. Like Jayden's PC, two pads are
plugged in: a "dead" one in the first slot that is never pressed (his Razer keyboard's hidden pad),
and the one we press in the second slot (his real Xbox pad). Each step presses a button, then reads
Game Night's own pads.txt log to see what the menus did, and takes a screenshot.
"menus" drives the main menu. "game" presses a button in the menus (the way a player picks their
controller), lets Game Night start the test game, then holds buttons and asks the game itself (through
RetroArch's local command port, on in this test build only) which player's buttons are down.
Any step that doesn't do what it should fails the test.
"""
import ctypes
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import vgamepad as vg

MODE, EXE, ROOT, SHOTS = sys.argv[1], sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
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


def plug_pads():
    """Two pretend pads, like Jayden's PC: an idle one first, then the one we press."""
    def plug(vid, pid):
        # Windows' Xbox 360 driver may only accept the standard Xbox 360 id (045e:028e).
        try:
            return vg.VX360Gamepad(vid=vid, pid=pid)
        except RuntimeError as e:
            say(f"  couldn't plug a pad with id {vid:04x}:{pid:04x} ({e}); using 045e:028e")
            return vg.VX360Gamepad()

    say("plugging in two pretend Xbox pads (first one stays idle, like Jayden's Razer keyboard)")
    dead = plug(0x046D, 0xC21D)
    time.sleep(1)
    pad = plug(0x045E, 0x02FF)
    time.sleep(2)
    say(f"pads plugged: idle one index {dead.get_index()}, pressed one index {pad.get_index()}")
    return dead, pad


def start_app(mode, reader=""):
    env = dict(os.environ, GAMENIGHT_E2E=mode, GAMENIGHT_E2E_READER=reader, GAMENIGHT_E2E_ROOT=str(ROOT), GAMENIGHT_UPDATE_URL="http://127.0.0.1:9/")
    app = subprocess.Popen([EXE], env=env)
    # Wait for the menus to start and reach the main menu.
    for _ in range(60):
        time.sleep(1)
        if any("first pad_state answer" in l for l in log_lines()):
            break
    time.sleep(4)
    say(f"window in front once open: {in_front()}")
    return app


def dump_log(title):
    say(title)
    for line in log_lines():
        say(f"  | {line}")


def menus():
    dead, pad = plug_pads()
    app = start_app("menus")
    try:
        dump_log("pads.txt so far:")
        screenshot("0-main-menu")
        step(pad, "1-dpad-down", B.XUSB_GAMEPAD_DPAD_DOWN, 13, "menu", "settings")
        step(pad, "2-dpad-up", B.XUSB_GAMEPAD_DPAD_UP, 12, "menu", "play")
        step(pad, "3-a-opens-play", B.XUSB_GAMEPAD_A, 0, "library")
        step(pad, "4-b-goes-back", B.XUSB_GAMEPAD_B, 1, "menu")
    finally:
        app.kill()
        dump_log("\nwhole pads.txt:")
    return "the pretend controller drove the main menu: down, up, A opens Play, B goes back"


def ask_game(command):
    """One RetroArch command on this PC's local command port; returns its answer (or '')."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(2)
        s.sendto(command.encode(), ("127.0.0.1", 55355))
        try:
            return s.recv(4096).decode(errors="replace").strip()
        except OSError as e:
            return f"(no answer: {e})"


def buttons():
    """The test game's RAM: $10 = player 1's buttons, $11 = player 2's (A=0x80 ... Right=0x01)."""
    for cmd in ("READ_CORE_MEMORY 10 2", "READ_CORE_RAM 10 2"):
        answer = ask_game(cmd)
        parts = answer.split()
        if len(parts) == 4 and parts[0] == cmd.split()[0]:
            try:
                return int(parts[2], 16), int(parts[3], 16), answer
            except ValueError:
                pass
        say(f"  ({cmd} -> {answer})")
    return None, None, answer


def hold_and_read(pad, button, name):
    pad.press_button(button=button)
    pad.update()
    time.sleep(0.6)
    p1, p2, raw = buttons()
    screenshot(name)
    pad.release_button(button=button)
    pad.update()
    time.sleep(0.4)
    say(f"--- {name}: player 1 {p1 if p1 is None else f'{p1:#04x}'}, player 2 {p2 if p2 is None else f'{p2:#04x}'} ({raw}); in front {in_front()}")
    return p1, p2


# What each Xbox button should be in an NES game with RetroArch's standard layout (the test game keeps
# player 1's NES buttons in $10: A=0x80 B=0x40 Select=0x20 Start=0x10 Up=0x08 Down=0x04 Left=0x02 Right=0x01).
# Xbox A is the bottom face button, which is the NES B spot, and Xbox B is the NES A spot.
NES = [
    ("A", "XUSB_GAMEPAD_A", 0x40), ("B", "XUSB_GAMEPAD_B", 0x80),
    ("View", "XUSB_GAMEPAD_BACK", 0x20), ("Menu", "XUSB_GAMEPAD_START", 0x10),
    ("Up", "XUSB_GAMEPAD_DPAD_UP", 0x08), ("Down", "XUSB_GAMEPAD_DPAD_DOWN", 0x04),
    ("Left", "XUSB_GAMEPAD_DPAD_LEFT", 0x02), ("Right", "XUSB_GAMEPAD_DPAD_RIGHT", 0x01),
]


def game(idle_pad, reader=""):
    """Plays the test game. idle_pad: also plug an idle pad first (like Jayden's PC), or just the one we use.
    reader "dinput": make RetroArch use its "dinput" reader, which Game Night picks on Jayden's PC."""
    tag = ("two-pads" if idle_pad else "one-pad") + (f"-{reader}" if reader else "")
    say(f"\n##### game test, {tag} #####")
    if idle_pad:
        dead, pad = plug_pads()
    else:
        dead, pad = None, vg.VX360Gamepad(vid=0x045E, pid=0x02FF)
        time.sleep(2)
        say(f"one pretend Xbox pad plugged in, index {pad.get_index()}")
    for f in (CACHE / "player" / "logs" / "retroarch.log",):
        f.unlink(missing_ok=True)
    app = start_app("padgame", reader)
    try:
        say("pressing A in the menus on the pad we use (Game Night then starts the test game)")
        press(pad, B.XUSB_GAMEPAD_A)
        for _ in range(30):  # wait for the game to answer on its command port
            time.sleep(1)
            if not ask_game("VERSION").startswith("(no answer"):
                break
        time.sleep(3)
        say(f"game version answer: {ask_game('VERSION')}; in front {in_front()}")
        controllers = CACHE / "player" / "logs" / "controllers.txt"
        say("controllers.txt (what Game Night told the game):")
        for line in controllers.read_text(errors="replace").splitlines() if controllers.exists() else ["(missing)"]:
            say(f"  | {line}")
        cfg = Path(os.environ["APPDATA"]) / "xyz.jjsnas.gamenight" / "player" / "retroarch.cfg"
        if cfg.exists():
            say("controller lines in retroarch.cfg:")
            for line in cfg.read_text(errors="replace").splitlines():
                if line.startswith(("input_player", "input_joypad_driver", "input_max_users", "network_cmd")):
                    say(f"  | {line}")

        p1, p2, raw = buttons()
        say(f"--- nothing pressed: player 1 {p1}, player 2 {p2} ({raw})")
        if p1 is None:
            failures.append(f"{tag}: couldn't ask the game what it sees ({raw})")
        else:
            wrong = []
            for name, button, want in NES:
                got, _ = hold_and_read(pad, getattr(B, button), f"game-{tag}-hold-{name}")
                if got != want:
                    wrong.append(f"{name} gave {got if got is None else f'{got:#04x}'} (wanted {want:#04x})")
            if dead is not None:
                hold_and_read(dead, B.XUSB_GAMEPAD_A, f"game-{tag}-idle-pad-A")
            if wrong:
                failures.append(f"{tag}: player 1's buttons in the game are wrong: " + "; ".join(wrong))
            else:
                say(f"  ok: every button reached player 1 as the right NES button ({tag})")
        ask_game("QUIT")
        try:
            app.wait(30)
        except subprocess.TimeoutExpired:
            pass
    finally:
        if app.poll() is None:
            app.kill()
        subprocess.run(["taskkill", "/F", "/IM", "retroarch.exe"], capture_output=True)
        log = CACHE / "player" / "logs" / "retroarch.log"
        if log.exists():
            say("RetroArch's controller lines:")
            for line in log.read_text(errors="replace").splitlines():
                if any(k in line for k in ("Input", "input", "Autoconf", "joypad", "XInput", "DInput", "Network", "command")):
                    say(f"  | {line}")
        dump_log("\nwhole pads.txt:")
        del pad, dead
        time.sleep(2)


def games():
    game(idle_pad=False)
    game(idle_pad=True)
    game(idle_pad=True, reader="dinput")
    return "the game's player 1 got every button, right, from the pad used in the menus"


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    done = {"menus": menus, "game": games}[MODE]()
    if failures:
        for f in failures:
            print(f"::error::controller test ({MODE}): {f}", flush=True)
        sys.exit(1)
    say(f"\n{done}")


main()
