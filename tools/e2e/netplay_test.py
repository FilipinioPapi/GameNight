#!/usr/bin/env python3
"""CI only (GitHub's Windows machine): two copies of Game Night's pinned RetroArch play the netplay test
cartridge together over the network, each with its own pretend Xbox pad, and we measure whether it works.

    python netplay_test.py <player folder> <work folder> <results folder>

<player folder> is what tools/player/fetch_player.py builds (retroarch.exe + cores). Nothing is installed
or changed outside <work folder> and <results folder>. The "direct" and "delayed" rounds stay on this
machine (loopback address, with netplay's public lobby, NAT punching and relay servers switched off); only
the relay rounds below go to the internet, to libretro's lobby and relay servers.

The "host" copy is player 1 and reads only pretend pad A; the "friend" copy joins it as player 2 and
reads only pretend pad B. Both copies have RetroArch's local command port on (each its own), so the test
can read the cartridge's RAM (see make_netplay_rom.py) from both while they play.

Each round:
  1. Connect: start the host, then the friend. Connected means the friend's game jumped to the host's
     frame (netplay hands the friend the host's game state) and both keep counting together.
  2. Right player: hold each NES button on pad A, then on pad B, and read players 1 and 2 in BOTH copies.
  3. Stay in sync: both pads press random buttons for a while. Every quarter second, compare the
     cartridge's per-frame fingerprints from both copies for every frame both have finished. One
     different fingerprint means the two games went apart.
  4. At the end: both copies' button-change lists must be identical, every player 1 entry must be a
     button state pad A was given (pad B for player 2), and the fingerprint chain must add up.

Rounds (NETPLAY_ROUNDS picks some by name; all by default):
  - "direct": straight connection on this machine.
  - "delayed": through a small relay in this script that adds internet-like delay and jitter both ways.
  - "relay-listed-<place>": through libretro's public relay the way stock RetroArch does it: the host asks
    libretro's lobby for the relay, gets a session from it and lists the game in libretro's PUBLIC game list
    (one connection only, so nobody else can join once the friend is in); the friend finds the session there
    and joins.
  - "relay-private-<place>": through the same public relay, but the host's relay session is held by a small
    bridge in this script (TunnelBridge) and passed straight to the friend, so nothing is listed anywhere.
    The host copy itself only listens on this machine.
  - "reconnect-<place>": the friend joins through the relay, leaves and joins again, several times.
Each round also measures how long a press takes to show up in your own game and in the other player's.
RetroArch's own repair of a desync (netplay_check_frames) is off, so any desync stays visible instead of
being quietly patched.
"""
import asyncio
import base64
import ctypes
import json
import secrets
import statistics
import struct
import urllib.request
import os
import random
import socket
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import vgamepad as vg
import vgamepad.win.vigem_client as vcli

sys.path.insert(0, str(Path(__file__).parent))
import make_netplay_rom as cart  # noqa: E402

PLAYER, WORK, OUT = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
TOOLS = Path(__file__).parent
EXE = PLAYER / "retroarch.exe"
CORE = PLAYER / "cores" / "fceumm_libretro.dll"
NETPLAY_PORT = 55435
RELAY_PORT = 55436
MASH_SECONDS = int(os.environ.get("NETPLAY_MASH_SECONDS", "90"))
SHORT_MASH_SECONDS = 30  # the far-away relays get a shorter sync check
LONG_MASH_SECONDS = 300  # the long rounds through the nearest relay
ONLY_ROUNDS = [r for r in os.environ.get("NETPLAY_ROUNDS", "").replace(",", " ").split() if r]
LOBBY = "http://lobby.libretro.com/"  # what RetroArch 1.22.2 itself uses (file_path_special.h)
PRESSES = 15  # presses per pad for the press-delay measurement
MARGIN = 60  # only compare frames at least this many frames old in both copies (newer ones may still be redone)
B = vg.XUSB_BUTTON
# Xbox button -> NES bit in the cartridge's $10/$11 (RetroArch's standard layout: Xbox A is the NES B spot).
NES = [
    ("A", B.XUSB_GAMEPAD_A, 0x40), ("B", B.XUSB_GAMEPAD_B, 0x80),
    ("View", B.XUSB_GAMEPAD_BACK, 0x20), ("Menu", B.XUSB_GAMEPAD_START, 0x10),
    ("Up", B.XUSB_GAMEPAD_DPAD_UP, 0x08), ("Down", B.XUSB_GAMEPAD_DPAD_DOWN, 0x04),
    ("Left", B.XUSB_GAMEPAD_DPAD_LEFT, 0x02), ("Right", B.XUSB_GAMEPAD_DPAD_RIGHT, 0x01),
]

failures = []


def say(m=""):
    print(m, flush=True)


def fail(m):
    failures.append(m)
    say(f"  FAIL: {m}")


def screenshot(name):
    subprocess.run(["pwsh", "-NoProfile", "-File", str(TOOLS / "screenshot.ps1"), str(OUT / f"{name}.png")], check=False)


# ---------------------------------------------------------------- pretend pads

def plug(label):
    pad = vg.VX360Gamepad()
    time.sleep(1.5)
    slot = ctypes.c_ulong(99)
    err = vcli.vigem_target_x360_get_user_index(pad._busp, pad._devicep, ctypes.addressof(slot))
    say(f"pretend pad {label} plugged in: bus number {pad.get_index()}, Xbox slot {slot.value} (answer {err:#x})")
    return pad, (slot.value if err == 0x20000000 else None)


def set_pad(pad, mask_buttons):
    pad.reset()
    for button in mask_buttons:
        pad.press_button(button=button)
    pad.update()


# ---------------------------------------------------------------- RetroArch copies

