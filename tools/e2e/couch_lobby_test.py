#!/usr/bin/env python3
"""CI only (GitHub's Windows machine): can the approved Couch Play lobby work? Measures three things before
any app building (design boards CQ4 and CQ6, approved 2026-10-31):

  1. "box":   the game's own window (RetroArch) sitting inside a box on a lobby screen, and switching between
              that box and full screen and back, while the game keeps running.
  2. "couch": 4 players on SNES (multitap) plus 4 watchers, 8 copies of RetroArch, staying in sync, on this
              machine and through libretro's relay the private way (nothing listed publicly).
  3. same rounds: switching between playing and watching mid-game, and dropping out and rejoining, without
              the game pausing for everyone else.

    python couch_lobby_test.py <player folder> <work folder> <results folder>

<player folder> is what tools/player/fetch_player.py builds. Nothing is installed or changed outside
<work folder> and <results folder>. Only the relay round goes to the internet (libretro's lobby, to find the
relay, and the relay itself). COUCH_PARTS picks parts ("box", "couch-direct", "couch-relay-nyc"); all by default.

How the game is read: the SNES test cartridge (make_snes_multitap_rom.py) keeps a frame number, a per-frame
fingerprint, all five pads and a button-change list in its RAM. snes9x doesn't publish its RAM to RetroArch's
READ_CORE_MEMORY command, so the test finds the RAM inside each RetroArch process by a marker the cartridge
writes at start-up, and reads it with ReadProcessMemory (read only, our own test processes only).

The lobby here is a plain stand-in window (Python's tkinter), not Game Night's app: it has a magenta box where
the game should appear, so a screenshot shows whether the game really covers the box.
"""
import asyncio
import ctypes
import ctypes.wintypes as wt
import json
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

sys.path.insert(0, str(Path(__file__).parent))
import make_snes_multitap_rom as cart  # noqa: E402
import netplay_test as np  # noqa: E402  (relay bridge, lobby helpers, pretend pads; same command line)

PLAYER, WORK, OUT = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
EXE = PLAYER / "retroarch.exe"
CORE = PLAYER / "cores" / "snes9x_libretro.dll"
NETPLAY_PORT = 55435
MASH_SECONDS = int(os.environ.get("COUCH_MASH_SECONDS", "90"))
SHORT_MASH = 30
ONLY = [p for p in os.environ.get("COUCH_PARTS", "").replace(",", " ").split() if p]
MARGIN = 60  # only compare frames at least this many frames old in every copy (newer ones may still be redone)
B = vg.XUSB_BUTTON
# Xbox button -> SNES button as a 16-bit pad value (first byte << 8 | second byte, see the cartridge).
# RetroArch's standard layout: Xbox A is the SNES B spot (bottom), X is Y, B is A, Y is X.
SNES = [
    ("A", B.XUSB_GAMEPAD_A, 0x8000), ("X", B.XUSB_GAMEPAD_X, 0x4000),
    ("View", B.XUSB_GAMEPAD_BACK, 0x2000), ("Menu", B.XUSB_GAMEPAD_START, 0x1000),
    ("Up", B.XUSB_GAMEPAD_DPAD_UP, 0x0800), ("Down", B.XUSB_GAMEPAD_DPAD_DOWN, 0x0400),
    ("Left", B.XUSB_GAMEPAD_DPAD_LEFT, 0x0200), ("Right", B.XUSB_GAMEPAD_DPAD_RIGHT, 0x0100),
    ("B", B.XUSB_GAMEPAD_B, 0x0080), ("Y", B.XUSB_GAMEPAD_Y, 0x0040),
    ("LB", B.XUSB_GAMEPAD_LEFT_SHOULDER, 0x0020), ("RB", B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0x0010),
]
OPPOSITE = [(0x0800, 0x0400), (0x0200, 0x0100)]

failures = []
findings = {}


def say(m=""):
    print(m, flush=True)


def fail(m):
    failures.append(m)
    say(f"  FAIL: {m}")


def set_pad(pad, buttons):
    pad.reset()
    for button in buttons:
        pad.press_button(button=button)
    pad.update()


# ---------------------------------------------------------------- Windows: reading our own test processes

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_ulonglong), ("AllocationBase", ctypes.c_ulonglong),
                ("AllocationProtect", wt.DWORD), ("_a1", wt.DWORD), ("RegionSize", ctypes.c_ulonglong),
                ("State", wt.DWORD), ("Protect", wt.DWORD), ("Type", wt.DWORD), ("_a2", wt.DWORD)]


k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenProcess.restype = wt.HANDLE
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype = wt.BOOL
k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
k32.VirtualQueryEx.restype = ctypes.c_size_t
k32.CloseHandle.argtypes = [wt.HANDLE]
WRITABLE = 0x04 | 0x08 | 0x40 | 0x80  # read-write, write-copy, and the executable versions


class ProcMem:
    """Read-only view of one of our RetroArch copies' memory."""

    def __init__(self, pid):
        self.h = k32.OpenProcess(0x0410, False, pid)  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
        if not self.h:
            raise OSError(f"OpenProcess failed: {ctypes.get_last_error()}")

    def read(self, address, n):
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t(0)
        if k32.ReadProcessMemory(self.h, ctypes.c_void_p(address), buf, n, ctypes.byref(got)) and got.value == n:
            return buf.raw
        return None

    def find_all(self, needle):
        found, address, mbi = [], 0, MBI()
        while k32.VirtualQueryEx(self.h, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            base, size = mbi.BaseAddress, mbi.RegionSize
            # committed, writable, not a guard page, and the process's own memory or a loaded DLL's
            # (skips mapped graphics memory, which can be huge)
            if mbi.State == 0x1000 and mbi.Protect & WRITABLE and not mbi.Protect & 0x100 \
                    and mbi.Type in (0x20000, 0x1000000) and size < (1 << 31):
                data = self.read(base, size)
                if data:
                    at = data.find(needle)
                    while at >= 0:
                        found.append(base + at)
                        at = data.find(needle, at + 1)
            address = base + size
            if address >= (1 << 47):
                break
        return found

    def close(self):
        if self.h:
            k32.CloseHandle(self.h)
            self.h = None


# ---------------------------------------------------------------- Windows: windows

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
u32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
u32.IsWindowVisible.argtypes = [wt.HWND]
u32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
u32.SetParent.argtypes = [wt.HWND, wt.HWND]
u32.SetParent.restype = wt.HWND
u32.GetParent.argtypes = [wt.HWND]
u32.GetParent.restype = wt.HWND
u32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
u32.GetAncestor.restype = wt.HWND
u32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
u32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
u32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
u32.SetForegroundWindow.argtypes = [wt.HWND]
u32.GetForegroundWindow.restype = wt.HWND
u32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
u32.IsWindow.argtypes = [wt.HWND]
try:
    u32.SetProcessDPIAware()
except OSError:
    pass

GWL_STYLE, GWLP_HWNDPARENT = -16, -8
WS_CHILD, WS_POPUP, WS_VISIBLE, WS_CLIPSIBLINGS = 0x40000000, 0x80000000, 0x10000000, 0x04000000
WS_DECOR = 0x00C00000 | 0x00040000 | 0x00020000 | 0x00010000 | 0x00080000  # caption, frame, min, max, menu
SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED, SWP_SHOWWINDOW = 0x4, 0x10, 0x20, 0x40
HWND_TOP, HWND_TOPMOST, HWND_NOTOPMOST = 0, (1 << 64) - 1, (1 << 64) - 2  # (HWND)-1 and (HWND)-2


def windows_of(pid):
    out = []

    def cb(hwnd, _):
        p = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(hwnd):
            out.append(hwnd)
        return True
    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def class_name(hwnd):
    buf = ctypes.create_unicode_buffer(128)
    u32.GetClassNameW(hwnd, buf, 128)
    return buf.value


def window_rect(hwnd):
    r = wt.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def client_screen_rect(hwnd):
    r, p = wt.RECT(), wt.POINT(0, 0)
    u32.GetClientRect(hwnd, ctypes.byref(r))
    u32.ClientToScreen(hwnd, ctypes.byref(p))
    return (p.x, p.y, r.right, r.bottom)


def screen_size():
    return u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)


