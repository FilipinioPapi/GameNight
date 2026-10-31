#!/usr/bin/env python3
"""CI only (GitHub's Windows machine): the REAL Game Night app hosts a Couch Play lobby, and a friend joins it
through libretro's relay the private way (nothing listed anywhere). Proves the whole chain the app builds:
Game Night's server (lobby, code, seats), the app's relay bridge (Rust), the app starting RetroArch as host in
the game box, and a friend joining with only what the server hands out.

    python couch_app_test.py <player folder> <work folder> <results folder> <game-night.exe> <server folder>

- The server is Game Night's own server code run on this machine by couch_server_standin.py (pretend RomM
  with one test game, pretend signed-in friends). Listens on 127.0.0.1 only.
- The app is the "e2e" test build (never shipped). With GAMENIGHT_E2E=couchhost it signs in with a test pass,
  hosts game "1" as an OPEN lobby exactly like the HOST A GAME button, and writes e2e-couch.json
  ({"code", "cmd_port"}) in the Game Night folder once its RetroArch is running.
- The "friend" is a stock copy of the same pinned RetroArch on this machine reading only pretend pad B. It only
  learns the relay session from the server, after joining with the code.

Checks: the open lobby is listed for the friend; joining gives seat 2 and the relay session; the friend
connects through the relay; pad A drives player 1 and pad B player 2 in both games; 60 s of random presses
with every finished frame compared; the friend switches to watching (pad B stops reaching the game); the
friend's game closes (seat held, game doesn't pause); the friend rejoins with the code and gets seat 2 back.

Look checks (window_watch.py, plus screenshots): the app shows the lobby screen full screen by default; the game
sits inside Game Night's window as a child window, inside the box (not over the seat list), with no menu bar,
and stays put (no flicker) while sampled 25 times a second. Then the app is started again as a window
(GAMENIGHT_E2E_WINDOWED), and the same is checked before and after the window is moved and resized.
"""
import json
import os
import random
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

import vgamepad as vg

sys.path.insert(0, str(Path(__file__).parent))
import make_netplay_rom as cart  # noqa: E402
import window_watch  # noqa: E402

PLAYER, WORK, OUT = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
APP, SERVER = Path(sys.argv[4]).resolve(), Path(sys.argv[5]).resolve()
TOOLS = Path(__file__).parent
EXE = PLAYER / "retroarch.exe"
CORE = PLAYER / "cores" / "fceumm_libretro.dll"
PORT = 8094
FRIEND_CMD_PORT = 55460
MASH_SECONDS = int(os.environ.get("COUCH_MASH_SECONDS", "60"))
MARGIN = 60  # compare only frames this many frames old in both copies (newer ones may still be redone)
B = vg.XUSB_BUTTON
NES = [
    ("A", B.XUSB_GAMEPAD_A, 0x40), ("B", B.XUSB_GAMEPAD_B, 0x80),
    ("View", B.XUSB_GAMEPAD_BACK, 0x20), ("Menu", B.XUSB_GAMEPAD_START, 0x10),
    ("Up", B.XUSB_GAMEPAD_DPAD_UP, 0x08), ("Down", B.XUSB_GAMEPAD_DPAD_DOWN, 0x04),
    ("Left", B.XUSB_GAMEPAD_DPAD_LEFT, 0x02), ("Right", B.XUSB_GAMEPAD_DPAD_RIGHT, 0x01),
]
failures, results = [], {}


def say(m=""):
    print(m, flush=True)


def fail(m):
    say(f"FAIL: {m}")
    failures.append(m)


def screenshot(name):
    subprocess.run(["pwsh", "-NoProfile", "-File", str(TOOLS / "screenshot.ps1"), str(OUT / f"{name}.png")], check=False)