class Copy:
    def __init__(self, name, cmd_port, pad_slot):
        self.name, self.cmd_port, self.pad_slot = name, cmd_port, pad_slot
        self.dir = WORK / name
        self.proc = None

    def write_config(self, x, extra=None):
        for d in ("logs", "saves", "states", "system", "cache"):
            (self.dir / d).mkdir(parents=True, exist_ok=True)
        p = lambda q: str(q).replace('"', "")  # noqa: E731
        settings = {
            # Same "no extras" basics as Game Night's own settings (app/src-tauri/src/games.rs).
            "config_save_on_exit": "false", "menu_driver": "rgui", "input_menu_toggle": "nul",
            "input_menu_toggle_gamepad_combo": "0", "input_quit_gamepad_combo": "0", "input_desktop_menu_toggle": "nul",
            "ui_companion_enable": "false", "ui_companion_start_on_boot": "false", "desktop_menu_enable": "false",
            "menu_show_online_updater": "false", "menu_show_core_updater": "false", "stdin_cmd_enable": "false",
            "cheevos_enable": "false", "discord_allow": "false", "history_list_enable": "false",
            "game_specific_options": "false", "auto_overrides_enable": "false", "auto_remaps_enable": "false",
            "auto_shaders_enable": "false", "savestate_auto_load": "false", "savestate_auto_save": "false",
            "rewind_enable": "false", "input_hold_fast_forward": "nul", "input_toggle_fast_forward": "nul",
            "input_exit_emulator": "nul",
            # The test reads the cartridge's RAM through this (this machine only).
            "network_cmd_enable": "true", "network_cmd_port": str(self.cmd_port),
            # Netplay: by default this machine only. No public lobby, no NAT punching, no relay servers.
            # (The relay rounds change some of these through `extra`.)
            "netplay_public_announce": "false", "netplay_nat_traversal": "false", "netplay_use_mitm_server": "false",
            "netplay_check_frames": "0", "netplay_nickname": self.name, "netplay_ping_show": "false",
            # Two windows side by side; both keep running when not in front.
            "video_driver": "d3d11", "video_fullscreen": "false", "video_windowed_fullscreen": "false",
            "video_scale": "2", "video_window_save_positions": "true",
            "video_windowed_position_x": str(x), "video_windowed_position_y": "40",
            "video_windowed_position_width": "512", "video_windowed_position_height": "480",
            "pause_nonactive": "false", "video_font_enable": "true",
            # No sound on the CI machine: a plain 60 frames-a-second speed limit instead (measured below).
            "audio_enable": "false", "video_vsync": "false", "vrr_runloop_enable": "true",
            # Controllers: this copy's player 1 is its own pad only; nothing else.
            "input_joypad_driver": "xinput", "input_autodetect_enable": "true",
            "joypad_autoconfig_dir": p(PLAYER / "autoconfig"), "input_max_users": "2",
            "input_player1_joypad_index": str(self.pad_slot), "input_player2_joypad_index": "15",
            "libretro_directory": p(PLAYER / "cores"), "savefile_directory": p(self.dir / "saves"),
            "savestate_directory": p(self.dir / "states"), "system_directory": p(self.dir / "system"),
            "cache_directory": p(self.dir / "cache"),
            "log_to_file": "true", "log_to_file_timestamp": "false", "log_verbosity": "true",
            "frontend_log_level": "0", "libretro_log_level": "2", "log_dir": p(self.dir / "logs"),
        }
        settings.update(extra or {})
        self.cfg = self.dir / "retroarch.cfg"
        self.cfg.write_text("".join(f'{k} = "{v}"\n' for k, v in settings.items()), encoding="ascii")

    def start(self, rom, netplay_args):
        log = self.dir / "logs" / "retroarch.log"
        log.unlink(missing_ok=True)
        args = [str(EXE), "-c", str(self.cfg), "-L", str(CORE), *netplay_args, str(rom)]
        say(f"starting {self.name}: {' '.join(args[1:])}")
        self.proc = subprocess.Popen(args, cwd=str(PLAYER))

    def log_text(self):
        try:
            return (self.dir / "logs" / "retroarch.log").read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return ""

    def ask(self, command, timeout=1.0):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.sendto(command.encode(), ("127.0.0.1", self.cmd_port))
            try:
                return s.recv(65536).decode(errors="replace").strip()
            except OSError:
                return None

    def ram(self, start, length):
        """Bytes of the cartridge's RAM, or None."""
        answer = self.ask(f"READ_CORE_MEMORY {start:x} {length}")
        got = parse_ram(answer, length)
        if got is None:
            self.last_bad_answer = (answer or "(no answer)")[:200]
        return got

    def quit(self):
        if self.proc and self.proc.poll() is None:
            self.ask("QUIT")
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def parse_ram(answer, length):
    parts = (answer or "").split()
    if len(parts) == length + 2 and parts[0] == "READ_CORE_MEMORY":
        try:
            return bytes(int(x, 16) for x in parts[2:])
        except ValueError:
            pass
    return None


def ram_at_once(copies, start, length, timeout=1.0):
    """Asks every copy at the same moment (each answers on its next frame), so timing two copies doesn't
    add their waits together. Returns {copy: bytes or None}."""
    command = f"READ_CORE_MEMORY {start:x} {length}".encode()
    by_port = {c.cmd_port: c for c in copies}
    got = {c: None for c in copies}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        for c in copies:
            s.sendto(command, ("127.0.0.1", c.cmd_port))
        for _ in copies:
            try:
                data, addr = s.recvfrom(65536)
            except OSError:
                break
            if addr[1] in by_port:
                got[by_port[addr[1]]] = parse_ram(data.decode(errors="replace").strip(), length)
    return got


def frame_of(mem):
    return mem[0] | mem[1] << 8 | mem[2] << 16


# ---------------------------------------------------------------- internet-like delay

