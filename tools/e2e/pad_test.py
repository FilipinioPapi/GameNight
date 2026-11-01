#!/usr/bin/env python3
"""CI only (GitHub's Windows machine): drives the real Game Night app with a pretend Xbox controller.

    python pad_test.py menus <GameNight.exe> <Game Night folder> <screenshot folder>
    python pad_test.py game  <GameNight.exe> <Game Night folder> <screenshot folder>
    python pad_test.py ingame <GameNight.exe> <Game Night folder> <screenshot folder>

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
import json
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


def front_is_game():
    """True when the window in front belongs to RetroArch (the game player)."""
    user32 = ctypes.windll.user32
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid.value}", "/FO", "CSV", "/NH"], capture_output=True, text=True)
    return "retroarch.exe" in out.stdout.lower()


def game_night_minimized(pid):
    """True when Game Night's visible main window is minimized."""
    user32 = ctypes.windll.user32
    found = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def each(hwnd, _):
        h = ctypes.c_void_p(hwnd)
        p = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        buf = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h, buf, 64)
        if p.value == pid and buf.value == "Game Night":
            found.append(bool(user32.IsIconic(h)))
        return True

    user32.EnumWindows(proc(each), 0)
    say(f"Game Night's window minimized: {found}")
    return any(found)


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
        # The main menu is a row of cards (LIBRARY, COUCH PLAY, SETTINGS, QUIT); the picked one grows.
        step(pad, "1-dpad-right", B.XUSB_GAMEPAD_DPAD_RIGHT, 15, "menu", "focused: button \"COUCH PLAY")
        step(pad, "2-dpad-right", B.XUSB_GAMEPAD_DPAD_RIGHT, 15, "menu", "focused: button \"SETTINGS")
        step(pad, "3-dpad-left", B.XUSB_GAMEPAD_DPAD_LEFT, 14, "menu", "focused: button \"COUCH PLAY")
        step(pad, "4-dpad-left", B.XUSB_GAMEPAD_DPAD_LEFT, 14, "menu", "focused: button \"LIBRARY")
        step(pad, "5-a-opens-library", B.XUSB_GAMEPAD_A, 0, "library")
        step(pad, "6-b-goes-back", B.XUSB_GAMEPAD_B, 1, "menu", "focused: button \"LIBRARY")
    finally:
        app.kill()
        dump_log("\nwhole pads.txt:")
    return "the pretend controller drove the main menu: right, right, left, left, A opens the Library, B goes back"


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
    for f in (CACHE / "player" / "logs" / "retroarch.log", ROOT / "e2e-result.json"):
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
        front = in_front()
        say(f"game version answer: {ask_game('VERSION')}; in front {front}")
        # Seen from outside the app: the game's window is in front and Game Night is minimized.
        if not front_is_game():
            failures.append(f"{tag}: the game wasn't the window in front ({front})")
        if not game_night_minimized(app.pid):
            failures.append(f"{tag}: Game Night wasn't minimized while the game ran")
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
        # Game Night reports whether it came back to the front once the game closed.
        result = ROOT / "e2e-result.json"
        window = json.loads(result.read_text()).get("window") if result.exists() else None
        say(f"window steps Game Night saw: {window}")
        if not (window or {}).get("back_in_front"):
            failures.append(f"{tag}: Game Night didn't come back to the front after the game closed")
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


# ---------------------------------------------------------------- the in-game menu (boards IG2, on your own)

INGAME_LOG = CACHE / "player" / "logs" / "ingame.txt"


def ingame_lines():
    try:
        return INGAME_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return []


def menu_window(pid):
    """Game Night's in-game menu window: (visible, (x, y, w, h)) or None if it was never made."""
    user32 = ctypes.windll.user32
    found = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    class RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]

    def each(hwnd, _):
        h = ctypes.c_void_p(hwnd)
        p = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        buf = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(h, buf, 64)
        if p.value == pid and buf.value == "Game Night menu":
            r = RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            found.append((bool(user32.IsWindowVisible(h)), (r.l, r.t, r.r - r.l, r.b - r.t)))
        return True

    user32.EnumWindows(proc(each), 0)
    return found[0] if found else None