def look(name, app, full_screen, game_full=False, settle=3, seconds=6):
    """Watches the game window for `seconds`, takes 3 quick screenshots, and checks it sits still in the box."""
    time.sleep(settle)  # the lobby screen fades in, then the box is sent
    summary, samples = window_watch.watch(app.pid, seconds)
    for i in range(3):
        screenshot(f"{name}-{i + 1}")
        time.sleep(0.15)
    (OUT / f"{name}-window.json").write_text(json.dumps({"summary": summary, "samples": samples}, indent=1))
    results.setdefault("look", {})[name] = summary
    say(f"  {name}: {json.dumps(summary)}")
    if not summary["last_game"]:
        fail(f"{name}: no game window found")
        return
    if not summary["always_child"]:
        fail(f"{name}: the game isn't inside Game Night's window (not a child window)")
    if summary["ever_menu_bar"]:
        fail(f"{name}: the game window shows RetroArch's menu bar")
    if summary["ever_hidden"]:
        fail(f"{name}: the game window was hidden while the lobby was showing")
    if summary["place_changes"] > 0:
        fail(f"{name}: the game window moved or resized {summary['place_changes']} times in {seconds} s (flicker)")
    if not summary["game_inside_app"]:
        fail(f"{name}: the game isn't inside Game Night's window: {summary['last_game']} vs {summary['last_app_inside']}")
    elif game_full == "strips":
        ax, ay, aw, ah = summary["last_app_inside"]
        if tuple(summary["last_game"]) != (ax, ay + 72, aw, ah - 72 - 56):
            fail(f"{name}: in full screen with lobby controls open, the game doesn't leave the top and bottom strips: {summary['last_game']}")
    elif game_full:
        if tuple(summary["last_game"]) != tuple(summary["last_app_inside"]):
            fail(f"{name}: the game doesn't fill Game Night's window in full screen: {summary['last_game']} vs {summary['last_app_inside']}")
    elif summary["last_game"][2] > 0.6 * summary["last_app_inside"][2]:
        fail(f"{name}: the game is wider than the lobby's game box (over the seat list): {summary['last_game']}")
    if summary["app_full_screen"] != full_screen:
        fail(f"{name}: Game Night full screen is {summary['app_full_screen']}, expected {full_screen}")


def wait_until(check, seconds, step=0.25):
    end = time.time() + seconds
    while time.time() < end:
        got = check()
        if got:
            return got
        time.sleep(step)
    return None


# ---------------------------------------------------------------- the server, as the friend's app talks to it

class Api:
    def __init__(self, url, token):
        self.url, self.token = url, token

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")


class Heartbeat(threading.Thread):
    """What the friend's app does every 3 s while in a lobby."""

    def __init__(self, api, code):
        super().__init__(daemon=True)
        self.api, self.code, self.on, self.last = api, code, threading.Event(), None
        self.on.set()

    def run(self):
        while True:
            if self.on.is_set():
                self.last = self.api.call("POST", f"/api/lobbies/{self.code}/heartbeat", {"retroarch": "running"})
            time.sleep(3)


# ---------------------------------------------------------------- RetroArch copies

class Ask:
    """RetroArch's local command port (this machine only)."""

    def __init__(self, port):
        self.cmd_port = port

    def ask(self, command, timeout=1.0):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.sendto(command.encode(), ("127.0.0.1", self.cmd_port))
            try:
                return s.recv(65536).decode(errors="replace").strip()
            except OSError:
                return None

    def send(self, command):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(command.encode(), ("127.0.0.1", self.cmd_port))

    def status(self):
        """RetroArch's own word on the game: PLAYING / PAUSED / CONTENTLESS (None = no answer)."""
        a = self.ask("GET_STATUS") or ""
        parts = a.split()
        return parts[1] if len(parts) > 1 else (a or None)

    def ram(self, start=0, length=1024):
        parts = (self.ask(f"READ_CORE_MEMORY {start:x} {length}") or "").split()
        if len(parts) == length + 2 and parts[0] == "READ_CORE_MEMORY":
            try:
                return bytes(int(x, 16) for x in parts[2:])
            except ValueError:
                return None
        return None