class DelayRelay(threading.Thread):
    """Passes the friend's connection on to the host, holding every piece of data back by delay ± jitter
    (in order, like the internet does for one connection). Counts what went through."""

    def __init__(self, listen_port, target_port, delay_ms, jitter_ms, seed):
        super().__init__(daemon=True)
        self.listen_port, self.target_port = listen_port, target_port
        self.delay, self.jitter = delay_ms / 1000, jitter_ms / 1000
        self.rng = random.Random(seed)
        self.ready = threading.Event()
        self.stats = {"connections": 0, "friend_to_host_bytes": 0, "host_to_friend_bytes": 0, "pieces": 0, "max_hold_ms": 0.0}

    def run(self):
        asyncio.run(self.main())

    async def main(self):
        server = await asyncio.start_server(self.handle, "127.0.0.1", self.listen_port)
        self.ready.set()
        async with server:
            await server.serve_forever()

    async def handle(self, reader, writer):
        self.stats["connections"] += 1
        up_reader, up_writer = await asyncio.open_connection("127.0.0.1", self.target_port)
        await asyncio.gather(self.pipe(reader, up_writer, "friend_to_host_bytes"),
                             self.pipe(up_reader, writer, "host_to_friend_bytes"), return_exceptions=True)

    async def pipe(self, reader, writer, counter):
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        last = 0.0

        async def send():
            while True:
                due, data = await queue.get()
                if data is None:
                    writer.close()
                    return
                wait = due - loop.time()
                if wait > 0:
                    await asyncio.sleep(wait)
                writer.write(data)
                await writer.drain()

        sender = asyncio.ensure_future(send())
        while True:
            data = await reader.read(65536)
            now = loop.time()
            if not data:
                await queue.put((now, None))
                break
            due = max(now + self.delay + self.rng.uniform(-self.jitter, self.jitter), last)
            last = due
            self.stats[counter] += len(data)
            self.stats["pieces"] += 1
            self.stats["max_hold_ms"] = max(self.stats["max_hold_ms"], round((due - now) * 1000, 1))
            await queue.put((due, data))
        await sender


# ---------------------------------------------------------------- libretro's public relay

# Relay ("tunnel") messages, from RetroArch 1.22.2 network/netplay/netplay_frontend.c. Each id is a 4-byte
# magic plus 12 bytes; an address is 16 bytes.
RATS = 0x52415453  # session: ask for a new one (12 zero bytes) / the session id the relay gives back
RATL = 0x5241544C  # link: a friend arrived; open a new connection to the relay and send this id on it
RATA = 0x52415441  # address: ask for / receive the arriving friend's address
RATP = 0x52415450  # ping: the relay checks the host is still there; answer with the same 4 bytes


def lobby_get(path, timeout=15):
    with urllib.request.urlopen(LOBBY + path, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def relay_address(place):
    """Ask libretro's lobby where a relay is, exactly like RetroArch does (tunnel?name=<place>)."""
    fields = dict(line.split("=", 1) for line in lobby_get(f"tunnel?name={place}").splitlines() if "=" in line)
    return fields["tunnel_addr"], int(fields["tunnel_port"])


def connect_times(host, port, n=5):
    """How long a plain connection to the relay takes from this machine (one round trip), in ms."""
    out = []
    for _ in range(n):
        t = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=10):
                out.append(round((time.perf_counter() - t) * 1000, 1))
        except OSError as e:
            out.append(None)
            say(f"  connection to {host}:{port} failed: {e}")
        time.sleep(0.3)
    return out


def find_in_lobby(nick, seconds):
    """Our host's entry in libretro's public game list (only our own entry is kept, nobody else's)."""
    end = time.time() + seconds
    while time.time() < end:
        try:
            for room in json.loads(lobby_get("list")):
                f = room.get("fields", {})
                if f.get("username") == nick:
                    return f
        except (OSError, ValueError) as e:
            say(f"  lobby list read failed: {e}")
        time.sleep(1)
    return None


class TunnelBridge(threading.Thread):
    """Holds a relay session for the host without listing anything publicly: asks libretro's relay for a
    session, and when a friend arrives through it, opens the link the way RetroArch's host would and passes
    it to the host copy on this machine (127.0.0.1). Counts what went through."""

    def __init__(self, relay_host, relay_port, target_port):
        super().__init__(daemon=True)
        self.relay = (relay_host, relay_port)
        self.target_port = target_port
        self.ready = threading.Event()
        self.session = None
        self.error = None
        self.stats = {"session_seconds": None, "relay_pings": 0, "links": 0, "links_failed": 0,
                      "friend_to_host_bytes": 0, "host_to_friend_bytes": 0}
        self.loop = None
        self.writer = None
        self.t0 = time.time()
        self.events = []  # what happened on the relay connections, with seconds since the bridge started

    def note(self, what):
        self.events.append((round(time.time() - self.t0, 2), what))
        say(f"  bridge @{self.events[-1][0]} s: {what}")

    def run(self):
        try:
            asyncio.run(self.main())
        except Exception as e:  # noqa: BLE001 - reported by the round
            self.error = f"{type(e).__name__}: {e}"
            self.ready.set()

    def stop(self):
        self.note("the test is ending the session (closing our side)")
        if self.loop and self.writer:
            self.loop.call_soon_threadsafe(self.writer.close)

    async def main(self):
        self.loop = asyncio.get_running_loop()
        t = time.perf_counter()
        reader, writer = await asyncio.wait_for(asyncio.open_connection(*self.relay), 15)
        self.writer = writer
        writer.write(struct.pack("!I", RATS) + bytes(12))
        await writer.drain()
        answer = await asyncio.wait_for(reader.readexactly(16), 15)
        if struct.unpack("!I", answer[:4])[0] != RATS or answer[4:] == bytes(12):
            raise RuntimeError(f"the relay gave no session: {answer.hex()}")
        self.stats["session_seconds"] = round(time.perf_counter() - t, 2)
        self.session = base64.b64encode(answer[4:]).decode()
        self.ready.set()
        waiting = {}  # link id -> future for the friend's address
        while True:
            try:
                magic = struct.unpack("!I", await reader.readexactly(4))[0]
            except (asyncio.IncompleteReadError, ConnectionError) as e:
                self.note(f"the relay closed the session connection ({type(e).__name__})")
                return
            if magic == RATP:
                writer.write(struct.pack("!I", RATP))
                await writer.drain()
                self.stats["relay_pings"] += 1
            elif magic == RATL:
                link = await reader.readexactly(12)
                fut = self.loop.create_future()
                waiting[link] = fut
                asyncio.ensure_future(self.open_link(link, fut, writer))
            elif magic == RATA:
                link = await reader.readexactly(12)
                addr = await reader.readexactly(16)
                fut = waiting.pop(link, None)
                if fut and not fut.done():
                    fut.set_result(addr)
            else:
                raise RuntimeError(f"unknown message from the relay: {magic:#x}")

    async def open_link(self, link, addr_future, control):
        try:
            up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(*self.relay), 15)
            control.write(struct.pack("!I", RATA) + link)  # same order as RetroArch: ask for the address
            await control.drain()
            await asyncio.wait_for(addr_future, 15)
            up_writer.write(struct.pack("!I", RATL) + link)
            await up_writer.drain()
            host_reader, host_writer = await asyncio.open_connection("127.0.0.1", self.target_port)
            self.stats["links"] += 1
            n = self.stats["links"]
            self.note(f"link {n}: a friend arrived through the relay and is passed to the host")
        except Exception as e:  # noqa: BLE001
            self.stats["links_failed"] += 1
            self.note(f"a friend's link failed: {type(e).__name__}: {e}")
            return
        await asyncio.gather(self.pipe(up_reader, host_writer, "friend_to_host_bytes", f"link {n}: relay side (friend)"),
                             self.pipe(host_reader, up_writer, "host_to_friend_bytes", f"link {n}: host side"),
                             return_exceptions=True)

    async def pipe(self, reader, writer, counter, label):
        """Copies one direction. Notes which side ended the link first and how, so a dropped connection
        can be pinned on the relay, the host or this bridge."""
        how = "closed it (end of data)"
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                self.stats[counter] += len(data)
                writer.write(data)
                await writer.drain()
        except Exception as e:  # noqa: BLE001
            how = f"broke: {type(e).__name__}: {e}"
        finally:
            self.note(f"{label} {how}")
            writer.close()


