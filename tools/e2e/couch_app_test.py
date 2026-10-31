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


def look(name, app, full_screen, game_full=False):
    """Watches the game window for 6 s, takes 3 quick screenshots, and checks it sits still in the box."""
    time.sleep(3)  # the lobby screen fades in, then the box is sent
    summary, samples = window_watch.watch(app.pid, 6)
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
        fail(f"{name}: the game window moved or resized {summary['place_changes']} times in 6 s (flicker)")
    if not summary["game_inside_app"]:
        fail(f"{name}: the game isn't inside Game Night's window: {summary['last_game']} vs {summary['last_app_inside']}")
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
            "netplay_check_frames": "0", "netplay_nickname": "Friend",
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


def frame_of(mem):
    return mem[0] | mem[1] << 8 | mem[2] << 16


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
        host = Ask(int(info["cmd_port"]))
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
        say("look: hold L3 + R3 for lobby controls, then Y: the game goes full screen")
        for name, full in (("look-2b-game-full-screen", True), ("look-2c-back-to-the-box", False)):
            set_pad(pad_a, [B.XUSB_GAMEPAD_LEFT_THUMB, B.XUSB_GAMEPAD_RIGHT_THUMB])
            time.sleep(1.4)
            set_pad(pad_a, [])
            time.sleep(0.6)
            set_pad(pad_a, [B.XUSB_GAMEPAD_Y])
            time.sleep(0.2)
            set_pad(pad_a, [])
            look(name, app, True, game_full=full)

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

        say("look: Game Night started again as a window (not full screen), hosting a new lobby")
        friend.kill()
        app.kill()
        app.wait(15)
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
        for name in ("retroarch.log", "relay.log", "couch.log", "gamebox.log"):
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