def frame():
    """The test game's frame number ($00-$02 in the netplay test cartridge), or None."""
    answer = ask_game("READ_CORE_MEMORY 0 3")
    parts = answer.split()
    if len(parts) == 5 and parts[0] == "READ_CORE_MEMORY":
        try:
            return int(parts[2], 16) | int(parts[3], 16) << 8 | int(parts[4], 16) << 16
        except ValueError:
            pass
    return None


def moving(seconds=1.0):
    a = frame()
    time.sleep(seconds)
    b = frame()
    say(f"    frames {a} -> {b}")
    return a is not None and b is not None and b > a


def hold(pad, buttons, seconds):
    for b in buttons:
        pad.press_button(button=b)
    pad.update()
    time.sleep(seconds)
    for b in buttons:
        pad.release_button(button=b)
    pad.update()
    time.sleep(0.3)


def ra_log():
    log = CACHE / "player" / "logs" / "retroarch.log"
    return log.read_text(errors="replace") if log.exists() else ""


def last_volume():
    """RetroArch's newest "Audio volume: X dB" log line, as a number (None before any change)."""
    for line in reversed(ra_log().splitlines()):
        if "volume: " in line:
            try:
                return float(line.split("volume: ")[1].split(" dB")[0])
            except ValueError:
                return None
    return None


def trigger_hold(pad, left, seconds):
    """Holds LT (left) or RT and returns (frame before, frame after)."""
    a = frame()
    (pad.left_trigger if left else pad.right_trigger)(value=255)
    pad.update()
    time.sleep(seconds)
    b = frame()
    (pad.left_trigger if left else pad.right_trigger)(value=0)
    pad.update()
    time.sleep(0.4)
    return a, b


def game_tab(app, pad, check, shown):
    """GAME and CONTROLLER tabs (board IG4): volume (changes when the menu closes on your own), hold LT to rewind,
    hold RT to fast forward, switching rewind off is saved for the console's next game."""
    say("\n--- GAME tab: volume 100% -> 80%, then back to the game")
    before = len(ingame_lines())
    press(pad, B.XUSB_GAMEPAD_GUIDE)
    time.sleep(1.5)
    check(shown(), "the menu opens for the GAME tab")
    for _ in range(2):
        press(pad, B.XUSB_GAMEPAD_RIGHT_SHOULDER)
        time.sleep(0.4)
    press(pad, B.XUSB_GAMEPAD_DPAD_LEFT)
    time.sleep(0.4)
    press(pad, B.XUSB_GAMEPAD_DPAD_LEFT)
    time.sleep(0.8)
    screenshot("ingame-7-game-tab-volume")
    press(pad, B.XUSB_GAMEPAD_B)
    ok = False
    for _ in range(20):
        time.sleep(0.5)
        if last_volume() == -2.0:
            ok = True
            break
    new = ingame_lines()[before:]
    for line in new:
        say(f"    | {line}")
    say(f"    RetroArch's volume lines: " + " / ".join(l.strip() for l in ra_log().splitlines() if "volume: " in l)[-400:])
    check(sum("action volume down" in l for l in new) == 2, "left twice on VOLUME asks for 2 steps down")
    check(ok, f"the game's volume is 80% (-2.0 dB) once the menu closed (RetroArch's log says {last_volume()})")
    vol = Path(os.environ["APPDATA"]) / "xyz.jjsnas.gamenight" / "player" / "volume.txt"
    say(f"    volume.txt: {vol.read_text().strip() if vol.exists() else '(none)'}")
    check(vol.exists() and vol.read_text().strip() == "80", "80% is saved for the next game")
    check(moving(), "the game carries on after the GAME tab")

    say("\n--- hold RT: fast forward")
    a, b = trigger_hold(pad, False, 2.0)
    time.sleep(0.5)
    c = frame()
    time.sleep(2.0)
    d = frame()
    say(f"    frames: RT held 2 s {a} -> {b}; nothing held 2 s {c} -> {d}")
    if None not in (a, b, c, d):
        check((b - a) > 1.3 * (d - c), f"holding RT runs the game faster ({b - a} frames vs {d - c} normally)")
    else:
        check(False, "the test game's frame number could be read for fast forward")

    say("\n--- hold LT: rewind")
    a, b = trigger_hold(pad, True, 1.5)
    say(f"    frames: LT held 1.5 s {a} -> {b}")
    check(None not in (a, b) and b < a, f"holding LT rewinds the game (frame {a} -> {b})")
    check(moving(), "the game carries on after rewinding")

    say("\n--- GAME tab: rewind off for the next game, CONTROLLER tab shows the pad")
    before = len(ingame_lines())
    press(pad, B.XUSB_GAMEPAD_GUIDE)
    time.sleep(1.5)
    for _ in range(2):
        press(pad, B.XUSB_GAMEPAD_RIGHT_SHOULDER)
        time.sleep(0.4)
    press(pad, B.XUSB_GAMEPAD_DPAD_DOWN)
    time.sleep(0.4)
    press(pad, B.XUSB_GAMEPAD_A)
    time.sleep(1.0)
    screenshot("ingame-8-game-tab-rewind-off")
    press(pad, B.XUSB_GAMEPAD_RIGHT_SHOULDER)
    time.sleep(0.8)
    screenshot("ingame-9-controller-tab")
    new = ingame_lines()[before:]
    for line in new:
        say(f"    | {line}")
    check(any("action rewind off" in l for l in new), "A on REWIND switches it off")
    store = Path(os.environ["APPDATA"]) / "xyz.jjsnas.gamenight" / "settings.json"
    saved = None
    for _ in range(10):
        try:
            saved = json.loads(store.read_text())["settings"]["consoles"]["nes"]["rewind"]
            break
        except Exception:
            time.sleep(0.5)
    say(f"    settings.json nes rewind: {saved}")
    check(saved is False, "rewind off is saved in Settings for the console's next game")
    press(pad, B.XUSB_GAMEPAD_B)
    time.sleep(1.5)
    check(not shown(), "B closes the menu")
    a, b = trigger_hold(pad, True, 1.0)
    check(None not in (a, b) and b < a, f"rewind keeps working in this game (the switch counts from the next game): {a} -> {b}")