class Friend(Ask):
    def __init__(self, slot):
        super().__init__(FRIEND_CMD_PORT)
        self.dir, self.slot, self.proc = WORK / "friend", slot, None

    def start(self, rom, relay, seat):
        for d in ("logs", "saves", "states", "system", "cache"):
            (self.dir / d).mkdir(parents=True, exist_ok=True)
        p = lambda q: str(q).replace('"', "")  # noqa: E731
        s = {
            "config_save_on_exit": "false", "menu_driver": "rgui", "input_menu_toggle": "nul",
            "input_menu_toggle_gamepad_combo": "0", "input_quit_gamepad_combo": "0", "ui_companion_enable": "false",
            "auto_remaps_enable": "false", "auto_overrides_enable": "false", "game_specific_options": "false",
            "cheevos_enable": "false", "discord_allow": "false", "rewind_enable": "false", "input_exit_emulator": "nul",
            "network_cmd_enable": "true", "network_cmd_port": str(self.cmd_port),
            "netplay_public_announce": "false", "netplay_nat_traversal": "false", "netplay_use_mitm_server": "false",
            "netplay_check_frames": "0", "netplay_nickname": "Friend", "netplay_allow_pausing": "true",
            f"netplay_request_device_p{seat}": "true",
            "video_driver": "d3d11", "video_fullscreen": "false", "video_scale": "2",
            "video_window_save_positions": "true", "video_windowed_position_x": "1600",
            "video_windowed_position_y": "760", "video_windowed_position_width": "300",
            "video_windowed_position_height": "240", "ui_menubar_enable": "false", "pause_nonactive": "false",
            "audio_enable": "false", "video_vsync": "false", "vrr_runloop_enable": "true",
            "input_joypad_driver": "xinput", "input_autodetect_enable": "true",
            "joypad_autoconfig_dir": p(PLAYER / "autoconfig"), "input_max_users": "1",
            "input_player1_joypad_index": str(self.slot),
            "libretro_directory": p(PLAYER / "cores"), "savefile_directory": p(self.dir / "saves"),
            "savestate_directory": p(self.dir / "states"), "system_directory": p(self.dir / "system"),
            "cache_directory": p(self.dir / "cache"), "log_to_file": "true", "log_to_file_timestamp": "false",
            "log_verbosity": "true", "frontend_log_level": "0", "log_dir": p(self.dir / "logs"),
        }
        cfg = self.dir / "retroarch.cfg"
        cfg.write_text("".join(f'{k} = "{v}"\n' for k, v in s.items()), encoding="ascii")
        args = [str(EXE), "-c", str(cfg), "-L", str(CORE), "--connect", relay["server"], "--port", str(relay["port"]),
                f"--mitm-session={relay['session']}", str(rom)]
        say(f"starting the friend: {' '.join(args[1:])}")
        self.proc = subprocess.Popen(args, cwd=str(PLAYER))

    def log(self):
        try:
            return (self.dir / "logs" / "retroarch.log").read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return ""

    def kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(10)


class HostAsk(Ask):
    """The app's RetroArch: follows its command port when the app starts it again (a crash or Refresh), so one
    problem shows as one failure instead of every later check reading nothing."""

    def __init__(self, port):
        self.first = port

    @property
    def cmd_port(self):
        return ra_cmd_port() or self.first


def frame_of(mem):
    return mem[0] | mem[1] << 8 | mem[2] << 16


def menu_window(pid):
    """Game Night's in-game menu window: (visible, (x, y, w, h)) or None."""
    import ctypes
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


def menu_shown(app):
    w = menu_window(app.pid)
    return bool(w and w[0])


# The host's in-game menu, HOME tab (not paused): RESUME, PAUSE FOR EVERYONE, FULL SCREEN / BACK TO LOBBY,
# REFRESH GAME, END GAME FOR EVERYONE.
HOST_ITEMS = {"resume": 0, "pause": 1, "full": 2, "lobby": 2, "refresh": 3}


def menu(app, pad, item=None):
    """The Xbox button opens the in-game menu; then D-pad down to `item` and A (None = leave it open)."""
    tap(pad, B.XUSB_GAMEPAD_GUIDE)
    if not wait_until(lambda: menu_shown(app), 4, 0.1):
        fail(f"the in-game menu didn't open with the Xbox button (for {item})")
        return False
    time.sleep(0.5)
    if item is None:
        return True
    for _ in range(HOST_ITEMS[item]):
        tap(pad, B.XUSB_GAMEPAD_DPAD_DOWN)
        time.sleep(0.3)
    tap(pad, B.XUSB_GAMEPAD_A)
    time.sleep(0.8)
    return True


def tap(pad, button):
    set_pad(pad, [button])
    time.sleep(0.2)
    set_pad(pad, [])


def ra_cmd_port():
    """The command port in the app's current RetroArch settings (it changes each time the game restarts)."""
    cfg = Path(os.environ.get("APPDATA", "")) / "xyz.jjsnas.gamenight" / "player" / "retroarch.cfg"
    for line in cfg.read_text(errors="replace").splitlines() if cfg.exists() else []:
        if line.startswith("network_cmd_port"):
            return int(line.split('"')[1])
    return None


def bezel_pixels(name, rect):
    """In screenshot `name`-3: share of lit pixels in a band left of where the game sits (8-18 % across, middle
    rows). The TV frame (bezel B) is dark grey there (about 26 of 255, measured in run 41236464953) with a red
    logo; with no bezel it's black."""
    from PIL import Image
    img = Image.open(OUT / f"{name}-3.png").convert("RGB")
    x, y, w, h = rect
    part = img.crop((x + int(w * 0.08), y + int(h * 0.3), x + int(w * 0.18), y + int(h * 0.7))).resize((32, 32))
    px = list(part.getdata())
    return {"band": round(sum(1 for p in px if max(p) > 12) / len(px), 3)}