# ---------------------------------------------------------------- one round

def wait_until(check, seconds, step=0.25):
    end = time.time() + seconds
    while time.time() < end:
        result = check()
        if result:
            return result
        time.sleep(step)
    return None


def read_both(host, friend):
    return host.ram(0, 1024), friend.ram(0, 1024)


def buttons_check(host, friend, pad, label, expect_player):
    """Hold each button on one pad; both copies must show it on the expected player only."""
    wrong = []
    for name, button, bit in NES:
        set_pad(pad, [button])
        time.sleep(0.5)
        h, f = host.ram(0x10, 2), friend.ram(0x10, 2)
        set_pad(pad, [])
        want = (bit, 0) if expect_player == 1 else (0, bit)
        got_h = tuple(h) if h else None
        got_f = tuple(f) if f else None
        status = "ok" if got_h == want and got_f == want else "WRONG"
        say(f"  pad {label} holds {name:5}: host sees P1 {fmt(got_h, 0)} P2 {fmt(got_h, 1)} | friend sees P1 {fmt(got_f, 0)} P2 {fmt(got_f, 1)}  {status}")
        if status != "ok":
            wrong.append(f"{name}: wanted P1 {want[0]:#04x} P2 {want[1]:#04x}, host {got_h}, friend {got_f}")
        time.sleep(0.3)
    return wrong


def fmt(t, i):
    return "--" if t is None else f"{t[i]:02x}"


def nes_view(state):
    """What the emulator passes on for a pad state: fceumm drops Up+Down and Left+Right pressed together
    (its "Allow opposing directions" option is off by default; libretro.c, up_down_allowed)."""
    if state & 0x0C == 0x0C:
        state &= ~0x0C
    if state & 0x03 == 0x03:
        state &= ~0x03
    return state


def mash(pads, seconds, seed, sent, stop, timeline):
    """Both pads press random buttons. Records every state each pad was given (as NES bits), and when."""
    rng = random.Random(seed)
    end = time.time() + seconds
    while time.time() < end and not stop.is_set():
        for key, pad in pads.items():
            if rng.random() < 0.5:
                chosen = [(button, bit) for _, button, bit in NES if rng.random() < 0.3]
                set_pad(pad, [b for b, _ in chosen])
                state = sum(bit for _, bit in chosen)
                sent[key].add(nes_view(state))
                timeline.append((time.time(), key, state))
        time.sleep(rng.uniform(0.03, 0.15))
    for pad in pads.values():
        set_pad(pad, [])


def press_delays(host, friend, pad_a, pad_b, n=PRESSES):
    """Press A on one pad and time how long until each game shows it: the presser's own game and the other
    player's game. Readings come once a frame, so each number is accurate to about one frame (~17-22 ms)."""
    out = {}
    rng = random.Random(3)
    for key, pad, own, other, idx in (("host_pad_a", pad_a, host, friend, 0), ("friend_pad_b", pad_b, friend, host, 1)):
        out[key] = {"own_game_ms": [], "other_game_ms": []}
    for _ in range(n):
        for key, pad, own, other, idx in (("host_pad_a", pad_a, host, friend, 0), ("friend_pad_b", pad_b, friend, host, 1)):
            seen = {own: None, other: None}
            set_pad(pad, [B.XUSB_GAMEPAD_A])
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < 3 and None in seen.values():
                for c, mem in ram_at_once([c for c in seen if seen[c] is None], 0x10, 2).items():
                    if mem and mem[idx] & 0x40:
                        seen[c] = round((time.perf_counter() - t0) * 1000, 1)
            set_pad(pad, [])
            out[key]["own_game_ms"].append(seen[own])
            out[key]["other_game_ms"].append(seen[other])
            wait_until(lambda: all(m and not m[idx] & 0x40 for m in ram_at_once([own, other], 0x10, 2).values()), 3, 0.02)
            time.sleep(rng.uniform(0.1, 0.3))
    for key, v in out.items():
        pairs = [(a, b) for a, b in zip(v["own_game_ms"], v["other_game_ms"]) if a is not None and b is not None]
        v["missed"] = sum(1 for a, b in zip(v["own_game_ms"], v["other_game_ms"]) if a is None or b is None)
        v["summary"] = {
            "own_game": spread([a for a, _ in pairs]), "other_game": spread([b for _, b in pairs]),
            "extra_for_other_player": spread([round(b - a, 1) for a, b in pairs]),
        }
    return out


def spread(xs):
    if not xs:
        return None
    xs = sorted(xs)
    return {"median": round(statistics.median(xs), 1), "p90": xs[min(len(xs) - 1, int(0.9 * len(xs)))],
            "min": xs[0], "max": xs[-1], "n": len(xs)}