def grab():
    from PIL import ImageGrab
    return ImageGrab.grab()


# ---------------------------------------------------------------- one copy of RetroArch with the SNES cartridge

class SnesCopy:
    def __init__(self, name, cmd_port, pad_slot, x=0, y=40, scale=1):
        self.name, self.cmd_port, self.pad_slot = name, cmd_port, pad_slot
        self.x, self.y, self.scale = x, y, scale
        self.dir = WORK / name
        self.proc = self.mem = None
        self.base = None
        self.sent_log_lines = 0

    def write_config(self, extra=None):
        for d in ("logs", "saves", "states", "system", "cache"):
            (self.dir / d).mkdir(parents=True, exist_ok=True)
        p = lambda q: str(q).replace('"', "")  # noqa: E731
        settings = {
            # Same "no extras" basics as Game Night's own settings (app/src-tauri/src/games.rs) and netplay_test.py.
            "config_save_on_exit": "false", "menu_driver": "rgui", "input_menu_toggle": "nul",
            "input_menu_toggle_gamepad_combo": "0", "input_quit_gamepad_combo": "0", "input_desktop_menu_toggle": "nul",
            "ui_companion_enable": "false", "ui_companion_start_on_boot": "false", "desktop_menu_enable": "false",
            "menu_show_online_updater": "false", "menu_show_core_updater": "false", "stdin_cmd_enable": "false",
            "cheevos_enable": "false", "discord_allow": "false", "history_list_enable": "false",
            "game_specific_options": "false", "auto_overrides_enable": "false", "auto_remaps_enable": "false",
            "auto_shaders_enable": "false", "savestate_auto_load": "false", "savestate_auto_save": "false",
            "rewind_enable": "false", "input_hold_fast_forward": "nul", "input_toggle_fast_forward": "nul",
            "input_exit_emulator": "nul",
            # The test sends commands (switch play/watch, full screen) through this (this machine only).
            "network_cmd_enable": "true", "network_cmd_port": str(self.cmd_port),
            # Netplay: by default this machine only. No public lobby, no NAT punching, no relay servers.
            "netplay_public_announce": "false", "netplay_nat_traversal": "false", "netplay_use_mitm_server": "false",
            "netplay_check_frames": "0", "netplay_nickname": self.name, "netplay_ping_show": "false",
            "netplay_max_connections": "8", "netplay_max_ping": "0",
            "video_driver": "d3d11", "video_fullscreen": "false", "video_windowed_fullscreen": "true",
            "video_scale": str(self.scale), "video_window_save_positions": "true",
            "video_windowed_position_x": str(self.x), "video_windowed_position_y": str(self.y),
            "video_windowed_position_width": str(256 * self.scale), "video_windowed_position_height": str(224 * self.scale),
            "pause_nonactive": "false", "video_font_enable": "true",
            "audio_enable": "false", "video_vsync": "false", "vrr_runloop_enable": "true",
            # Controllers: this copy's player 1 is its own pad only. Port 2 is a multitap (players 2-5).
            "input_joypad_driver": "xinput", "input_autodetect_enable": "true",
            "joypad_autoconfig_dir": p(PLAYER / "autoconfig"), "input_max_users": "5",
            "input_player1_joypad_index": str(self.pad_slot),
            "input_libretro_device_p1": "1", "input_libretro_device_p2": "257",
            "libretro_directory": p(PLAYER / "cores"), "savefile_directory": p(self.dir / "saves"),
            "savestate_directory": p(self.dir / "states"), "system_directory": p(self.dir / "system"),
            "cache_directory": p(self.dir / "cache"),
            "log_to_file": "true", "log_to_file_timestamp": "false", "log_verbosity": "true",
            "frontend_log_level": "0", "libretro_log_level": "2", "log_dir": p(self.dir / "logs"),
        }
        for n in range(2, 6):
            settings[f"input_player{n}_joypad_index"] = "15"
        for n in range(3, 6):
            settings[f"input_libretro_device_p{n}"] = "1"
        for n in range(1, 17):
            settings[f"netplay_request_device_p{n}"] = "false"
        settings.update(extra or {})
        self.cfg = self.dir / "retroarch.cfg"
        self.cfg.write_text("".join(f'{k} = "{v}"\n' for k, v in settings.items()), encoding="ascii")

    def start(self, rom, netplay_args):
        log = self.dir / "logs" / "retroarch.log"
        if log.exists():
            keep = OUT / f"{self.name}-earlier-{int(time.time())}-retroarch.log"
            keep.write_bytes(log.read_bytes())
            log.unlink()
        self.base = None
        if self.mem:
            self.mem.close()
            self.mem = None
        args = [str(EXE), "-c", str(self.cfg), "-L", str(CORE), *netplay_args, str(rom)]
        say(f"starting {self.name}: {' '.join(args[1:])}")
        self.proc = subprocess.Popen(args, cwd=str(PLAYER))
        self.started = time.time()

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def locate(self, seconds=40):
        """Finds the cartridge's RAM inside this copy. Netplay keeps saved copies of the game too (each with
        the marker), so the live one is the one that keeps counting and is furthest along."""
        end = time.time() + seconds
        while time.time() < end and self.alive():
            if not self.mem:
                try:
                    self.mem = ProcMem(self.proc.pid)
                except OSError:
                    time.sleep(0.5)
                    continue
            bases = [a - cart.MARKER_AT for a in self.mem.find_all(cart.MARKER)]
            if not bases:
                time.sleep(0.5)
                continue
            score = {b: 0 for b in bases}
            last = {}
            for _ in range(8):
                frames = {}
                for b in bases:
                    d = self.mem.read(b, 3)
                    if d:
                        frames[b] = frame_of(d)
                if frames:
                    top = max(frames.values())
                    for b, f in frames.items():
                        if f == top:
                            score[b] += 1
                    last = frames
                time.sleep(0.07)
            best = max(bases, key=lambda b: (score[b], last.get(b, -1)))
            first = frame_of(self.mem.read(best, 3) or b"\0\0\0")
            time.sleep(0.2)
            again = frame_of(self.mem.read(best, 3) or b"\0\0\0")
            if again > first:
                self.base = best
                self.candidates = len(bases)
                return True
            time.sleep(0.5)
        return False

    def ram(self, start, length):
        if self.base is None or not self.mem:
            return None
        return self.mem.read(self.base + start, length)

    def frame(self):
        d = self.ram(0, 3)
        return frame_of(d) if d else None

    def send(self, command):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(command.encode(), ("127.0.0.1", self.cmd_port))

    def log_text(self):
        try:
            return (self.dir / "logs" / "retroarch.log").read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return ""

    def netplay_lines(self):
        return [l for l in self.log_text().splitlines() if "[Netplay]" in l]

    def new_netplay_lines(self):
        lines = self.netplay_lines()
        new = lines[self.sent_log_lines:]
        self.sent_log_lines = len(lines)
        return new

    def main_window(self):
        if not self.alive():
            return None
        wins = [w for w in windows_of(self.proc.pid)]
        if not wins:
            return None
        return max(wins, key=lambda w: window_rect(w)[2] * window_rect(w)[3])

    def quit(self):
        if self.alive():
            self.send("QUIT")
            try:
                self.proc.wait(8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.keep_log()

    def kill(self):
        if self.alive():
            self.proc.kill()
            self.proc.wait(10)
        self.keep_log()

    def keep_log(self):
        if self.mem:
            self.mem.close()
            self.mem = None
        self.base = None
        log = self.dir / "logs" / "retroarch.log"
        if log.exists():
            (OUT / f"{self.name}-{int(time.time())}-retroarch.log").write_bytes(log.read_bytes())


def frame_of(mem):
    return mem[0] | mem[1] << 8 | mem[2] << 16


def pad_values(mem):
    """Pads 1-5 as 16-bit values from RAM $10-$19."""
    return [mem[0x10 + 2 * i] << 8 | mem[0x11 + 2 * i] for i in range(5)]


class FrameWatch(threading.Thread):
    """Reads one copy's frame number every 10 ms, so we can see whether (and how long) its game stops."""

    def __init__(self, copy):
        super().__init__(daemon=True)
        self.copy, self.points, self.stop = copy, [], threading.Event()

    def run(self):
        while not self.stop.is_set():
            f = self.copy.frame()
            if f is not None:
                self.points.append((time.perf_counter(), f))
            time.sleep(0.01)

    def longest_stop_ms(self, t0, t1):
        """Longest time the frame number didn't move, within [t0, t1] (perf_counter seconds)."""
        pts = [p for p in self.points if t0 <= p[0] <= t1]
        if len(pts) < 2:
            return None
        longest, since, last = 0.0, pts[0][0], pts[0][1]
        for t, f in pts[1:]:
            if f != last:
                longest = max(longest, t - since)
                since, last = t, f
        longest = max(longest, pts[-1][0] - since)
        return round(longest * 1000)

    def fps(self, t0, t1):
        pts = [p for p in self.points if t0 <= p[0] <= t1]
        if len(pts) < 2 or pts[-1][0] == pts[0][0]:
            return None
        return round((pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0]), 1)