def app_bezel():
    """The bezel file the app's RetroArch settings point at, and how many pages it has."""
    cfg = Path(os.environ.get("APPDATA", "")) / "xyz.jjsnas.gamenight" / "player" / "retroarch.cfg"
    lines = cfg.read_text(errors="replace").splitlines() if cfg.exists() else []
    get = lambda k: next((l.split('"')[1] for l in lines if l.startswith(k + " ") and '"' in l), None)
    overlay = get("input_overlay")
    pages = None
    if overlay and Path(overlay).is_file():
        first = Path(overlay).read_text(errors="replace").splitlines()[:1]
        pages = first[0].split("=")[1].strip() if first else None
    return {"enabled": get("input_overlay_enable"), "file": Path(overlay).name if overlay else None, "pages": pages}


def set_pad(pad, buttons):
    pad.reset()
    for b in buttons:
        pad.press_button(button=b)
    pad.update()


# ---------------------------------------------------------------- checks

def connected(host, friend):
    """The friend took the host's game (its frame number jumped to the host's) and both keep counting."""
    a, b = host.ram(0, 3), friend.ram(0, 3)
    if not a or not b:
        return None
    fa, fb = frame_of(a), frame_of(b)
    return (fa, fb) if fa > 120 and abs(fa - fb) < 60 else None


def buttons_check(host, friend, pad, label, byte):
    wrong = []
    for name, button, bit in NES:
        set_pad(pad, [button])
        def seen():
            a, b = host.ram(0x10, 2), friend.ram(0x10, 2)
            return a and b and a[byte] == bit and b[byte] == bit and a[1 - byte] == 0 and b[1 - byte] == 0
        if not wait_until(seen, 3, 0.05):
            a, b = host.ram(0x10, 2), friend.ram(0x10, 2)
            wrong.append(f"{name}: host {a.hex() if a else None}, friend {b.hex() if b else None}")
        set_pad(pad, [])
        time.sleep(0.15)
    if wrong:
        fail(f"pad {label}: buttons didn't show on player {byte + 1} only in both games: {wrong}")
    else:
        say(f"  pad {label}: all 8 buttons on player {byte + 1} only, in both games")
    return not wrong


def sync_round(host, friend, pad_a, pad_b, seconds, seed):
    """Random presses on both pads; compare every finished frame's fingerprint in both games."""
    rnd = random.Random(seed)
    compared, different, first_bad, reads = set(), 0, None, 0
    end = time.time() + seconds
    next_press = 0.0
    while time.time() < end:
        if time.time() >= next_press:
            for pad in (pad_a, pad_b):
                set_pad(pad, [b for _, b, _ in rnd.sample(NES, rnd.randint(0, 3))])
            next_press = time.time() + rnd.uniform(0.05, 0.4)
        a, b = host.ram(0, 1024), friend.ram(0, 1024)
        if not a or not b:
            time.sleep(0.05)
            continue
        reads += 1
        fa, fb = frame_of(a), frame_of(b)
        lo, hi = max(fa, fb) - 250, min(fa, fb) - MARGIN
        for f in range(max(lo, 1), hi + 1):
            if f in compared:
                continue
            compared.add(f)
            if a[0x300 + (f & 0xFF)] != b[0x300 + (f & 0xFF)]:
                different += 1
                first_bad = first_bad or f
        time.sleep(0.25)
    set_pad(pad_a, [])
    set_pad(pad_b, [])
    say(f"  {len(compared)} frames compared, {different} different (reads {reads})")
    if len(compared) < seconds * 30:
        fail(f"sync: only {len(compared)} frames could be compared in {seconds} s")
    if different:
        fail(f"sync: {different} frames out of sync, first at frame {first_bad}")
    return {"frames_compared": len(compared), "frames_different": different}


def seat(lobby, n):
    return next((s for s in lobby.get("seats", []) if s.get("n") == n), {}) if isinstance(lobby, dict) else {}