def run_round(name, rom, pad_a, slot_a, pad_b, slot_b, delay=None, place=None, listed=False,
              mash_seconds=MASH_SECONDS, reconnects=0):
    say(f"\n################ round: {name} ################")
    result = {"round": name, "ok": False}
    host = Copy(f"host-{name}", 55355, slot_a)
    friend = Copy(f"friend-{name}", 55356, slot_b)
    host_extra, friend_extra = {}, {}
    if place:
        try:
            relay_host, relay_port = relay_address(place)
        except (OSError, KeyError, ValueError) as e:
            fail(f"{name}: libretro's lobby didn't say where the {place} relay is ({e})")
            return result
        plain = connect_times(relay_host, relay_port)
        ok_times = [t for t in plain if t is not None]
        result["relay"] = {"place": place, "address": f"{relay_host}:{relay_port}", "plain_connect_ms": plain,
                           "plain_connect_median_ms": statistics.median(ok_times) if ok_times else None}
        say(f"{place} relay is {relay_host}:{relay_port}; a plain connection from this machine takes {plain} ms")
    if listed:
        # Stock RetroArch: the host lists the game in libretro's public list. No password: RetroArch's friend side
        # ignores netplay_password and always pops up a box to TYPE it (netplay_handshake_init: menu_input_dialog),
        # which stalled run 41167800601. Instead the host takes one connection only, so once our friend is in,
        # nobody else can join; anyone sneaking in first would show up in the right-player checks.
        nick = f"gn-ci-{secrets.token_hex(3)}"
        host_extra = {"netplay_public_announce": "true", "netplay_use_mitm_server": "true", "netplay_mitm_server": place,
                      "netplay_nickname": nick, "netplay_max_connections": "1"}
    host.write_config(0, host_extra)
    friend.write_config(520, friend_extra)
    delayer = bridge = None
    samples = []
    try:
        t_host = time.time()
        host.start(rom, ["--host", "--port", str(NETPLAY_PORT)])
        if not wait_until(lambda: host.ram(0, 3), 40):
            fail(f"{name}: the host copy never answered ({getattr(host, 'last_bad_answer', '')})")
            return result
        time.sleep(3)
        connect_args = ["--connect", "127.0.0.1", "--port", str(NETPLAY_PORT)]
        if delay:
            delayer = DelayRelay(RELAY_PORT, NETPLAY_PORT, *delay, seed=11)
            delayer.start()
            delayer.ready.wait(10)
            connect_args = ["--connect", "127.0.0.1", "--port", str(RELAY_PORT)]
            say(f"delay relay on port {RELAY_PORT}: {delay[0]} ms ± {delay[1]} ms each way")
        if listed:
            entry = find_in_lobby(nick, 60)
            if not entry:
                fail(f"{name}: the host never showed up in libretro's public game list")
                return result
            result["lobby"] = {
                "listed_after_seconds": round(time.time() - t_host, 1),
                "fields_anyone_can_read": sorted(entry),
                "lists_host_internet_address": bool(entry.get("ip")),
                "country_shown": bool(entry.get("country")), "game_name_shown": entry.get("game_name"),
                "nickname_shown": entry.get("username") == nick, "has_password": entry.get("has_password"),
                "relay": f"{entry.get('mitm_ip')}:{entry.get('mitm_port')}", "host_method": entry.get("host_method"),
            }
            say(f"host listed in libretro's public game list after {result['lobby']['listed_after_seconds']} s: {result['lobby']}")
            if not entry.get("mitm_session"):
                fail(f"{name}: the public listing has no relay session")
                return result
            connect_args = ["--connect", entry["mitm_ip"], "--port", str(entry["mitm_port"]),
                            f"--mitm-session={entry['mitm_session']}"]
        elif place:
            bridge = TunnelBridge(relay_host, relay_port, NETPLAY_PORT)
            bridge.start()
            bridge.ready.wait(30)
            if not bridge.session:
                fail(f"{name}: couldn't get a session from the {place} relay ({bridge.error})")
                return result
            say(f"bridge holds a {place} relay session (took {bridge.stats['session_seconds']} s); nothing is listed")
            connect_args = ["--connect", relay_host, "--port", str(relay_port), f"--mitm-session={bridge.session}"]
        host_frame_before = frame_of(host.ram(0, 3))
        t_join = time.time()
        friend.start(rom, connect_args)
        max_gap = 60 if place else 30

        # 1. Connect
        def joined():
            h, f = host.ram(0, 3), friend.ram(0, 3)
            if h and f:
                fh, ff = frame_of(h), frame_of(f)
                if ff > 60 and abs(fh - ff) < max_gap:
                    return fh, ff
            return None
        got = wait_until(joined, 45)
        result["connect_seconds"] = round(time.time() - t_join, 1)
        if not got:
            h, f = host.ram(0, 3), friend.ram(0, 3)
            fail(f"{name}: the friend never caught up with the host (host frame {h and frame_of(h)}, friend frame {f and frame_of(f)})")
            return result
        say(f"connected after {result['connect_seconds']} s: host frame {got[0]}, friend frame {got[1]} "
            f"(the host was on frame {host_frame_before} before the friend started, so the friend took the host's game)")
        result["host_frame_at_join"], result["friend_frame_at_join"] = got
        time.sleep(2)
        screenshot(f"{name}-1-connected")

        # 2. Right player
        say("\nright player check:")
        wrong = buttons_check(host, friend, pad_a, "A (host)", 1) + buttons_check(host, friend, pad_b, "B (friend)", 2)
        set_pad(pad_a, [B.XUSB_GAMEPAD_DPAD_RIGHT])
        set_pad(pad_b, [B.XUSB_GAMEPAD_DPAD_LEFT, B.XUSB_GAMEPAD_A])
        time.sleep(0.5)
        h, f = host.ram(0x10, 2), friend.ram(0x10, 2)
        set_pad(pad_a, [])
        set_pad(pad_b, [])
        both_ok = h and f and tuple(h) == (0x01, 0x42) and tuple(f) == (0x01, 0x42)
        say(f"  both at once (A: Right, B: Left + A): host {h and h.hex()}, friend {f and f.hex()}  {'ok' if both_ok else 'WRONG'}")
        if not both_ok:
            wrong.append(f"both at once: host {h and h.hex()}, friend {f and f.hex()} (wanted 0142)")
        result["right_player_problems"] = wrong
        if wrong:
            fail(f"{name}: buttons reached the wrong player: " + "; ".join(wrong))
        time.sleep(1)

        # How long a press takes to show up: in your own game, and in the other player's game
        delays = press_delays(host, friend, pad_a, pad_b)
        result["press_delay"] = delays
        for key, v in delays.items():
            sm = v["summary"]
            say(f"  press delay, {key}: own game {sm['own_game']}, other player's game {sm['other_game']}, "
                f"extra for the other player {sm['extra_for_other_player']} ms; missed {v['missed']}")
            if v["missed"]:
                fail(f"{name}: {v['missed']} of {PRESSES} presses on {key} never showed up in both games")
        time.sleep(1)

        # 3. Stay in sync
        say(f"\nsync check: both pads press random buttons for {mash_seconds} s; comparing every finished frame")
        # states the pads were given so far (the right-player checks above), then the random ones
        sent = {"a": {0, 0x01} | {bit for _, _, bit in NES}, "b": {0, 0x42} | {bit for _, _, bit in NES}}
        stop = threading.Event()
        timeline = []
        history = {"host": {}, "friend": {}}  # change number -> (full frame, P1, P2), kept once it can't be redone
        masher = threading.Thread(target=mash, args=({"a": pad_a, "b": pad_b}, mash_seconds, 5, sent, stop, timeline), daemon=True)
        checked, mismatches, bad_frames, bad_reads = set(), [], set(), 0
        first = None
        masher.start()
        shot_taken = False
        while masher.is_alive():
            t = time.time()
            a, b = read_both(host, friend)
            if not a or not b:
                bad_reads += 1
                time.sleep(0.25)
                continue
            fa, fb = frame_of(a), frame_of(b)
            settled = min(fa, fb) - MARGIN
            for who, mem, c in (("host", a, host), ("friend", b, friend)):
                lst = c.ram(0x400, 1024)
                if lst:
                    keep_changes(history[who], mem, lst, settled)
            first = first or (t, fa, fb)
            samples.append((round(t - first[0], 2), fa, fb))
            lo, hi = max(fa, fb) - 255, min(fa, fb) - MARGIN
            for fr in range(max(lo, 1), hi + 1):
                checked.add(fr)
                if a[0x300 + (fr & 0xFF)] != b[0x300 + (fr & 0xFF)] and fr not in bad_frames:
                    bad_frames.add(fr)
                    if len(mismatches) < 20:
                        mismatches.append({"frame": fr, "host": a[0x300 + (fr & 0xFF)], "friend": b[0x300 + (fr & 0xFF)], "at_s": samples[-1][0]})
            if not shot_taken and t - first[0] > 10:
                screenshot(f"{name}-2-playing")
                shot_taken = True
            time.sleep(max(0, 0.25 - (time.time() - t)))
        masher.join()
        span = (samples[0][1], samples[-1][1]) if samples else (0, 0)
        seconds = samples[-1][0] - samples[0][0] if len(samples) > 1 else 0
        fps_h = (samples[-1][1] - samples[0][1]) / seconds if seconds else 0
        fps_f = (samples[-1][2] - samples[0][2]) / seconds if seconds else 0
        gaps = [abs(x[1] - x[2]) for x in samples]
        result.update({
            "samples": len(samples), "unreadable_samples": bad_reads, "frames_checked": len(checked),
            "frames_played": span[1] - span[0], "mismatched_frames": len(bad_frames),
            "first_mismatches": mismatches, "host_fps": round(fps_h, 2), "friend_fps": round(fps_f, 2),
            "biggest_frame_gap": max(gaps) if gaps else None, "average_frame_gap": round(sum(gaps) / len(gaps), 1) if gaps else None,
            "pad_a_states": len(sent["a"]), "pad_b_states": len(sent["b"]),
        })
        say(f"  {len(samples)} looks, {len(checked)} frames compared out of about {span[1] - span[0]} played, "
            f"{len(bad_frames)} different; speed host {fps_h:.2f} / friend {fps_f:.2f} frames a second; "
            f"frame gap between the copies: biggest {result['biggest_frame_gap']}, average {result['average_frame_gap']}")
        drops = [l for c in (host, friend) for l in c.log_text().splitlines() if "disconnected" in l.lower()]
        result["dropped_during_play"] = drops
        if drops:
            fail(f"{name}: the connection dropped during play ({'; '.join(drops)}); after a drop the two games "
                 f"run on their own, so frames differ from then on")
        elif mismatches:
            fail(f"{name}: the two games went out of sync (first different frame {mismatches[0]['frame']})")
        if len(samples) < mash_seconds * 2:
            fail(f"{name}: too few readings ({len(samples)}) to trust the sync check")
        if span[1] - span[0] > 0 and len(checked) < 0.9 * (span[1] - span[0] - MARGIN):
            fail(f"{name}: only {len(checked)} of ~{span[1] - span[0]} frames could be compared")
        result["two_unconnected_copies_fps"] = round(SOLO_FPS, 2)
        # Over the internet a slower round is a finding to report, not a broken test, unless it's far off.
        slowest = 0.8 if place else 0.95
        for who, fps in (("host", fps_h), ("friend", fps_f)):
            if fps < slowest * SOLO_FPS or fps > 61:
                fail(f"{name}: the {who} ran at {fps:.1f} frames a second (two unconnected copies on this machine: {SOLO_FPS:.1f})")
            elif fps < 0.95 * SOLO_FPS:
                say(f"  NOTE: the {who} ran at {fps:.1f} frames a second, below the {SOLO_FPS:.1f} of two unconnected copies")

        # 4. End checks: change lists, right player under load, fingerprint chain
        time.sleep(2.5)
        end_h = host.ram(0, 1024), host.ram(0x400, 1024)
        end_f = friend.ram(0, 1024), friend.ram(0x400, 1024)
        if not all(end_h) or not all(end_f):
            fail(f"{name}: couldn't read the final state from both copies")
            return result
        ch, cf = end_h[0][8] | end_h[0][9] << 8, end_f[0][8] | end_f[0][9] << 8
        result["button_changes"] = {"host": ch, "friend": cf}
        lists_same = ch == cf and end_h[1] == end_f[1]
        result["change_lists_identical"] = lists_same
        say(f"\nend: {ch} button changes seen by the host's game, {cf} by the friend's; lists identical: {lists_same}")
        if not lists_same:
            fail(f"{name}: the two games' button-change lists differ")
        keep_changes(history["host"], end_h[0], end_h[1], frame_of(end_h[0]))
        keep_changes(history["friend"], end_f[0], end_f[1], frame_of(end_f[0]))
        hh, hf = history["host"], history["friend"]
        full_same = hh == hf
        missing = [k for k in range(ch) if k not in hh]
        result["whole_change_history_identical"] = full_same
        result["changes_never_read"] = len(missing)
        say(f"  whole button-change history ({len(hh)} of {ch} changes read along the way): identical in both copies: {full_same}")
        if not full_same:
            diff = [k for k in sorted(set(hh) | set(hf)) if hh.get(k) != hf.get(k)][:10]
            say(f"  first differences: {[(k, hh.get(k), hf.get(k)) for k in diff]}")
            fail(f"{name}: the two games' button-change histories differ")
        if missing:
            fail(f"{name}: {len(missing)} button changes were never read (first {missing[0]})")
        entries = [hh[k] for k in sorted(hh)]
        stray_1 = sorted({p1 for _, p1, _ in entries} - sent["a"])
        stray_2 = sorted({p2 for _, _, p2 in entries} - sent["b"])
        result["player1_states_not_from_pad_a"] = stray_1
        result["player2_states_not_from_pad_b"] = stray_2
        say(f"  every player 1 state came from pad A: {not stray_1}; every player 2 state from pad B: {not stray_2}"
            f" (pad A was given {len(sent['a'])} different states, pad B {len(sent['b'])})")
        explain_strays(entries, stray_1, stray_2, samples, first, timeline, result)
        (OUT / f"{name}-changes.csv").write_text("change,frame,p1,p2\n" + "".join(f"{k},{f},{p1},{p2}\n" for k, (f, p1, p2) in sorted(hh.items())))
        (OUT / f"{name}-pad-timeline.csv").write_text("seconds,pad,state\n" + "".join(f"{round(t - first[0], 3)},{k},{st}\n" for t, k, st in timeline))
        if stray_1 or stray_2:
            fail(f"{name}: buttons crossed between players during play (P1 extra {stray_1}, P2 extra {stray_2})")
        chain_ok, chain_frames = fingerprint_chain(end_h[0], entries)
        result["fingerprint_chain_ok"], result["fingerprint_chain_frames"] = chain_ok, chain_frames
        say(f"  fingerprint chain adds up over the last {chain_frames} frames: {chain_ok}")
        if not chain_ok:
            fail(f"{name}: the cartridge's fingerprint chain doesn't add up (test cartridge or emulator problem)")

        # Problems RetroArch itself wrote down
        for c in (host, friend):
            text = c.log_text()
            lines = [l for l in text.splitlines() if "netplay" in l.lower()]
            bad = [l for l in lines if any(k in l.lower() for k in ("mismatch", "desync", "disconnect", "failed", "error"))]
            result[f"{c.name.split('-')[0]}_netplay_log_problems"] = bad[:20]
            say(f"\n{c.name}: {len(lines)} netplay lines in RetroArch's log, {len(bad)} look like problems")
            for l in lines[:60]:
                say(f"  | {l}")
        if delayer:
            result["delay_relay"] = dict(delayer.stats, delay_ms=delay[0], jitter_ms=delay[1])
            say(f"delay relay: {delayer.stats}")

        # Leave and join again (same session), checking the friend is still player 2 each time
        if reconnects:
            result["reconnects"] = rejoin(name, rom, host, friend, pad_b, connect_args, reconnects, max_gap)
        result["ok"] = not [f for f in failures if f.startswith(f"{name}:")]
        return result
    finally:
        if bridge:
            result.setdefault("relay", {})["bridge"] = dict(bridge.stats, error=bridge.error, events=bridge.events)
            say(f"bridge: {bridge.stats} (error: {bridge.error})")
            bridge.stop()
        for c in (friend, host):
            c.quit()
        subprocess.run(["taskkill", "/F", "/IM", "retroarch.exe"], capture_output=True)
        for c in (host, friend):
            log = c.dir / "logs" / "retroarch.log"
            if log.exists():
                (OUT / f"{c.name}-retroarch.log").write_bytes(log.read_bytes())
        (OUT / f"{name}-samples.csv").write_text(
            "seconds,host_frame,friend_frame\n" + "".join(f"{s},{a},{b}\n" for s, a, b in samples))
        time.sleep(2)