# ---------------------------------------------------------------- part 1: the game in a box on the lobby screen

class Lobby:
    """A stand-in lobby screen in its own process (lobby_standin.py): a dark window with a magenta box where the
    live game should show."""
    BG, BOX = (0x1A, 0x0F, 0x2E), (0xFF, 0x00, 0xFF)

    def start(self):
        self.proc = subprocess.Popen([sys.executable, str(Path(__file__).parent / "lobby_standin.py")],
                                     stdout=subprocess.PIPE, text=True)
        line = self.proc.stdout.readline().split()
        if len(line) != 3 or line[0] != "READY":
            raise RuntimeError(f"the stand-in lobby didn't start: {line}")
        self.box_hwnd, self.top_hwnd = int(line[1]), int(line[2])

    def box_rect(self):
        return client_screen_rect(self.box_hwnd)

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()


def box_picture(rect, shot=None):
    """How much of the box shows the lobby's magenta (game not covering it) in a screenshot."""
    shot = shot or grab()
    x, y, w, h = rect
    crop = shot.crop((x, y, x + w, y + h)).convert("RGB")
    px = list(crop.getdata())
    magenta = sum(1 for p in px if p[0] > 220 and p[1] < 40 and p[2] > 220)
    return {"magenta_share": round(magenta / max(1, len(px)), 3)}, crop


def live_in(rect):
    """Two screenshots 0.3 s apart: share of the box's pixels that changed (the game's colour changes every
    frame, the lobby never changes)."""
    s1 = grab()
    time.sleep(0.3)
    s2 = grab()
    x, y, w, h = rect
    a = list(s1.crop((x, y, x + w, y + h)).convert("RGB").getdata())
    b = list(s2.crop((x, y, x + w, y + h)).convert("RGB").getdata())
    changed = sum(1 for p, q in zip(a, b) if p != q)
    pic, _ = box_picture(rect, s2)
    return dict(pic, changed_share=round(changed / max(1, len(a)), 3)), s2