# ---------------------------------------------------------------- main

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    root = WORK / "gn" / "Game Night"
    (root / "nes").mkdir(parents=True, exist_ok=True)
    data = cart.rom()
    (root / "nes" / "test.nes").write_bytes(data)
    (root / "library.json").write_text(json.dumps({"1": {"console": "nes", "file": "test.nes", "size": len(data)}}))
    friend_rom = WORK / "friend-test.nes"  # the friend's own copy of the same file
    friend_rom.write_bytes(data)

    say("plugging in pretend pads: A = the host (player 1), B = the friend (player 2)")
    pad_a = vg.VX360Gamepad()
    time.sleep(1.5)
    pad_b = vg.VX360Gamepad()
    time.sleep(1.5)
    slot_b = 1  # the lobby proof measured A-D as slots 0-3 (ViGEm can't report the slot here)

    say("starting Game Night's server code on this machine (stand-in)")
    server_log = open(OUT / "server.log", "w")
    server = subprocess.Popen([sys.executable, str(TOOLS / "couch_server_standin.py"), str(SERVER), str(WORK / "server"),
                               str(len(data)), str(PORT)], stdout=server_log, stderr=subprocess.STDOUT)
    def healthy():
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/healthz", timeout=2) as r:
                return r.status == 200
        except OSError:
            return False
    if not wait_until(healthy, 30):
        fail("the stand-in server didn't start (see server.log)")
        return
    standin = json.loads((WORK / "server" / "standin.json").read_text())
    friend_api = Api(standin["url"], standin["passes"]["friend"])

    say("starting the Game Night app (e2e build) to host game 1 as an open lobby")
    env = dict(os.environ, GAMENIGHT_E2E="couchhost", GAMENIGHT_E2E_ROOT=str(root), GAMENIGHT_PLAYER_DIR=str(PLAYER),
               GAMENIGHT_E2E_SERVER=standin["url"], GAMENIGHT_E2E_TOKEN=standin["passes"]["host"])
    app_log = open(OUT / "app.log", "w")
    t0 = time.time()
    app = subprocess.Popen([str(APP)], env=env, stdout=app_log, stderr=subprocess.STDOUT)
    friend = Friend(slot_b)
    try:
        info_file = root / "e2e-couch.json"
        info = wait_until(lambda: info_file.exists() and json.loads(info_file.read_text() or "{}"), 120, 0.5)
        if not info or "code" not in info:
            fail(f"the app didn't host a lobby within 120 s: {info}")
            return
        results["host_ready_seconds"] = round(time.time() - t0, 1)
        code = info["code"]
        say(f"  app hosted lobby {code} in {results['host_ready_seconds']} s (its RetroArch command port {info['cmd_port']})")
        host = HostAsk(int(info["cmd_port"]))
        screenshot("1-host-lobby")
        say("look: the lobby screen, full screen by default")
        look("look-1-full-screen", app, True)

        status, listed = friend_api.call("GET", "/api/lobbies")
        mine = [x for x in (listed or {}).get("lobbies", [])] if status == 200 else []
        if not any(x.get("code") == code for x in mine):
            fail(f"the open lobby isn't in the friend's list: {status} {listed}")
        else:
            say("  the friend sees the open lobby in their list")
        if any("relay" in x for x in mine):
            fail("the open lobby list shows the relay session to someone who hasn't joined")

        status, lobby = friend_api.call("POST", f"/api/lobbies/{code.lower()}/join", {"as": "play"})
        if status != 200 or lobby.get("you", {}).get("seat") != 2 or not lobby.get("relay"):
            fail(f"joining with the code didn't give seat 2 and the relay: {status} {lobby}")
            return
        relay = lobby["relay"]
        say(f"  joined: seat 2, relay {relay['server']}:{relay['port']}")
        beat = Heartbeat(friend_api, code)
        beat.start()

        t = time.time()
        friend.start(friend_rom, relay, 2)
        got = wait_until(lambda: connected(host, friend), 60, 0.25)
        if not got:
            fail("the friend didn't connect through the relay within 60 s")
            say(friend.log()[-3000:])
            return
        results["join_seconds"] = round(time.time() - t, 1)
        say(f"  connected through the relay in {results['join_seconds']} s (frames {got})")
        screenshot("2-friend-connected")
        say("look: after the friend connected")
        look("look-2-friend-connected", app, True)
        say("look: Xbox button for the in-game menu, then FULL SCREEN: the game goes full screen")
        if not window_watch.focus_app(app.pid):
            # The test friend's own RetroArch window opened last and is in front; a player would be in Game Night.
            fail("couldn't put Game Night in front for the pad presses")
        menu(app, pad_a, "full")
        if menu_shown(app):
            fail("the in-game menu stayed open after FULL SCREEN")
        look("look-2b-game-full-screen", app, True, game_full=True)
        say("look: the bezel (TV frame) around the full screen game, none in the lobby's small box")
        results["bezel"] = {"settings": app_bezel()}
        say(f"  RetroArch's bezel setting: {results['bezel']['settings']}")
        b = results["bezel"]["settings"]
        if b["enabled"] == "true":
            fail(f"Couch Play has no bezel for now (it went with the host's RetroArch crashing), but one is set: {b}")
        full_rect = results["look"]["look-2b-game-full-screen"]["last_game"]
        results["bezel"]["full_screen"] = bezel_pixels("look-2b-game-full-screen", full_rect)
        say(f"  full screen, lit share left of the game: {results['bezel']['full_screen']}")
        if False:  # Couch Play has no bezel for now (see games.rs); the band is recorded only.
            # Measure why: flip the page ourselves. Lit now = Game Night's page count was off by one;
            # still dark = RetroArch isn't drawing the bezel at all.
            host.send("OVERLAY_NEXT")
            time.sleep(1.5)
            screenshot("look-2b-bezel-after-one-more-flip-3")
            results["bezel"]["after_one_more_flip"] = bezel_pixels("look-2b-bezel-after-one-more-flip", full_rect)
            say(f"  after one more OVERLAY_NEXT sent by the test: {results['bezel']['after_one_more_flip']}")
            host.send("OVERLAY_NEXT")
            time.sleep(0.5)
        say("look: in full screen, the in-game menu over the game (the game stays full screen behind it)")
        menu(app, pad_a)
        w = menu_window(app.pid)
        say(f"  menu window: {w}")
        if w and w[0] and (w[1][2] < 1000 or w[1][3] < 600):
            fail(f"the in-game menu doesn't cover Game Night's window: {w}")
        look("look-2c-full-screen-menu-open", app, True, game_full=True, settle=1.0, seconds=4)
        h1 = host.ram(0, 3)
        time.sleep(1)
        h2 = host.ram(0, 3)
        results["menu_open_host"] = {"status": host.status(), "frames": [frame_of(h1) if h1 else None, frame_of(h2) if h2 else None]}
        say(f"  host's RetroArch with the menu open: {results['menu_open_host']}")
        say("menu open: the host's presses stop reaching the game, the friend's still do")
        set_pad(pad_a, [B.XUSB_GAMEPAD_X])  # X does nothing in the menu
        set_pad(pad_b, [B.XUSB_GAMEPAD_A])
        time.sleep(1.5)
        a, b = host.ram(0x10, 2), friend.ram(0x10, 2)
        set_pad(pad_a, [])
        set_pad(pad_b, [])
        results["menu_open_buttons"] = {"host": a.hex() if a else None, "friend": b.hex() if b else None}
        say(f"  with the host's menu open, holding X on pad A and A on pad B: host game {results['menu_open_buttons']['host']}, friend game {results['menu_open_buttons']['friend']}")
        if not a or not b or a[0] != 0 or b[0] != 0 or a[1] != 0x40 or b[1] != 0x40:
            fail(f"menu open: pad A should go nowhere and pad B reach player 2 in both games: {results['menu_open_buttons']}")
        m1 = friend.ram(0, 3)
        time.sleep(1)
        m2 = friend.ram(0, 3)
        if not m1 or not m2 or frame_of(m2) - frame_of(m1) < 30:
            fail(f"the game didn't keep going for the friend while the host's menu was open: {m1} {m2}")
        tap(pad_a, B.XUSB_GAMEPAD_B)
        time.sleep(1)
        if menu_shown(app):
            fail("B didn't close the in-game menu")
        buttons_check(host, friend, pad_a, "A (after the host's menu closed)", 0)
        say("look: the in-game menu's BACK TO LOBBY")
        menu(app, pad_a, "lobby")
        look("look-2d-back-to-the-box", app, True)
        box_rect = results["look"]["look-2d-back-to-the-box"]["last_game"]
        results["bezel"]["box"] = bezel_pixels("look-2d-back-to-the-box", box_rect)
        # Recorded only: in the box the game itself fills that band.
        say(f"  in the box, lit share in the same band: {results['bezel']['box']} (the game fills most of the box)")
        say("full screen and back 6 more times through the menu, quickly (Jayden lost control after doing this)")
        for _ in range(6):
            menu(app, pad_a, "full")
            time.sleep(1)
            menu(app, pad_a, "lobby")
            time.sleep(1)
        look("look-2e-after-switching", app, True)

        say("pause for everyone (host's menu), then resume for everyone")
        menu(app, pad_a, "pause")
        paused = wait_until(lambda: friend_api.call("GET", f"/api/lobbies/{code}")[1].get("paused"), 6, 0.5)
        f1 = friend.ram(0, 3)
        time.sleep(2)
        f2 = friend.ram(0, 3)
        results["pause_host"] = {"server": paused, "friend_frames": [frame_of(f1) if f1 else None, frame_of(f2) if f2 else None]}
        screenshot("2f-host-paused-for-everyone")
        say(f"  {results['pause_host']}")
        if not paused or not f1 or not f2 or frame_of(f2) != frame_of(f1):
            fail(f"the host's PAUSE FOR EVERYONE didn't pause the friend's game: {results['pause_host']}")
        results["pause_host"]["status_paused_menu_open"] = host.status()
        tap(pad_a, B.XUSB_GAMEPAD_A)  # the same spot now says RESUME FOR EVERYONE
        time.sleep(3)
        results["pause_host"]["status_resumed_menu_open"] = host.status()
        f1 = friend.ram(0, 3)
        time.sleep(1)
        f2 = friend.ram(0, 3)
        tap(pad_a, B.XUSB_GAMEPAD_B)
        time.sleep(1)
        h1 = host.ram(0, 3)
        time.sleep(1)
        h2 = host.ram(0, 3)
        results["pause_host"]["status_resumed_menu_closed"] = host.status()
        results["pause_host"]["host_frames_menu_closed"] = [frame_of(h1) if h1 else None, frame_of(h2) if h2 else None]
        say(f"  RetroArch's status: {results['pause_host']}")
        if not f1 or not f2 or frame_of(f2) - frame_of(f1) < 30:
            fail(f"RESUME FOR EVERYONE didn't start the game again for the friend: {f1} {f2}")

        say("a friend pauses for everyone (through the server); the host's app pauses the game and shows who")
        status, view = friend_api.call("POST", f"/api/lobbies/{code}/pause", {"on": True})
        if status != 200 or not (view or {}).get("paused"):
            fail(f"the friend couldn't pause through the server: {status} {view}")
        time.sleep(5)  # the host's app hears it with its next heartbeat (every 3 s)
        h1 = host.ram(0, 3)
        time.sleep(2)
        h2 = host.ram(0, 3)
        w = menu_window(app.pid)
        screenshot("2g-paused-by-friend")
        results["pause_friend"] = {"host_frames": [frame_of(h1) if h1 else None, frame_of(h2) if h2 else None], "paused_by_window": w}
        say(f"  {results['pause_friend']}")
        if not h1 or not h2 or frame_of(h2) != frame_of(h1):
            fail(f"the friend's pause didn't pause the game: {results['pause_friend']}")
        if not (w and w[0]):
            fail("the host's screen didn't show \"Paused by\" while the friend had paused")
        results["pause_friend"]["status_paused"] = host.status()
        friend_api.call("POST", f"/api/lobbies/{code}/pause", {"on": False})
        time.sleep(5)
        results["pause_friend"]["status_after"] = host.status()
        say(f"  host's RetroArch status: paused {results['pause_friend']['status_paused']}, after {results['pause_friend']['status_after']}")
        h1 = host.ram(0, 3)
        time.sleep(1)
        h2 = host.ram(0, 3)
        if not h1 or not h2 or frame_of(h2) - frame_of(h1) < 30:
            fail(f"the game didn't carry on after the friend resumed: {h1} {h2}")
        if menu_shown(app):
            fail("\"Paused by\" stayed on the host's screen after the friend resumed")

        say("right player check")
        buttons_check(host, friend, pad_a, "A", 0)
        buttons_check(host, friend, pad_b, "B", 1)

        say(f"{MASH_SECONDS} s of random presses on both pads")
        results["sync"] = sync_round(host, friend, pad_a, pad_b, MASH_SECONDS, 7)
        screenshot("3-after-sync")

        say("the friend switches to watching")
        status, lobby = friend_api.call("POST", f"/api/lobbies/{code}/switch", {"as": "watch"})
        if status != 200 or lobby.get("you", {}).get("role") != "watch":
            fail(f"switch to watch refused: {status} {lobby}")
        friend.send("NETPLAY_GAME_WATCH")
        time.sleep(2)
        set_pad(pad_b, [B.XUSB_GAMEPAD_A])
        time.sleep(1.5)
        a = host.ram(0x10, 2)
        set_pad(pad_b, [])
        if not a or a[1] != 0:
            fail(f"pad B still reaches player 2 after switching to watching: {a.hex() if a else None}")
        else:
            say("  pad B no longer reaches the game")
        status, lobby = friend_api.call("POST", f"/api/lobbies/{code}/switch", {"as": "play"})
        friend.send("NETPLAY_GAME_WATCH")
        if status != 200 or lobby.get("you", {}).get("seat") != 2:
            fail(f"switch back to play didn't give seat 2: {status} {lobby}")
        time.sleep(3)
        buttons_check(host, friend, pad_b, "B (back from watching)", 1)

        say("the friend's game closes suddenly: the host's game must keep going, seat 2 held")
        beat.on.clear()
        before = host.ram(0, 3)
        friend.kill()
        time.sleep(1)
        frames = []
        for _ in range(8):
            m = host.ram(0, 3)
            frames.append(frame_of(m) if m else None)
            time.sleep(0.5)
        if None in frames or frames != sorted(frames) or frames[-1] - frames[0] < 150:
            fail(f"the host's game didn't keep going after the friend dropped: {frames}")
        else:
            say(f"  host kept playing ({frames[-1] - frames[0]} frames in 3.5 s)")
        _, view = friend_api.call("GET", f"/api/lobbies/{code}")
        held = wait_until(lambda: seat(friend_api.call("GET", f"/api/lobbies/{code}")[1], 2).get("status") == "held" or None, 25, 1)
        if not held:
            fail(f"seat 2 wasn't held for the dropped friend: {friend_api.call('GET', f'/api/lobbies/{code}')}")
        else:
            say("  seat 2 is held for the friend")
        screenshot("4-friend-dropped")

        say("the friend rejoins with the same code")
        status, lobby = friend_api.call("POST", f"/api/lobbies/{code}/join", {"as": "play"})
        if status != 200 or lobby.get("you", {}).get("seat") != 2:
            fail(f"rejoin didn't give seat 2 back: {status} {lobby}")
        else:
            beat.on.set()
            friend.start(friend_rom, lobby["relay"], 2)
            t = time.time()
            if not wait_until(lambda: connected(host, friend), 60, 0.25):
                fail("the friend didn't reconnect within 60 s")
            else:
                results["rejoin_seconds"] = round(time.time() - t, 1)
                buttons_check(host, friend, pad_b, "B (after rejoin)", 1)
                results["sync_after_rejoin"] = sync_round(host, friend, pad_a, pad_b, 20, 8)
        if app.poll() is not None:
            fail(f"the Game Night app closed during the test (exit {app.returncode})")

        say("refresh: the in-game menu's REFRESH GAME. The host's game saves its spot, restarts and loads the spot again")
        window_watch.focus_app(app.pid)
        old_port = ra_cmd_port()
        m = host.ram(0, 3)
        before = frame_of(m) if m else None
        menu(app, pad_a, "refresh")
        new_port = wait_until(lambda: (p := ra_cmd_port()) and p != old_port and p, 30, 0.5)
        if not new_port or before is None:
            fail(f"refresh: the game didn't restart (port {old_port} -> {new_port}, frame before {before})")
        else:
            host = Ask(new_port)
            time.sleep(6)  # started, then the spot loaded 1.5 s after
            m = host.ram(0, 3)
            after = frame_of(m) if m else None
            results["refresh"] = {"frame_before": before, "frame_after": after}
            say(f"  frame before {before}, after {after}")
            if after is None or after < before:
                fail(f"refresh: the game didn't come back at the saved spot (frame {before} before, {after} after)")
            look("look-2f-after-refresh", app, True)

        say("look: Game Night started again as a window (not full screen), hosting a new lobby")
        friend.kill()
        app.kill()
        app.wait(15)
        logs = Path(os.environ.get("LOCALAPPDATA", "")) / "xyz.jjsnas.gamenight" / "player" / "logs"
        for name in ("gamebox.log", "couch.log", "retroarch.log", "ingame.txt", "relay.log", "retroarch-crash.log"):
            if (logs / name).exists():
                (OUT / f"host-{name.split('.')[0]}-full-screen-run.log").write_bytes((logs / name).read_bytes())
        info_file.unlink(missing_ok=True)
        time.sleep(2)
        app = subprocess.Popen([str(APP)], env=dict(env, GAMENIGHT_E2E_WINDOWED="1"), stdout=app_log, stderr=subprocess.STDOUT)
        info = wait_until(lambda: info_file.exists() and json.loads(info_file.read_text() or "{}"), 120, 0.5)
        if not info or "code" not in info:
            fail(f"the windowed app didn't host a lobby within 120 s: {info}")
        else:
            look("look-3-windowed", app, False)
            say("look: the window is moved and made bigger")
            window_watch.move_app(app.pid, 40, 30, 1500, 900)
            look("look-4-windowed-moved", app, False)
    finally:
        friend.kill()
        (OUT / "friend-retroarch.log").write_text(friend.log())
        if app.poll() is None:
            app.kill()
        server.kill()
        for name in ("retroarch.log", "relay.log", "couch.log", "gamebox.log", "ingame.txt", "retroarch-crash.log"):
            for base in (Path(os.environ.get("LOCALAPPDATA", "")) / "xyz.jjsnas.gamenight" / "player" / "logs",):
                src = base / name
                if src.exists():
                    (OUT / f"host-{name}").write_bytes(src.read_bytes())


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        say(traceback.format_exc())
        fail(f"the test stopped with {type(e).__name__}: {e}")
    summary = {"ok": not failures, "failures": failures, **results}
    (OUT / "results.json").write_text(json.dumps(summary, indent=2))
    say(json.dumps(summary, indent=2))
    for f in failures:
        print(f"::error::couch app test: {f}", flush=True)
    sys.exit(1 if failures else 0)