def rejoin(name, rom, host, friend, pad_b, connect_args, times, max_gap):
    out = []
    for i in range(times):
        old_log = friend.log_text()
        friend.quit()
        (OUT / f"{friend.name}-before-rejoin-{i + 1}-retroarch.log").write_text(old_log, encoding="utf-8")
        time.sleep(3)
        t = time.time()
        friend.start(rom, connect_args)

        def joined():
            h, f = host.ram(0, 3), friend.ram(0, 3)
            return h and f and frame_of(f) > 60 and abs(frame_of(h) - frame_of(f)) < max_gap
        ok = bool(wait_until(joined, 45))
        took = round(time.time() - t, 1)
        player2 = False
        if ok:
            time.sleep(2)
            set_pad(pad_b, [B.XUSB_GAMEPAD_A])
            time.sleep(0.5)
            h, f = host.ram(0x10, 2), friend.ram(0x10, 2)
            set_pad(pad_b, [])
            player2 = bool(h and f and tuple(h) == (0, 0x40) and tuple(f) == (0, 0x40))
        out.append({"joined": ok, "seconds": took, "friend_is_player_2": player2})
        say(f"  rejoin {i + 1}: joined {ok} after {took} s, friend still player 2: {player2}")
        if not ok or not player2:
            fail(f"{name}: rejoin {i + 1} failed (joined {ok}, player 2 {player2})")
    return out