def lobby_share(shot):
    """Share of the whole screen showing the lobby (its dark colour or magenta box)."""
    px = list(shot.convert("RGB").resize((shot.width // 4, shot.height // 4)).getdata())
    lob = sum(1 for p in px if (abs(p[0] - Lobby.BG[0]) < 6 and abs(p[1] - Lobby.BG[1]) < 6 and abs(p[2] - Lobby.BG[2]) < 6)
              or (p[0] > 220 and p[1] < 40 and p[2] > 220))
    return round(lob / max(1, len(px)), 3)


def near(a, b, slack=3):
    return a is not None and b is not None and all(abs(p - q) <= slack for p, q in zip(a, b))


def step(watch, name, action, check, settle=1.5, timeout=6.0):
    """Runs one window change and measures it: how long until `check()` passes, and whether the game stopped."""
    t0 = time.perf_counter()
    note = action()
    took = None
    end = t0 + timeout
    while time.perf_counter() < end:
        if check():
            took = round((time.perf_counter() - t0) * 1000)
            break
        time.sleep(0.02)
    time.sleep(settle)
    t1 = time.perf_counter()
    out = {"step": name, "reached_ms": took, "game_longest_stop_ms": watch.longest_stop_ms(t0, t1),
           "game_fps_during": watch.fps(t0, t1)}
    if note:
        out["note"] = note
    say(f"  {name}: reached after {took} ms; the game's longest stop {out['game_longest_stop_ms']} ms, "
        f"{out['game_fps_during']} frames a second during the change")
    return out


def pad_reaches_game(copy, pad, lobby):
    """With the lobby window in front (as it would be in the app), does the pad still reach the game?"""
    u32.SetForegroundWindow(lobby.top_hwnd)
    time.sleep(0.4)
    front = u32.GetForegroundWindow()
    set_pad(pad, [B.XUSB_GAMEPAD_A])
    time.sleep(0.4)
    m = copy.ram(0x10, 2)
    set_pad(pad, [])
    return {"lobby_in_front": front == lobby.top_hwnd, "front_window_class": class_name(front) if front else None,
            "game_saw_the_press": bool(m and m[0] & 0x80)}


def part_box(rom, pad_a, slot_a):
    say("\n################ part 1: the game in a box on the lobby screen ################")
    res = {"part": "box", "screen": screen_size()}
    copy = SnesCopy("box", 55390, slot_a, x=60, y=60, scale=2)
    copy.write_config()
    lobby = Lobby()
    lobby.start()
    watch = None
    try:
        copy.start(rom, [])
        if not copy.locate(40):
            fail("box: couldn't find the game's RAM in RetroArch")
            return res
        say(f"found the game's RAM ({copy.candidates} marked copies in the process)")
        hwnd = wait_for(lambda: copy.main_window(), 15)
        if not hwnd:
            fail("box: RetroArch's window never showed")
            return res
        watch = FrameWatch(copy)
        watch.start()
        orig, win = hwnd, {"h": hwnd}

        def H():
            # RetroArch's own full screen switch throws its window away and makes a new one (run 41178739169),
            # so always work on whichever window it has now
            if not u32.IsWindow(win["h"]):
                win["h"] = copy.main_window() or win["h"]
            return win["h"]
        style0 = u32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        res["retroarch_window"] = {"class": class_name(hwnd), "rect": window_rect(hwnd), "style": hex(style0 & 0xFFFFFFFF)}
        say(f"RetroArch window {class_name(hwnd)} at {window_rect(hwnd)}; lobby box at {lobby.box_rect()}")
        time.sleep(1)
        grab().save(OUT / "box-0-start.png")
        sw, sh = screen_size()
        full = (0, 0, sw, sh)

        # ---- way A: RetroArch's window becomes a child window inside the lobby's box
        say("\nway A: RetroArch's window becomes a child of the lobby's box (SetParent)")
        a = res["child_window"] = {"steps": []}

        def embed():
            st = (u32.GetWindowLongPtrW(H(), GWL_STYLE) & ~(WS_POPUP | WS_DECOR)) | WS_CHILD | WS_VISIBLE
            u32.SetWindowLongPtrW(H(), GWL_STYLE, st)
            u32.SetParent(H(), lobby.box_hwnd)
            bw, bh = lobby.box_rect()[2:]
            u32.SetWindowPos(H(), HWND_TOP, 0, 0, bw, bh, SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOACTIVATE)

        a["steps"].append(step(watch, "into the box", embed, lambda: near(window_rect(H()), lobby.box_rect())))
        a["rect_after"], a["box"] = window_rect(H()), lobby.box_rect()
        a["in_box"] = near(a["rect_after"], a["box"])
        a["picture_in_box"], shot = live_in(lobby.box_rect())
        shot.save(OUT / "box-A1-child-in-box.png")
        a["pad_with_lobby_in_front"] = pad_reaches_game(copy, pad_a, lobby)
        say(f"  in the box: {a['in_box']}; picture {a['picture_in_box']}; pad: {a['pad_with_lobby_in_front']}")

        # RetroArch's own full screen switch, while it is a child window
        before = set(windows_of(copy.proc.pid))
        a["steps"].append(step(watch, "RetroArch's own full screen switch (child)", lambda: copy.send("FULLSCREEN_TOGGLE"),
                               lambda: near(window_rect(copy.main_window() or H()), full), settle=2.5))
        w_now = copy.main_window() or (win['h'] if u32.IsWindow(win['h']) else None)
        a["retroarch_fullscreen"] = {
            "same_window": w_now == orig, "windows_before": len(before), "windows_after": len(windows_of(copy.proc.pid)),
            "rect": window_rect(w_now) if w_now else None, "still_child_of_box": bool(w_now and u32.GetParent(w_now) == lobby.box_hwnd),
            "lobby_share_of_screen": lobby_share(grab())}
        grab().save(OUT / "box-A2-child-retroarch-fullscreen.png")
        a["steps"].append(step(watch, "RetroArch's own switch back (child)", lambda: copy.send("FULLSCREEN_TOGGLE"),
                               lambda: near(window_rect(copy.main_window() or H()), lobby.box_rect()), settle=2.5))
        w_now = copy.main_window() or (win['h'] if u32.IsWindow(win['h']) else None) or H()
        a["retroarch_back"] = {"same_window": w_now == orig, "rect": window_rect(w_now), "box": lobby.box_rect(),
                               "back_in_box": near(window_rect(w_now), lobby.box_rect())}
        a["retroarch_back"]["picture_in_box"], shot = live_in(lobby.box_rect())
        shot.save(OUT / "box-A3-child-after-retroarch-switch.png")
        say(f"  RetroArch's own switch: {a['retroarch_fullscreen']}; back: {a['retroarch_back']}")
        if not a["retroarch_back"]["back_in_box"] and u32.IsWindow(win['h']):
            embed()
            time.sleep(1)

        # Our own full screen: take it out of the box, cover the screen; then put it back
        def ours_full():
            u32.SetParent(H(), None)
            st = (u32.GetWindowLongPtrW(H(), GWL_STYLE) & ~(WS_CHILD | WS_DECOR)) | WS_POPUP | WS_VISIBLE
            u32.SetWindowLongPtrW(H(), GWL_STYLE, st)
            u32.SetWindowPos(H(), HWND_TOPMOST, 0, 0, sw, sh, SWP_FRAMECHANGED | SWP_SHOWWINDOW)
        a["steps"].append(step(watch, "our full screen (out of the box, cover the screen)", ours_full,
                               lambda: near(window_rect(H()), full)))
        shot = grab()
        shot.save(OUT / "box-A4-child-our-fullscreen.png")
        a["our_fullscreen"] = {"rect": window_rect(H()), "covers_screen": near(window_rect(H()), full), "lobby_share_of_screen": lobby_share(shot)}

        def ours_back():
            u32.SetWindowPos(H(), HWND_NOTOPMOST, 0, 0, 0, 0, 0x1 | 0x2 | SWP_NOACTIVATE)
            embed()
        a["steps"].append(step(watch, "our way back into the box", ours_back, lambda: near(window_rect(H()), lobby.box_rect())))
        a["our_back"] = {"rect": window_rect(H()), "back_in_box": near(window_rect(H()), lobby.box_rect())}
        a["our_back"]["picture_in_box"], shot = live_in(lobby.box_rect())
        shot.save(OUT / "box-A5-child-back-in-box.png")
        say(f"  our full screen: {a['our_fullscreen']}; back: {a['our_back']}")

        # Back to a normal window before way B
        u32.SetParent(H(), None)
        u32.SetWindowLongPtrW(H(), GWL_STYLE, style0)
        u32.SetWindowPos(H(), HWND_TOP, 60, 60, 600, 500, SWP_FRAMECHANGED | SWP_SHOWWINDOW)
        time.sleep(1.5)

        # ---- way B: RetroArch stays its own window, without borders, kept exactly over the box and owned by the
        # lobby window (so it stays above it and minimises with it); the app moves it when the lobby moves
        say("\nway B: RetroArch stays its own borderless window, placed over the box and owned by the lobby")
        bres = res["owned_window"] = {"steps": []}

        def place_over_box():
            st = (u32.GetWindowLongPtrW(H(), GWL_STYLE) & ~(WS_CHILD | WS_DECOR)) | WS_POPUP | WS_VISIBLE
            u32.SetWindowLongPtrW(H(), GWL_STYLE, st)
            u32.SetWindowLongPtrW(H(), GWLP_HWNDPARENT, lobby.top_hwnd)
            x, y, w, h = lobby.box_rect()
            u32.SetWindowPos(H(), HWND_TOP, x, y, w, h, SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOACTIVATE)

        bres["steps"].append(step(watch, "over the box", place_over_box, lambda: near(window_rect(H()), lobby.box_rect())))
        bres["in_box"] = near(window_rect(H()), lobby.box_rect())
        bres["picture_in_box"], shot = live_in(lobby.box_rect())
        shot.save(OUT / "box-B1-owned-over-box.png")
        bres["pad_with_lobby_in_front"] = pad_reaches_game(copy, pad_a, lobby)
        bres["still_over_box_with_lobby_in_front"] = near(window_rect(H()), lobby.box_rect())
        bres["picture_with_lobby_in_front"], shot = live_in(lobby.box_rect())
        shot.save(OUT / "box-B2-owned-lobby-in-front.png")
        say(f"  over the box: {bres['in_box']}; picture {bres['picture_in_box']}; pad: {bres['pad_with_lobby_in_front']}; "
            f"with the lobby in front: {bres['picture_with_lobby_in_front']}")

        # The lobby window moves: the app follows with the game window
        def move_lobby():
            u32.SetWindowPos(lobby.top_hwnd, 0, 60, 40, 0, 0, 0x1 | SWP_NOZORDER | SWP_NOACTIVATE)
            time.sleep(0.2)
            x, y, w, h = lobby.box_rect()
            u32.SetWindowPos(H(), 0, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE)
        bres["steps"].append(step(watch, "lobby moved, game window follows", move_lobby, lambda: near(window_rect(H()), lobby.box_rect())))

        def full_b():
            u32.SetWindowPos(H(), HWND_TOPMOST, 0, 0, sw, sh, SWP_SHOWWINDOW)
        bres["steps"].append(step(watch, "our full screen (cover the screen)", full_b, lambda: near(window_rect(H()), full)))
        shot = grab()
        shot.save(OUT / "box-B3-owned-our-fullscreen.png")
        bres["our_fullscreen"] = {"rect": window_rect(H()), "covers_screen": near(window_rect(H()), full), "lobby_share_of_screen": lobby_share(shot)}

        def back_b():
            x, y, w, h = lobby.box_rect()
            u32.SetWindowPos(H(), HWND_NOTOPMOST, x, y, w, h, SWP_SHOWWINDOW | SWP_NOACTIVATE)
        bres["steps"].append(step(watch, "our way back over the box", back_b, lambda: near(window_rect(H()), lobby.box_rect())))
        bres["our_back"] = {"rect": window_rect(H()), "back_in_box": near(window_rect(H()), lobby.box_rect())}
        bres["our_back"]["picture_in_box"], shot = live_in(lobby.box_rect())
        shot.save(OUT / "box-B4-owned-back-over-box.png")
        say(f"  our full screen: {bres['our_fullscreen']}; back: {bres['our_back']}")

        orig = H()
        before = set(windows_of(copy.proc.pid))
        bres["steps"].append(step(watch, "RetroArch's own full screen switch (owned)", lambda: copy.send("FULLSCREEN_TOGGLE"),
                                  lambda: near(window_rect(copy.main_window() or H()), full), settle=2.5))
        w_now = copy.main_window()
        bres["retroarch_fullscreen"] = {"same_window": w_now == orig, "windows_before": len(before),
                                        "rect": window_rect(w_now) if w_now else None, "lobby_share_of_screen": lobby_share(grab())}
        grab().save(OUT / "box-B5-owned-retroarch-fullscreen.png")
        bres["steps"].append(step(watch, "RetroArch's own switch back (owned)", lambda: copy.send("FULLSCREEN_TOGGLE"),
                                  lambda: near(window_rect(copy.main_window() or H()), lobby.box_rect()), settle=2.5))
        w_now = copy.main_window() or H()
        bres["retroarch_back"] = {"same_window": w_now == orig, "rect": window_rect(w_now), "box": lobby.box_rect(),
                                  "back_in_box": near(window_rect(w_now), lobby.box_rect())}
        grab().save(OUT / "box-B6-owned-after-retroarch-switch.png")
        say(f"  RetroArch's own switch: {bres['retroarch_fullscreen']}; back: {bres['retroarch_back']}")

        # The headline numbers (the test's claims). Way-specific RetroArch switch results are findings, not failures.
        for way, r in (("child_window", a), ("owned_window", bres)):
            ok = r.get("in_box") and r["picture_in_box"]["magenta_share"] < 0.02 and r["picture_in_box"]["changed_share"] > 0.3 \
                and r["our_fullscreen"]["covers_screen"] and r["our_back"]["back_in_box"]
            stops = [s["game_longest_stop_ms"] for s in r["steps"] if s["game_longest_stop_ms"] is not None]
            r["works"] = bool(ok)
            r["longest_game_stop_ms_any_step"] = max(stops) if stops else None
        res["works_any_way"] = a["works"] or bres["works"]
        if not res["works_any_way"]:
            fail("box: neither way put a live game in the box and switched to full screen and back")
        return res
    finally:
        if watch:
            watch.stop.set()
        copy.quit()
        lobby.close()
        subprocess.run(["taskkill", "/F", "/IM", "retroarch.exe"], capture_output=True)
        time.sleep(2)


def wait_for(check, seconds, step_s=0.25):
    end = time.time() + seconds
    while time.time() < end:
        r = check()
        if r:
            return r
        time.sleep(step_s)
    return None


# ---------------------------------------------------------------- part 2 and 3: 4 players + 4 watchers

class CutProxy:
    """For the on-this-machine round: each friend connects through their own small pass-through on this
    machine, which can go silent (like their internet dying) without closing the connection."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.frozen_ports, self.conns = set(), {}
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def add(self, port):
        fut = asyncio.run_coroutine_threadsafe(asyncio.start_server(lambda r, w: self.handle(port, r, w), "127.0.0.1", port), self.loop)
        fut.result(10)

    async def handle(self, port, reader, writer):
        rec = {"frozen": False}
        self.conns.setdefault(port, []).append(rec)
        up_r, up_w = await asyncio.open_connection("127.0.0.1", NETPLAY_PORT)
        await asyncio.gather(self.pipe(reader, up_w, rec), self.pipe(up_r, writer, rec), return_exceptions=True)

    async def pipe(self, reader, writer, rec):
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                while rec["frozen"]:
                    await asyncio.sleep(0.05)
                writer.write(data)
                await writer.drain()
        finally:
            if not rec["frozen"]:
                writer.close()

    def freeze(self, port):
        for rec in self.conns.get(port, []):
            rec["frozen"] = True


class FreezableBridge(np.TunnelBridge):
    """The private relay bridge from netplay_test.py, plus a way to make one friend's link go silent."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.frozen = set()

    async def pipe(self, reader, writer, counter, label):
        n = int(label.split()[1].rstrip(":"))
        how = "closed it (end of data)"
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                while n in self.frozen:
                    await asyncio.sleep(0.05)
                self.stats[counter] += len(data)
                writer.write(data)
                await writer.drain()
        except Exception as e:  # noqa: BLE001
            how = f"broke: {type(e).__name__}: {e}"
        finally:
            self.note(f"{label} {how}")
            if n not in self.frozen:
                writer.close()


class Couch:
    """One round: host + 3 players + 4 watchers."""

    def __init__(self, name, rom, pads, slots, place=None):
        self.name, self.rom, self.place = name, rom, place
        self.pads, self.slots = pads, slots  # seat 1-4 -> pretend pad / its Xbox slot
        self.res = {"round": name, "joins": [], "events": []}
        self.copies, self.live = {}, []
        self.proxy = self.bridge = None
        self.link_of = {}
        self.port_of = {}
        self.watch = None

    # --- people
    def person(self, name, i, pad_slot, extra):
        c = SnesCopy(f"{self.name}-{name}", 55400 + i, pad_slot, x=(i % 4) * 250, y=30 + (i // 4) * 280)
        c.extra = extra
        c.write_config(extra)
        self.copies[name] = c
        return c

    def connect_args(self, c):
        if self.bridge:
            return ["--connect", self.relay[0], "--port", str(self.relay[1]), f"--mitm-session={self.bridge.session}"]
        if c.name not in self.port_of:
            self.port_of[c.name] = 55500 + len(self.port_of)
            self.proxy.add(self.port_of[c.name])
        port = self.port_of[c.name]
        return ["--connect", "127.0.0.1", "--port", str(port)]

    def join(self, who, label="join"):
        c = self.copies[who]
        for attempt in range(1, 4):
            ok = self.join_once(who, label, attempt)
            if ok or c.alive() or attempt == 3:
                return ok
            say(f"  {who}'s RetroArch closed by itself (exit code {c.proc.returncode:#x}); trying again")
        return False

    def join_once(self, who, label, attempt):
        c = self.copies[who]
        links_before = self.bridge.stats["links"] if self.bridge else 0
        t0, p0 = time.time(), time.perf_counter()
        c.start(self.rom, self.connect_args(c))
        host = self.copies["P1"]
        ok = c.locate(40)

        def caught_up():
            if not c.alive():
                return None
            if c.base is None:
                c.locate(5)
            fh, fc = host.frame(), c.frame()
            # the host's game arrived: this copy is far past where it could have got on its own, and level with the host
            own_best = 62 * (time.time() - c.started) + 300
            return fh and fc and fc > own_best and abs(fh - fc) < (90 if self.place else 40)
        ok = ok and bool(wait_for(caught_up, 45, 0.2))
        took = round(time.time() - t0, 1)
        time.sleep(1.5)
        # the netplay copy of the RAM may have moved after the host's game arrived; find it again
        c.locate(10)
        p1 = time.perf_counter()
        entry = {"who": who, "what": label, "attempt": attempt, "joined": ok, "seconds": took,
                 "exit_code": None if c.alive() else hex(c.proc.returncode & 0xFFFFFFFF),
                 "host_longest_stop_ms": self.watch.longest_stop_ms(p0, p1) if self.watch else None,
                 "marked_copies_in_process": getattr(c, "candidates", None)}
        if self.bridge:
            self.link_of[who] = self.bridge.stats["links"] if self.bridge.stats["links"] > links_before else None
        entry["log"] = c.new_netplay_lines()[-6:]
        say(f"  {who} {label}: {'ok' if ok else 'FAILED'} after {took} s; host's game longest stop {entry['host_longest_stop_ms']} ms")
        self.res["joins"].append(entry)
        if ok and c not in self.live:
            self.live.append(c)
        if not ok and (c.alive() or attempt == 3):
            fail(f"{self.name}: {who} couldn't {label} (host frame {host.frame()}, theirs {c.frame()}, "
                 f"RetroArch {'running' if c.alive() else 'closed, exit code ' + entry['exit_code']})")
        return ok

    # --- checks
    def seats(self, c):
        m = c.ram(0, 0x20)
        return pad_values(m) if m else None

    def seat_check(self, owners, label):
        """owners: seat number (1-4) -> pretend pad. Holds some buttons on each pad, checks every live copy shows
        them on that seat only."""
        say(f"\nright seat check ({label}): owners {sorted(owners)}")
        wrong = []
        names = ["A", "Menu", "Left", "B", "RB"]
        for seat, pad in sorted(owners.items()):
            for name, button, value in [x for x in SNES if x[0] in names]:
                set_pad(pad, [button])
                time.sleep(0.45)
                seen = {c.name.split("-")[-1]: self.seats(c) for c in self.live}
                set_pad(pad, [])
                want = [0] * 5
                want[seat - 1] = value
                bad = {k: v for k, v in seen.items() if v != want}
                if bad:
                    wrong.append(f"seat {seat} {name}: wanted {[hex(x) for x in want]}, got " + ", ".join(f"{k} {[hex(x) for x in v] if v else None}" for k, v in bad.items()))
                time.sleep(0.25)
            say(f"  seat {seat}: {'ok in all ' + str(len(self.live)) + ' copies' if not [w for w in wrong if w.startswith(f'seat {seat} ')] else 'WRONG'}")
        for w in wrong[:8]:
            say(f"    {w}")
        self.res.setdefault("seat_checks", []).append({"label": label, "copies": len(self.live), "problems": wrong[:20]})
        if wrong:
            fail(f"{self.name}: buttons reached the wrong seat ({label}): {wrong[0]}")
        return not wrong

    def pad_goes_nowhere(self, pad, label):
        set_pad(pad, [B.XUSB_GAMEPAD_A])
        time.sleep(0.5)
        seen = {c.name.split("-")[-1]: self.seats(c) for c in self.live}
        set_pad(pad, [])
        nowhere = all(v == [0] * 5 for v in seen.values() if v)
        say(f"  {label}: pad pressed, shows on no seat in any copy: {nowhere}")
        return nowhere

    def mash_and_compare(self, owners, seconds, label, side_job=None):
        """All owning pads press random buttons; every quarter second compare every finished frame's fingerprint
        across all live copies; at the end compare the button-change histories and check each seat only ever
        showed what its own pad was given."""
        say(f"\nsync check ({label}): {len(owners)} pads press random buttons for {seconds} s; {len(self.live)} copies compared")
        sent = {s: {0} for s in range(1, 6)}
        stop = threading.Event()
        rng = random.Random(sum(label.encode()))

        def mash():
            end = time.time() + seconds
            while time.time() < end and not stop.is_set():
                for seat, pad in owners.items():
                    if rng.random() < 0.5:
                        chosen = [(b, v) for _, b, v in SNES if rng.random() < 0.25]
                        value = sum(v for _, v in chosen)
                        for u, d in OPPOSITE:  # never hold opposite directions (the emulator drops them)
                            if value & u and value & d:
                                chosen = [(b, v) for b, v in chosen if v != d]
                                value &= ~d
                        set_pad(pad, [b for b, _ in chosen])
                        sent[seat].add(value)
                time.sleep(rng.uniform(0.03, 0.15))
            for pad in owners.values():
                set_pad(pad, [])
        masher = threading.Thread(target=mash, daemon=True)
        copies = list(self.live)
        host = self.copies["P1"]
        start_frame = host.frame() or 0
        histories = {c.name: {} for c in copies}
        checked, bad_frames, mismatches, looks, unreadable = set(), set(), [], 0, 0
        frames_seen = []
        t_start = time.perf_counter()
        masher.start()
        side = threading.Thread(target=side_job, daemon=True) if side_job else None
        if side:
            side.start()
        while masher.is_alive():
            t = time.time()
            mems = {c: c.ram(0, 0x400) for c in copies}
            lists = {c: c.ram(cart.CHANGES_AT, cart.CHANGE_SIZE * cart.CHANGE_SLOTS) for c in copies}
            if not all(mems.values()) or not all(lists.values()):
                unreadable += 1
                time.sleep(0.25)
                continue
            looks += 1
            frames = {c: frame_of(m) for c, m in mems.items()}
            frames_seen.append((time.perf_counter(), dict((c.name, f) for c, f in frames.items())))
            hi, lo = max(frames.values()), min(frames.values())
            settled = lo - MARGIN
            for c in copies:
                keep_changes(histories[c.name], mems[c], lists[c], settled)
            for fr in range(max(hi - 255, start_frame + 1, 1), settled + 1):
                checked.add(fr)
                vals = {c.name: mems[c][0x300 + (fr & 0xFF)] for c in copies}
                if len(set(vals.values())) > 1 and fr not in bad_frames:
                    bad_frames.add(fr)
                    if len(mismatches) < 10:
                        mismatches.append({"frame": fr, "values": vals})
            time.sleep(max(0, 0.25 - (time.time() - t)))
        masher.join()
        if side:
            side.join(60)
        time.sleep(2.5)
        # final read
        for c in copies:
            m, l = c.ram(0, 0x400), c.ram(cart.CHANGES_AT, cart.CHANGE_SIZE * cart.CHANGE_SLOTS)
            if m and l:
                keep_changes(histories[c.name], m, l, frame_of(m) - 2)
        t_end = time.perf_counter()
        hist_host = {k: v for k, v in histories[host.name].items() if v[0] > start_frame}
        diffs = []
        for c in copies:
            h = {k: v for k, v in histories[c.name].items() if v[0] > start_frame}
            common = set(h) & set(hist_host)
            d = [k for k in common if h[k] != hist_host[k]]
            if d or len(common) < 0.9 * len(hist_host):
                diffs.append({"copy": c.name, "different": len(d), "common": len(common), "host_changes": len(hist_host)})
        strays = {}
        for k, (f, *seats) in hist_host.items():
            for s in range(5):
                if seats[s] not in sent[s + 1]:
                    strays.setdefault(s + 1, set()).add(seats[s])
        span = (frames_seen[0][1], frames_seen[-1][1]) if frames_seen else ({}, {})
        dur = frames_seen[-1][0] - frames_seen[0][0] if len(frames_seen) > 1 else 0
        fps = {n: round((span[1][n] - span[0][n]) / dur, 1) for n in span[0] if dur and n in span[1]}
        out = {"label": label, "copies": [c.name for c in copies], "seconds": seconds, "looks": looks, "unreadable": unreadable,
               "frames_compared": len(checked), "frames_different": len(bad_frames), "first_differences": mismatches,
               "button_changes_host": len(hist_host), "histories_not_matching": diffs,
               "seat_states_not_from_their_pad": {k: sorted(v)[:10] for k, v in strays.items()},
               "fps": fps, "host_longest_stop_ms": self.watch.longest_stop_ms(t_start, t_end) if self.watch else None}
        say(f"  {looks} looks, {len(checked)} frames compared across {len(copies)} copies, {len(bad_frames)} different; "
            f"{len(hist_host)} button changes, histories matching in every copy: {not diffs}; strays: {out['seat_states_not_from_their_pad']}; fps {fps}")
        self.res.setdefault("sync", []).append(out)
        if bad_frames:
            fail(f"{self.name}: copies went out of sync ({label}), first different frame {mismatches[0]['frame']}")
        if diffs:
            fail(f"{self.name}: button-change histories differ ({label}): {diffs[:3]}")
        if strays:
            fail(f"{self.name}: a seat showed buttons its pad wasn't given ({label}): {out['seat_states_not_from_their_pad']}")
        if looks < seconds * 2:
            fail(f"{self.name}: too few readings ({looks}) to trust the sync check ({label})")
        played = (span[1].get(host.name, 0) - span[0].get(host.name, 0)) if frames_seen else 0
        out["frames_played_host"] = played
        if played and len(checked) < 0.8 * (played - MARGIN):
            fail(f"{self.name}: only {len(checked)} of ~{played} frames could be compared ({label})")
        return out

    def event(self, name, action, seconds=12):
        """Runs something (switch seats, drop someone) and measures whether the game stopped for the others."""
        say(f"\n-- {name}")
        t0 = time.perf_counter()
        note = action()
        time.sleep(seconds)
        t1 = time.perf_counter()
        # the host (a player) and W3 (a watcher who stays the whole time)
        watches = {"host P1": {"longest_stop_ms": self.watch.longest_stop_ms(t0, t1), "fps": self.watch.fps(t0, t1)}}
        if getattr(self, "w3watch", None):
            watches["watcher W3"] = {"longest_stop_ms": self.w3watch.longest_stop_ms(t0, t1), "fps": self.w3watch.fps(t0, t1)}
        logs = {c.name.split("-")[-1]: c.new_netplay_lines()[-8:] for c in self.copies.values() if c.proc}
        ev = {"event": name, "game_for_others": watches, "note": note, "netplay_log": {k: v for k, v in logs.items() if v}}
        say(f"   game for the others: {watches}; note: {note}")
        for k, v in ev["netplay_log"].items():
            for line in v:
                say(f"   | {k}: {line}")
        self.res["events"].append(ev)
        return ev

    # --- the round
    def run(self):
        say(f"\n################ round: {self.name} ################")
        res = self.res
        pads = self.pads
        slots = self.slots
        host = self.person("P1", 0, slots[1], {"netplay_request_device_p1": "true"})
        for n in (2, 3, 4):
            self.person(f"P{n}", n - 1, slots[n], {f"netplay_request_device_p{n}": "true"})
        # W1 shares pad D's slot: when P4 moves to watching and W1 takes seat 4, pad D is "handed over".
        self.person("W1", 4, slots[4], {"netplay_start_as_spectator": "true", "netplay_request_device_p4": "true"})
        for n in (2, 3, 4):
            self.person(f"W{n}", 3 + n, 15, {"netplay_start_as_spectator": "true"})
        try:
            if self.place:
                relay_host, relay_port = np.relay_address(self.place)
                self.relay = (relay_host, relay_port)
                plain = np.connect_times(relay_host, relay_port)
                res["relay"] = {"place": self.place, "address": f"{relay_host}:{relay_port}", "plain_connect_ms": plain}
                say(f"{self.place} relay is {relay_host}:{relay_port}; plain connect {plain} ms")
            else:
                self.proxy = CutProxy()
            for attempt in range(1, 4):
                host.start(self.rom, ["--host", "--port", str(NETPLAY_PORT)])
                if host.locate(40):
                    break
                code = None if host.alive() else hex(host.proc.returncode & 0xFFFFFFFF)
                res.setdefault("host_start_problems", []).append({"attempt": attempt, "exit_code": code})
                say(f"  the host's RetroArch {'never showed the game' if code is None else 'closed by itself, exit code ' + code}")
                host.kill()
            else:
                fail(f"{self.name}: the host's game never started (3 tries: {res['host_start_problems']})")
                return res
            self.live.append(host)
            self.watch = FrameWatch(host)
            self.watch.start()
            time.sleep(2)
            if self.place:
                self.bridge = FreezableBridge(relay_host, relay_port, NETPLAY_PORT)
                self.bridge.start()
                self.bridge.ready.wait(30)
                if not self.bridge.session:
                    fail(f"{self.name}: no session from the {self.place} relay ({self.bridge.error})")
                    return res
                say(f"bridge holds a {self.place} relay session; nothing is listed")

            # ---- 2. everyone joins: 3 more players, then 4 watchers
            for who in ("P2", "P3", "P4", "W1", "W2", "W3", "W4"):
                self.join(who)
                time.sleep(1)
            if len(self.live) < 8:
                fail(f"{self.name}: only {len(self.live)} of 8 copies joined")
            self.w3watch = FrameWatch(self.copies["W3"])
            self.w3watch.start()
            grab().save(OUT / f"{self.name}-1-everyone-in.png")
            owners = {1: pads[1], 2: pads[2], 3: pads[3], 4: pads[4]}
            self.seat_check(owners, "4 players, 4 watchers")
            self.mash_and_compare(owners, MASH_SECONDS, "4 players + 4 watchers")
            grab().save(OUT / f"{self.name}-2-after-play.png")

            # ---- 3a. switch: P4 moves to watching mid-game; W1 takes seat 4; P4 asks to play again (seats full)
            p4, w1 = self.copies["P4"], self.copies["W1"]
            self.event("P4 switches to watching (mid-game)", lambda: p4.send("NETPLAY_GAME_WATCH"), 6)
            res["p4_watching_pad_d_goes_nowhere"] = self.pad_goes_nowhere(pads[4], "after P4 moved to watching, pad D")
            self.event("W1 switches to playing (asks for seat 4)", lambda: w1.send("NETPLAY_GAME_WATCH"), 6)
            self.seat_check(owners, "seat 4 now W1's (pad D handed over)")
            self.event("P4 asks to play again while all 4 seats are taken", lambda: p4.send("NETPLAY_GAME_WATCH"), 6)
            self.mash_and_compare(owners, SHORT_MASH, "after switching")
            self.event("W1 back to watching", lambda: w1.send("NETPLAY_GAME_WATCH"), 6)
            self.event("P4 back to playing (seat 4)", lambda: p4.send("NETPLAY_GAME_WATCH"), 6)
            self.seat_check(owners, "seat 4 back to P4")

            # ---- 3b. drop-outs and rejoins, game keeps going
            p2, p3, w2 = self.copies["P2"], self.copies["P3"], self.copies["W2"]
            self.event("P2's game closes suddenly (crash or quit)", lambda: (p2.kill(), self.live.remove(p2))[1], 8)
            res["seat_2_empty_after_drop"] = self.pad_goes_nowhere(pads[2], "after P2 dropped, pad B")
            self.join("P2", "rejoin with the same seat")
            self.seat_check(owners, "P2 rejoined")

            def go_silent():
                if self.bridge:
                    n = self.link_of.get("P3")
                    self.bridge.frozen.add(n)
                    return f"froze relay link {n}"
                self.proxy.freeze(self.port_of[p3.name])
                return "froze P3's connection"
            self.event("P3's internet goes silent (connection not closed)", go_silent, 20)
            p3_alive = p3.alive()
            p3.kill()
            if p3 in self.live:
                self.live.remove(p3)
            res["p3_copy_still_running_after_20s_silence"] = p3_alive
            self.join("P3", "rejoin after going silent")
            self.seat_check(owners, "P3 rejoined")
            self.event("W2 (a watcher) closes suddenly", lambda: (w2.kill(), self.live.remove(w2))[1], 6)
            self.join("W2", "rejoin as a watcher")

            # ---- the window trick during online play: host's game into a box, full screen, back
            def window_tricks():
                hwnd = host.main_window()
                if not hwnd:
                    return
                sw, sh = screen_size()
                st = (u32.GetWindowLongPtrW(hwnd, GWL_STYLE) & ~WS_DECOR) | WS_POPUP | WS_VISIBLE
                u32.SetWindowLongPtrW(hwnd, GWL_STYLE, st)
                for x, y, w, h in ((440, 140, 512, 448), (0, 0, sw, sh), (440, 140, 512, 448), (0, 0, sw, sh), (0, 30, 256, 224)):
                    time.sleep(4)
                    u32.SetWindowPos(hwnd, 0, x, y, w, h, SWP_FRAMECHANGED | SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW)
            self.mash_and_compare(owners, SHORT_MASH, "after drop-outs, host's window into a box and full screen and back", window_tricks)
            grab().save(OUT / f"{self.name}-3-end.png")
            res["ok"] = not [f for f in failures if f.startswith(f"{self.name}:")]
            return res
        finally:
            for w in (self.watch, getattr(self, "w3watch", None)):
                if w:
                    w.stop.set()
            if self.bridge:
                res.setdefault("relay", {})["bridge"] = dict(self.bridge.stats, error=self.bridge.error, events=self.bridge.events[-40:])
                self.bridge.stop()
            for c in self.copies.values():
                if c.proc:
                    c.quit()
            subprocess.run(["taskkill", "/F", "/IM", "retroarch.exe"], capture_output=True)
            time.sleep(2)


def keep_changes(store, ram, changes, settled):
    """Adds the change list's entries to store (change number -> (full frame, seat1..seat5)), for frames up to
    `settled` only (newer ones can still be redone by netplay). Skips the 8 oldest slots, which a change made
    between the two reads could have overwritten."""
    total = ram[8] | ram[9] << 8
    now = frame_of(ram)
    n = min(total, cart.CHANGE_SLOTS)
    for k in range(total - n, total):
        if k < total - (cart.CHANGE_SLOTS - 8):
            continue
        e = changes[(k % cart.CHANGE_SLOTS) * cart.CHANGE_SIZE:(k % cart.CHANGE_SLOTS) * cart.CHANGE_SIZE + cart.CHANGE_SIZE]
        f16 = e[0] | e[1] << 8
        full = (now & ~0xFFFF) | f16
        if full > now:
            full -= 0x10000
        if full <= settled:
            store[k] = (full, *[e[2 + 2 * i] << 8 | e[3 + 2 * i] for i in range(5)])


def eight_alone(rom, slots):
    """Yardstick: 8 copies side by side, NOT connected. How fast can this machine run 8 at once?"""
    copies = [SnesCopy(f"alone-{i}", 55380 + i, 15, x=(i % 4) * 250, y=30 + (i // 4) * 280) for i in range(8)]
    try:
        for c in copies:
            c.write_config()
            c.start(rom, [])
        for c in copies:
            if not c.locate(40):
                fail("couldn't find the game's RAM in an unconnected copy")
                return None
        time.sleep(3)
        t0, f0 = time.time(), [c.frame() for c in copies]
        time.sleep(20)
        t1, f1 = time.time(), [c.frame() for c in copies]
        fps = [round((b - a) / (t1 - t0), 1) for a, b in zip(f0, f1)]
        say(f"8 copies side by side, not connected: {fps} frames a second")
        grab().save(OUT / "eight-alone.png")
        return fps
    finally:
        for c in copies:
            c.quit()
        subprocess.run(["taskkill", "/F", "/IM", "retroarch.exe"], capture_output=True)
        time.sleep(2)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    rom = WORK / "couch-4p-test.sfc"
    rom.write_bytes(cart.rom())
    say(f"RetroArch: {EXE} ({EXE.stat().st_size} bytes); core {CORE.name}; screen {screen_size()}")
    say("plugging in four pretend Xbox pads: A, B, C, D for seats 1-4")
    pads, slots = {}, {}
    for seat, label in zip((1, 2, 3, 4), "ABCD"):
        pads[seat], slots[seat] = np.plug(label)
    if None in slots.values() or len(set(slots.values())) < 4:
        say("  couldn't read the Xbox slots; assuming A-D = 0-3")
        slots = {1: 0, 2: 1, 3: 2, 4: 3}
    summary = {"parts": []}

    def run_part(name, fn):
        if ONLY and name not in ONLY:
            return
        try:
            summary["parts"].append(fn())
        except Exception as e:  # noqa: BLE001 - one broken part shouldn't hide the others' numbers
            where = traceback.format_exc()
            say(where)
            fail(f"{name}: stopped with {type(e).__name__}: {e}")
            summary["parts"].append({"part": name, "error": f"{type(e).__name__}: {e}", "where": where})
            subprocess.run(["taskkill", "/F", "/IM", "retroarch.exe"], capture_output=True)

    run_part("box", lambda: part_box(rom, pads[1], slots[1]))
    if not ONLY or any(p.startswith("couch") for p in ONLY):
        summary["eight_unconnected_fps"] = eight_alone(rom, slots)
    run_part("couch-direct", lambda: Couch("couch-direct", rom, pads, slots).run())
    run_part("couch-relay-nyc", lambda: Couch("couch-relay-nyc", rom, pads, slots, place="nyc").run())
    summary["ok"] = not failures
    summary["failures"] = failures
    (OUT / "results.json").write_text(json.dumps(summary, indent=2, default=str))
    say("\n================ summary ================")
    say(json.dumps(summary, indent=2, default=str)[:60000])
    if failures:
        for f in failures:
            print(f"::error::couch lobby test: {f}", flush=True)
        sys.exit(1)
    say("\nall parts passed")


if __name__ == "__main__":
    main()