def ingame():
    """On your own: the Xbox button and L3 + R3 open Game Night's menu over the game, which pauses it; B and the
    Xbox button close it and the game carries on; the look can change; Quit asks first, then goes back to Game Night."""
    import make_netplay_rom
    lib = json.loads((ROOT / "library.json").read_text())
    game_file = ROOT / lib["1"]["console"] / lib["1"]["file"]
    original = game_file.read_bytes()
    game_file.write_bytes(make_netplay_rom.rom())  # same buttons at $10, plus a frame number at $00-$02
    pad = vg.VX360Gamepad(vid=0x045E, pid=0x02FF)
    time.sleep(2)
    for f in (CACHE / "player" / "logs" / "retroarch.log", ROOT / "e2e-result.json"):
        f.unlink(missing_ok=True)
    app = start_app("padgame")
    G = B.XUSB_GAMEPAD_GUIDE

    def check(ok, what):
        say(f"  {'ok' if ok else 'FAIL'}: {what}")
        if not ok:
            failures.append(f"in-game menu: {what}")
        return ok

    def shown():
        w = menu_window(app.pid)
        return bool(w and w[0])

    try:
        say("pressing A in the menus (Game Night then starts the test game)")
        press(pad, B.XUSB_GAMEPAD_A)
        for _ in range(30):
            time.sleep(1)
            if not ask_game("VERSION").startswith("(no answer"):
                break
        time.sleep(3)
        check(front_is_game(), f"the game is in front before the menu ({in_front()})")
        check(moving(), "the game runs")

        say("\n--- Xbox button: the menu opens over the game and the game pauses")
        press(pad, G)
        time.sleep(1.5)
        w = menu_window(app.pid)
        say(f"    menu window: {w}; in front {in_front()}")
        screenshot("ingame-1-xbox-button-open")
        check(bool(w and w[0]), "the menu window shows after the Xbox button")
        if w and w[0]:
            check(w[1][2] >= 1000 and w[1][3] >= 600, f"the menu covers the game's screen ({w[1]})")
        check(not moving(1.5), "the game is paused while the menu is open")

        say("\n--- B: back to the game")
        press(pad, B.XUSB_GAMEPAD_B)
        time.sleep(1.5)
        screenshot("ingame-2-b-closed")
        check(not shown(), "B closes the menu")
        check(moving(), "the game carries on after B")
        check(front_is_game(), f"the game is in front again ({in_front()})")
        say("    pad A in the game after the menu closed (player 1 must see it):")
        p1, _ = hold_and_read(pad, B.XUSB_GAMEPAD_A, "ingame-2b-pad-reaches-game")
        check(p1 == 0x40, f"the pad reaches the game again after the menu (player 1 {p1})")

        say("\n--- hold L3 + R3 for 1.4 s: the menu opens")
        hold(pad, [B.XUSB_GAMEPAD_LEFT_THUMB, B.XUSB_GAMEPAD_RIGHT_THUMB], 1.4)
        time.sleep(1)
        screenshot("ingame-3-l3-r3-open")
        check(shown(), "holding L3 + R3 opens the menu")
        check(not moving(1.2), "the game is paused (L3 + R3)")

        say("\n--- RB: MY SCREEN tab, right: the next look")
        before = len(ingame_lines())
        press(pad, B.XUSB_GAMEPAD_RIGHT_SHOULDER)
        time.sleep(0.6)
        press(pad, B.XUSB_GAMEPAD_DPAD_RIGHT)
        time.sleep(2.5)
        screenshot("ingame-4-my-screen-look")
        new = ingame_lines()[before:]
        for line in new:
            say(f"    | {line}")
        check(any("action look" in l for l in new), "right on LOOK changes the look")
        check(shown(), "the menu stays open while changing the look")
        log = CACHE / "player" / "logs" / "retroarch.log"
        text = log.read_text(errors="replace") if log.exists() else ""
        say("    RetroArch's shader lines: " + " / ".join(l.strip() for l in text.splitlines() if "hader" in l)[-600:])
        press(pad, B.XUSB_GAMEPAD_LEFT_SHOULDER)
        time.sleep(0.5)

        say("\n--- Xbox button again: closes the menu")
        press(pad, G)
        time.sleep(1.5)
        check(not shown(), "the Xbox button closes the menu")
        check(moving(), "the game carries on")

        game_tab(app, pad, check, shown)

        say("\n--- Quit to Library: asks first; Keep playing; then Yes")
        press(pad, G)
        time.sleep(1.5)
        for _ in range(4):
            press(pad, B.XUSB_GAMEPAD_DPAD_DOWN)
            time.sleep(0.35)
        press(pad, B.XUSB_GAMEPAD_A)
        time.sleep(1)
        screenshot("ingame-5-quit-asks")
        check(app.poll() is None and frame() is not None, "Quit asks first (the game is still there)")
        press(pad, B.XUSB_GAMEPAD_A)  # "Keep playing" is picked first
        time.sleep(0.8)
        check(shown() and frame() is not None, "Keep playing keeps the menu and the game")
        press(pad, B.XUSB_GAMEPAD_A)  # Quit again
        time.sleep(0.8)
        press(pad, B.XUSB_GAMEPAD_DPAD_LEFT)  # to "Yes, quit"
        time.sleep(0.4)
        screenshot("ingame-6-quit-yes")
        press(pad, B.XUSB_GAMEPAD_A)
        try:
            app.wait(30)
        except subprocess.TimeoutExpired:
            pass
        result = ROOT / "e2e-result.json"
        res = json.loads(result.read_text()) if result.exists() else {}
        say(f"    e2e result: {res}")
        check(app.poll() is not None and res.get("ok") is not None, "Yes, quit closes the game (and the test app with it)")
        check(bool((res.get("window") or {}).get("back_in_front")), "Game Night came back in front after quitting")
    finally:
        if app.poll() is None:
            app.kill()
        subprocess.run(["taskkill", "/F", "/IM", "retroarch.exe"], capture_output=True)
        game_file.write_bytes(original)
        say("\ningame.txt:")
        for line in ingame_lines():
            say(f"  | {line}")
        dump_log("\nwhole pads.txt:")
        del pad
        time.sleep(2)
    return "the in-game menu opened with the Xbox button and L3 + R3, paused the game, changed the look and quit after asking"


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    done = {"menus": menus, "game": games, "ingame": ingame}[MODE]()
    if failures:
        for f in failures:
            print(f"::error::controller test ({MODE}): {f}", flush=True)
        sys.exit(1)
    say(f"\n{done}")


main()