def keep_changes(store, ram, changes_ram, settled):
    """Adds the change list's entries to store (change number -> (full frame, P1, P2)), for frames up to
    `settled` only (newer ones can still be redone by netplay). Skips the 16 oldest slots, which a change
    made between the two reads could have overwritten."""
    total = ram[8] | ram[9] << 8
    for full, k, p1, p2 in changes_in_order(ram, changes_ram, total, numbered=True):
        if full <= settled and k >= total - 240:
            store[k] = (full, p1, p2)


def explain_strays(entries, stray_1, stray_2, samples, first, timeline, result):
    """For each unexpected button state, show when it happened and what each pad was doing then."""
    notes = []
    for player, strays in ((1, stray_1), (2, stray_2)):
        for state in strays:
            for f, p1, p2 in entries:
                if (p1 if player == 1 else p2) != state:
                    continue
                # frame -> seconds, from the readings (host frame against time)
                near = min(samples, key=lambda x: abs(x[1] - f))
                at = near[0] - (near[1] - f) / 60.0
                around = [(round(t - first[0] - at, 3), k, st) for t, k, st in timeline if abs(t - first[0] - at) < 0.5]
                note = {"player": player, "state": state, "frame": f, "about_s": round(at, 2), "pads_around (seconds from it, pad, state)": around}
                notes.append(note)
                say(f"  unexpected player {player} state {state:#04x} at frame {f} (~{at:.2f} s): pads around then {around}")
    result["unexpected_states"] = notes[:20]


def changes_in_order(ram, changes_ram, total, numbered=False):
    """The button-change list as (full frame, P1, P2), oldest first."""
    now = frame_of(ram)
    n = min(total, 256)
    out = []
    for k in range(total - n, total):
        e = changes_ram[(k & 0xFF) * 4:(k & 0xFF) * 4 + 4]
        f16 = e[0] | e[1] << 8
        full = (now & ~0xFFFF) | f16
        if full > now:
            full -= 0x10000
        out.append((full, k, e[2], e[3]) if numbered else (full, e[2], e[3]))
    return out


def fingerprint_chain(ram, entries):
    """Recompute the cartridge's fingerprint for the last 255 frames from the change list and compare."""
    now = frame_of(ram)
    if not entries:
        return False, 0
    first = max(now - 254, entries[0][0])
    if first > now:
        return False, 0
    ok = True
    for fr in range(first, now + 1):
        p1 = p2 = 0
        for ef, a, b in entries:
            if ef <= fr:
                p1, p2 = a, b
        want = cart.fingerprint(ram[0x300 + ((fr - 1) & 0xFF)], fr, p1, p2)
        if ram[0x300 + (fr & 0xFF)] != want:
            ok = False
            break
    return ok, now - first + 1


SOLO_FPS = 60.0


def solo_speed(rom, slot_a, slot_b):
    """The yardstick for speed: the same two copies with the same settings, side by side on this machine
    but NOT connected, so the only difference from the real rounds is netplay itself."""
    pair = [Copy("solo-1", 55357, slot_a), Copy("solo-2", 55358, slot_b)]
    try:
        for i, c in enumerate(pair):
            c.write_config(i * 520)
            c.start(rom, [])
        if not wait_until(lambda: all(c.ram(0, 3) for c in pair), 40):
            fail("the two unconnected copies never answered")
            return 60.0
        time.sleep(3)
        t0, f0 = time.time(), [frame_of(c.ram(0, 3)) for c in pair]
        time.sleep(30)
        t1, f1 = time.time(), [frame_of(c.ram(0, 3)) for c in pair]
        fps = [(b - a) / (t1 - t0) for a, b in zip(f0, f1)]
        say(f"two copies side by side, not connected: {fps[0]:.2f} and {fps[1]:.2f} frames a second over {t1 - t0:.1f} s")
        return min(fps)
    finally:
        for c in pair:
            c.quit()
        subprocess.run(["taskkill", "/F", "/IM", "retroarch.exe"], capture_output=True)
        time.sleep(2)


def main():
    global SOLO_FPS
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    rom = WORK / "netplay-test.nes"
    rom.write_bytes(cart.rom())
    say(f"RetroArch: {EXE} ({EXE.stat().st_size} bytes); core {CORE.name}")
    say("plugging in two pretend Xbox pads: A for the host (player 1), B for the friend (player 2)")
    pad_a, slot_a = plug("A")
    pad_b, slot_b = plug("B")
    if slot_a is None or slot_b is None or slot_a == slot_b:
        say("  couldn't read the Xbox slots; assuming A = 0, B = 1")
        slot_a, slot_b = 0, 1
    SOLO_FPS = solo_speed(rom, slot_a, slot_b)
    plan = [
        ("direct", {}),
        ("delayed", {"delay": (50, 20)}),
        ("relay-listed-nyc", {"place": "nyc", "listed": True}),
        ("relay-private-nyc", {"place": "nyc", "reconnects": 5}),
        ("relay-private-madrid", {"place": "madrid", "mash_seconds": SHORT_MASH_SECONDS}),
        ("relay-private-saopaulo", {"place": "saopaulo", "mash_seconds": SHORT_MASH_SECONDS}),
        ("relay-private-singapore", {"place": "singapore", "mash_seconds": SHORT_MASH_SECONDS}),
        # Longer play through the nearest relay, both ways, to see whether connections drop (run 41169114880
        # dropped one at ~60 s): if both drop, it's the relay or the internet; if only the private one, the bridge.
        ("relay-listed-nyc-long", {"place": "nyc", "listed": True, "mash_seconds": LONG_MASH_SECONDS}),
        ("relay-private-nyc-long", {"place": "nyc", "mash_seconds": LONG_MASH_SECONDS}),
    ]
    rounds = []
    for name, opts in plan:
        if ONLY_ROUNDS and name not in ONLY_ROUNDS:
            continue
        try:
            rounds.append(run_round(name, rom, pad_a, slot_a, pad_b, slot_b, **opts))
        except Exception as e:  # noqa: BLE001 - one broken round shouldn't hide the others' numbers
            where = traceback.format_exc()
            say(where)
            fail(f"{name}: the round stopped with {type(e).__name__}: {e}")
            rounds.append({"round": name, "ok": False, "error": f"{type(e).__name__}: {e}", "where": where})
    summary = {"ok": not failures, "two_unconnected_copies_fps": round(SOLO_FPS, 2), "failures": failures, "rounds": rounds, "mash_seconds": MASH_SECONDS}
    (OUT / "results.json").write_text(json.dumps(summary, indent=2))
    say("\n================ summary ================")
    say(json.dumps(summary, indent=2))
    if failures:
        for f in failures:
            print(f"::error::netplay test: {f}", flush=True)
        sys.exit(1)
    say("\nevery round: connected, every button on the right player, and the two games never went apart")


if __name__ == "__main__":
    main()
