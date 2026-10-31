#!/usr/bin/env python3
"""CI only (GitHub's Windows machine): can the approved in-game menu and display (boards IG1-IG3, approved by
Jayden 2026-10-31) work with Game Night's RetroArch? Measured before anything is built:

  "looks"  One game, full screen at 1920x1080:
           - where whole-pixel (integer) scaling puts the game, for square pixels, the console's own shape and 4:3;
           - a bezel picture with a hole cut exactly there: bezel all around, live game in the hole;
           - every "look" (scanlines, CRT Lottes, CRT Geom, CRT Royale) switched LIVE with RetroArch's SET_SHADER
             command (also from a folder with a space in its name) and back to the plain look (look off): the look
             shows, stays inside the game (bezel untouched), and how fast the game still runs with it;
           - the same SET_SHADER sent on RetroArch's standard input (stdin) instead of its local command port;
           - bezel C (libretro's animated Super Famicom border): loads, lights up with the pad, and a mouse click on
             its pictured buttons does NOT press anything in the game.
  "couch"  Couch Play on this machine: host P1 and P2 play, W1 watches, each with a DIFFERENT look (and P1 a bezel):
           - same game in every copy (0 frames out of sync), while looks also change mid-game;
           - "Pause for everyone": P2 pauses, the game stops for all; P2 resumes; the host pauses too;
             who paused shows in the others' logs (for "Paused by <name>");
           - with pausing allowed, switching windows still never pauses anyone;
           - "your menu is open": RetroArch's own menu, open but hidden behind Game Night's, stops YOUR presses
             reaching the game while the game keeps running for everyone (random presses into it for 15 s);
             compared with the known way (switch to watching and back, which frees the seat meanwhile).

    python ingame_menu_test.py <player folder> <work folder> <results folder>

<player folder> is what tools/player/fetch_player.py builds. Nothing is installed or changed outside <work folder>
and <results folder>, and nothing goes to the internet. INGAME_PARTS picks parts ("looks", "couch"); all by default.
"""
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import couch_lobby_test as cl  # noqa: E402  (same command line: player, work, results)
import make_snes_multitap_rom as cart  # noqa: E402
import netplay_test as np  # noqa: E402

from couch_lobby_test import B, SNES, PLAYER, WORK, OUT, say, fail, set_pad, grab, u32  # noqa: E402

ONLY = [p for p in os.environ.get("INGAME_PARTS", "").replace(",", " ").split() if p]
MASH_SECONDS = int(os.environ.get("INGAME_MASH_SECONDS", "60"))
SHADERS = PLAYER / "shaders"
LOOKS = {
    "plain": SHADERS / "slang" / "nearest.slangp",
    "scanlines": SHADERS / "scanlines.slangp",
    "lottes": SHADERS / "slang" / "crt" / "crt-lottes.slangp",
    "geom": SHADERS / "slang" / "crt" / "crt-geom.slangp",
    "royale": SHADERS / "slang" / "crt" / "crt-royale.slangp",
}
BEZEL_C_SNES = PLAYER / "overlays" / "animated-border" / "super_famicom_animated_border.cfg"
BEZEL_RGB = (24, 200, 90)
# What Game Night would set with every bezel: the bezel is a picture only (no mouse/touch buttons), it never hides
# because a pad is plugged in, and RetroArch's own menu (hidden behind Game Night's) has nothing on it to choose.
DISPLAY = {
    "input_overlay_pointer_enable": "false", "input_overlay_hide_when_gamepad_connected": "false",
    "input_overlay_auto_scale": "false", "input_overlay_opacity": "1.000000", "input_overlay_scale_landscape": "1.000000",
    "input_overlay_show_mouse_cursor": "true", "input_overlay_hide_in_menu": "false", "input_overlay_behind_menu": "true",
    "input_overlay_enable_autopreferred": "false",
}
QUIET_MENU = {
    "kiosk_mode_enable": "true", "menu_show_load_core": "false", "menu_show_load_content": "false",
    "menu_show_quit_retroarch": "false", "menu_show_restart_retroarch": "false", "menu_show_information": "false",
    "menu_show_configurations": "false", "menu_show_help": "false", "menu_show_overlays": "false",
    "menu_show_rewind": "false", "menu_show_latency": "false",
    **{f"quick_menu_show_{k}": "false" for k in (
        "resume_content", "restart_content", "close_content", "savestate_submenu", "save_load_state", "replay",
        "take_screenshot", "undo_save_load_state", "add_to_favorites", "add_to_playlist", "start_recording",
        "start_streaming", "set_core_association", "reset_core_association", "options", "core_options_flush",
        "controls", "cheats", "shaders", "save_core_overrides", "save_content_dir_overrides", "save_game_overrides",
        "information", "download_thumbnails")},
}
# RetroArch's own menu drawn fully see-through (every colour's alpha 0): when it is open behind Game Night's menu
# only to hold your presses back, nothing of it should show on the game.
INVISIBLE_THEME = "".join(f"rgui_{k}_color = \"0x00000000\"\n" for k in (
    "entry_normal", "entry_hover", "title", "bg_dark", "bg_light", "border_dark", "border_light", "shadow", "particle"))
results = {"parts": []}


# ---------------------------------------------------------------- measuring the picture

def changed_box(seconds=1.2, shots=4):
    """Bounding box of everything that changed between a few screenshots (the game's colour changes every frame;
    a bezel never changes), as (x, y, w, h), plus the last screenshot."""
    from PIL import ImageChops
    imgs = []
    for _ in range(shots):
        imgs.append(grab().convert("RGB"))
        time.sleep(seconds / shots)
    box = None
    for a, b in zip(imgs, imgs[1:]):
        bb = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 12 else 0).getbbox()
        if bb:
            box = bb if box is None else (min(box[0], bb[0]), min(box[1], bb[1]), max(box[2], bb[2]), max(box[3], bb[3]))
    rect = (box[0], box[1], box[2] - box[0], box[3] - box[1]) if box else None
    return rect, imgs


def structure(imgs, rect):
    """How much pattern the game area has (a look's scanlines/mask): the game itself is one flat colour per frame,
    so with no look this is ~0. Highest standard deviation of brightness inside the rect over the screenshots."""
    from PIL import ImageStat
    if not rect:
        return None
    x, y, w, h = rect
    best = 0.0
    for im in imgs:
        crop = im.crop((x + w // 8, y + h // 8, x + w - w // 8, y + h - h // 8)).convert("L")
        best = max(best, ImageStat.Stat(crop).stddev[0])
    return round(best, 1)


def bezel_share(img, rect):
    """Share of the screen OUTSIDE the game rect that shows the test bezel's colour."""
    small = img.resize((img.width // 4, img.height // 4))
    x, y, w, h = [v // 4 for v in rect]
    total = hit = 0
    for j in range(small.height):
        for i in range(small.width):
            if x - 2 <= i <= x + w + 1 and y - 2 <= j <= y + h + 1:
                continue
            total += 1
            p = small.getpixel((i, j))
            if all(abs(p[k] - BEZEL_RGB[k]) < 24 for k in range(3)):
                hit += 1
    return round(hit / max(1, total), 3)


def inside(a, b, slack=2):
    """Rect a lies inside rect b."""
    return a is not None and b is not None and a[0] >= b[0] - slack and a[1] >= b[1] - slack \
        and a[0] + a[2] <= b[0] + b[2] + slack and a[1] + a[3] <= b[1] + b[3] + slack


def make_test_bezel(folder, size, hole):
    """A plain green bezel picture the size of the screen with a see-through hole where the game is, and the
    RetroArch overlay file that shows it (a picture only: no buttons)."""
    from PIL import Image, ImageDraw
    folder.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", size, BEZEL_RGB + (255,))
    x, y, w, h = hole
    ImageDraw.Draw(img).rectangle((x, y, x + w - 1, y + h - 1), fill=(0, 0, 0, 0))
    img.save(folder / "bezel.png")
    cfg = folder / "bezel.cfg"
    cfg.write_text("overlays = 1\noverlay0_overlay = bezel.png\noverlay0_full_screen = true\n"
                   "overlay0_normalized = true\noverlay0_descs = 0\n", encoding="ascii")
    return cfg


def log_lines(copy, since, words=("hader", "slang", "verlay", "[ERROR]", "Failed", "failed", "aus")):
    lines = copy.log_text().splitlines()[since:]
    return [l for l in lines if any(w in l for w in words)][-12:]


def fps_over(copy, seconds):
    f0, t0 = copy.frame(), time.perf_counter()
    time.sleep(seconds)
    f1, t1 = copy.frame(), time.perf_counter()
    return round((f1 - f0) / (t1 - t0), 1) if f0 is not None and f1 is not None else None


# ---------------------------------------------------------------- part 1: looks, bezels, whole-pixel scaling

def full_screen(extra=None):
    s = {"video_fullscreen": "true", "video_windowed_fullscreen": "true", "video_font_enable": "false",
         "video_scale_integer": "true", "aspect_ratio_index": "22", **DISPLAY}
    s.update(extra or {})
    return s


def start_copy(copy, rom, extra, args=None, stdin=False):
    copy.write_config(extra)
    if not stdin:
        copy.start(rom, args or [])
    else:
        log = copy.dir / "logs" / "retroarch.log"
        if log.exists():
            log.unlink()
        a = [str(cl.EXE), "-c", str(copy.cfg), "-L", str(cl.CORE), *(args or []), str(rom)]
        say(f"starting {copy.name} with commands on its standard input: {' '.join(a[1:])}")
        copy.proc = subprocess.Popen(a, cwd=str(PLAYER), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT)
        copy.mem, copy.base = None, None
    if not copy.locate(40):
        fail(f"looks: couldn't find the game's RAM in {copy.name}")
        return False
    time.sleep(2.5)
    return True


def stop_copy(copy):
    copy.quit()
    subprocess.run(["taskkill", "/F", "/IM", "retroarch.exe"], capture_output=True)
    time.sleep(1.5)


def part_looks(rom, pad, slot):
    say("\n################ part 1: whole-pixel scaling, bezels and looks (one game, full screen) ################")
    res = {"part": "looks", "screen": cl.screen_size(), "scaling": {}, "looks": {}}
    sw, sh = cl.screen_size()
    copy = cl.SnesCopy("looks", 55600, slot)

    # 1. where whole-pixel scaling puts the game
    for name, aspect in (("square pixels", "21"), ("console's own shape", "22"), ("4:3", "0")):
        if not start_copy(copy, rom, full_screen({"aspect_ratio_index": aspect})):
            return res
        rect, imgs = changed_box()
        imgs[-1].save(OUT / f"looks-scaling-{aspect}.png")
        whole = bool(rect and rect[3] % 224 == 0)
        res["scaling"][name] = {"aspect_ratio_index": aspect, "game_rect": rect, "height_whole_pixels": whole,
                                "height_x": round(rect[3] / 224, 3) if rect else None, "width_x": round(rect[2] / 256, 3) if rect else None,
                                "fps": fps_over(copy, 3)}
        say(f"  {name}: game at {rect} (height {res['scaling'][name]['height_x']}x, width {res['scaling'][name]['width_x']}x)")
        stop_copy(copy)
        if not whole:
            fail(f"looks: whole-pixel scaling ({name}) didn't give a whole-pixel height: {rect}")
    rect = res["scaling"]["console's own shape"]["game_rect"]
    if not rect:
        fail("looks: couldn't see where the game is on screen")
        return res

    # 2. a bezel with a hole exactly over the game, then every look switched live
    bezel = make_test_bezel(WORK / "test bezel", (sw, sh), rect)
    if not start_copy(copy, rom, full_screen({"input_overlay_enable": "true", "input_overlay": str(bezel)})):
        return res
    r2, imgs = changed_box()
    imgs[-1].save(OUT / "looks-bezel-off.png")
    base = {"game_rect": r2, "bezel_share_outside_game": bezel_share(imgs[-1], rect), "structure": structure(imgs, rect),
            "fps": fps_over(copy, 4), "log": log_lines(copy, 0)}
    res["bezel"] = base
    say(f"  test bezel: {base}")
    if base["bezel_share_outside_game"] < 0.97 or not inside(r2, rect) or (r2[2] * r2[3]) < 0.95 * rect[2] * rect[3]:
        fail(f"looks: the bezel didn't sit around the game exactly ({base})")

    def look(name, command, settle=4.0):
        since = len(copy.log_text().splitlines())
        copy.send(command)
        time.sleep(settle)
        rr, ims = changed_box()
        ims[-1].save(OUT / f"looks-{name}.png")
        out = {"command": command, "changed_area": rr, "inside_game": inside(rr, rect),
               "bezel_share_outside_game": bezel_share(ims[-1], rect), "structure": structure(ims, rect),
               "fps": fps_over(copy, 5), "alive": copy.alive(), "log": log_lines(copy, since)}
        res["looks"][name] = out
        say(f"  {name}: pattern {out['structure']} (no look: {base['structure']}), bezel {out['bezel_share_outside_game']}, "
            f"inside the game {out['inside_game']}, {out['fps']} frames a second")
        for l in out["log"]:
            say(f"    | {l}")
        return out

    for name, path in LOOKS.items():
        o = look(name, f"SET_SHADER {path}", settle=12.0 if name == "royale" else 4.0)
        if not o["alive"]:
            fail(f"looks: RetroArch closed when switching to {name}")
            return res
        if name != "plain" and (o["structure"] or 0) < (base["structure"] or 0) + 3:
            fail(f"looks: {name} didn't show (pattern {o['structure']})")
        if o["bezel_share_outside_game"] < 0.97:
            fail(f"looks: {name} drew over the bezel ({o['bezel_share_outside_game']})")
    shows = lambda o: (o["structure"] or 0) >= (base["structure"] or 0) + 3  # noqa: E731
    # turning a look off live = switching to the plain look (SHADER_TOGGLE measured unreliable in run 41220810666:
    # after CRT Royale it re-applied Royale, then a saved "retroarch.slangp")
    res["plain_turns_look_off"] = not shows(look("plain (look off)", f"SET_SHADER {LOOKS['plain']}"))
    if not res["plain_turns_look_off"]:
        fail("looks: switching to the plain look didn't turn the CRT look off")
    stop_copy(copy)
    # a folder with a space in its name (Windows user names often have one), from a fresh start with no look
    spaced = WORK / "a folder with spaces"
    if spaced.exists():
        shutil.rmtree(spaced)
    shutil.copytree(SHADERS / "zfast_crt", spaced / "zfast_crt")
    shutil.copy2(LOOKS["scanlines"], spaced / "scanlines.slangp")
    if start_copy(copy, rom, full_screen({"input_overlay_enable": "true", "input_overlay": str(bezel)})):
        res["path_with_spaces_works"] = shows(look("scanlines from a folder with spaces", f"SET_SHADER {spaced / 'scanlines.slangp'}"))
        if not res["path_with_spaces_works"]:
            fail("looks: SET_SHADER didn't work from a folder with spaces in its name")
    stop_copy(copy)

    # 3. the same command on standard input
    say("\nSET_SHADER on RetroArch's standard input (stdin)")
    st = {}
    if start_copy(copy, rom, full_screen({"stdin_cmd_enable": "true", "input_overlay_enable": "false"}), stdin=True):
        got = []
        reader = threading.Thread(target=lambda: got.extend(iter(copy.proc.stdout.readline, b"")), daemon=True)
        reader.start()
        try:
            copy.proc.stdin.write(b"VERSION\n")
            copy.proc.stdin.flush()
            time.sleep(2)
            r_before, ims0 = changed_box()
            copy.proc.stdin.write(f"SET_SHADER {LOOKS['lottes']}\n".encode())
            copy.proc.stdin.flush()
            time.sleep(4)
            r_after, ims1 = changed_box()
            ims1[-1].save(OUT / "looks-stdin.png")
            st = {"stdout_lines": [l.decode(errors="replace").rstrip() for l in got][-10:],
                  "structure_before": structure(ims0, rect), "structure_after": structure(ims1, rect),
                  "log": log_lines(copy, 0)}
        except OSError as e:
            st = {"error": f"{type(e).__name__}: {e}"}
        st["works"] = bool(st.get("structure_after") is not None and st["structure_after"] >= (st.get("structure_before") or 0) + 3)
        stop_copy(copy)
    res["stdin"] = st
    say(f"  stdin: {st}")

    # 4. bezel C: libretro's animated Super Famicom border
    say("\nbezel C (animated Super Famicom border)")
    c = {"file": str(BEZEL_C_SNES), "exists": BEZEL_C_SNES.is_file()}
    if c["exists"] and start_copy(copy, rom, full_screen({"input_overlay_enable": "true", "input_overlay": str(BEZEL_C_SNES),
                                                          "input_overlay_show_inputs": "2", "input_overlay_show_inputs_port": "0"})):
        u32.SetForegroundWindow(copy.main_window() or 0)
        time.sleep(1)
        idle = grab().convert("RGB")
        idle.save(OUT / "looks-bezel-c-idle.png")
        set_pad(pad, [B.XUSB_GAMEPAD_A, B.XUSB_GAMEPAD_DPAD_UP, B.XUSB_GAMEPAD_LEFT_SHOULDER])
        time.sleep(0.8)
        pressed = grab().convert("RGB")
        pressed.save(OUT / "looks-bezel-c-pressed.png")
        game_saw = copy.ram(0x10, 2)
        set_pad(pad, [])
        from PIL import ImageChops
        bb = ImageChops.difference(idle, pressed).convert("L").point(lambda v: 255 if v > 30 else 0)
        # changes outside the game area = the bezel's buttons lighting up
        x, y, w, h = rect
        from PIL import ImageDraw
        ImageDraw.Draw(bb).rectangle((x - 4, y - 4, x + w + 4, y + h + 4), fill=0)
        c["lights_up_with_the_pad"] = bb.getbbox()
        c["game_saw_the_pad"] = bool(game_saw and game_saw[0] & 0x08)
        # a mouse click where the border pictures the A button (its overlay file: "a,0.97043,0.4725")
        ax, ay = int(0.97043 * sw), int(0.4725 * sh)

        def clicks():
            u32.SetCursorPos(ax, ay)
            seen = []
            for _ in range(3):
                u32.mouse_event(0x2, 0, 0, 0, 0)
                time.sleep(0.25)
                seen.append(copy.ram(0x10, 2))
                u32.mouse_event(0x4, 0, 0, 0, 0)
                time.sleep(0.25)
            return any(m and (m[0] or m[1]) for m in seen)
        # 1. RetroArch's own "overlay pointer" setting off (run 41221344002: the click still pressed A)
        c["mouse_click_on_pictured_button_pressed_it"] = clicks()
        # 2. Game Night switches the game window to "disabled" (Windows then gives it no mouse or keyboard input)
        hwnd = copy.main_window()
        u32.EnableWindow.argtypes = [cl.wt.HWND, cl.wt.BOOL]
        u32.EnableWindow(hwnd, False)
        time.sleep(0.5)
        c["window_disabled_click_pressed_it"] = clicks()
        set_pad(pad, [B.XUSB_GAMEPAD_A])
        time.sleep(0.5)
        m = copy.ram(0x10, 2)
        set_pad(pad, [])
        c["window_disabled_pad_still_works"] = bool(m and m[0] & 0x80)
        c["window_disabled_game_live"] = fps_over(copy, 2)
        u32.EnableWindow(hwnd, True)
        c["fps"] = fps_over(copy, 4)
        c["log"] = log_lines(copy, 0)
        stop_copy(copy)
    res["bezel_c"] = c
    say(f"  bezel C: {c}")
    if not c.get("lights_up_with_the_pad"):
        fail("looks: bezel C didn't light up when the pad was pressed")
    if c.get("window_disabled_click_pressed_it") is not False or not c.get("window_disabled_pad_still_works"):
        fail(f"looks: bezel C's pictured buttons can still be clicked, or the pad stopped ({c})")
    return res


# ---------------------------------------------------------------- part 2: Couch Play with a look each, pause, menu

class Trio(cl.Couch):
    """Host P1 and P2 play, W1 watches."""

    def set_look(self, who, look):
        c = self.copies[who]
        c.send(f"SET_SHADER {LOOKS[look]}")
        c.look = look

    def run(self):
        say("\n################ part 2: Couch Play, a different look each, pause for everyone, menu open ################")
        res = self.res
        pads, slots = self.pads, self.slots
        common = {"netplay_allow_pausing": "true", "menu_pause_libretro": "false", "pause_nonactive": "false",
                  **DISPLAY, **QUIET_MENU}
        bezel = make_test_bezel(WORK / "couch bezel", (256, 224), (16, 16, 224, 192))
        theme = WORK / "invisible-menu.cfg"
        theme.write_text(INVISIBLE_THEME, encoding="ascii")
        common.update({"rgui_menu_color_theme": "0", "rgui_menu_theme_preset": str(theme), "menu_rgui_transparency": "true",
                       "menu_rgui_shadows": "false", "rgui_particle_effect": "0", "menu_widget_scale_auto": "true",
                       "menu_enable_widgets": "false"})
        host = self.person("P1", 0, slots[1], {**common, "netplay_request_device_p1": "true",
                                                "input_overlay_enable": "true", "input_overlay": str(bezel)})
        self.person("P2", 1, slots[2], {**common, "netplay_request_device_p2": "true"})
        self.person("W1", 2, 15, {**common, "netplay_start_as_spectator": "true"})
        self.proxy = cl.CutProxy()
        watches = {}
        try:
            host.start(self.rom, ["--host", "--port", str(cl.NETPLAY_PORT)])
            if not host.locate(40):
                fail("couch: the host's game never started")
                return res
            self.live.append(host)
            self.watch = watches["P1"] = cl.FrameWatch(host)
            self.watch.start()
            time.sleep(2)
            for who in ("P2", "W1"):
                self.join(who)
                time.sleep(1)
            if len(self.live) < 3:
                fail(f"couch: only {len(self.live)} of 3 copies joined")
                return res
            for who in ("P2", "W1"):
                watches[who] = cl.FrameWatch(self.copies[who])
                watches[who].start()
            self.watches = watches
            owners = {1: pads[1], 2: pads[2]}

            # ---- a different look each
            # GitHub's machine has no graphics card (software drawing): CRT Lottes ran at 3 fps, Geom 10, Royale 4,
            # scanlines 60 (run 41220810666). So the players get the light looks; the slow one goes on the watcher
            # (does a slow WATCHER hold the players back?), and Royale on P2 is a measured slow-down for everyone.
            for who, look in (("P1", "scanlines"), ("P2", "plain"), ("W1", "geom")):
                self.set_look(who, look)
            time.sleep(4)
            grab().save(OUT / "couch-1-looks.png")
            res["looks_log"] = {who: log_lines(self.copies[who], 0, ("hader", "slang", "[ERROR]")) for who in ("P1", "P2", "W1")}
            self.seat_check(owners, "a different look each")
            r = self.mash_and_compare(owners, MASH_SECONDS, "P1 scanlines + bezel, P2 plain, W1 CRT Geom")
            res["fps_players_light_watcher_geom"] = r.get("fps")

            # ---- looks changing mid-game (P2 tries the heaviest, CRT Royale)
            def switch_looks():
                for who, look in (("P2", "royale"), ("W1", "plain"), ("P1", "plain")):
                    time.sleep(5)
                    self.set_look(who, look)
            self.mash_and_compare(owners, 30, "looks changed mid-game (P2 CRT Royale)", switch_looks)
            res["fps_with_p2_on_royale"] = {k: w.fps(time.perf_counter() - 10, time.perf_counter()) for k, w in watches.items()}
            say(f"  frames a second for everyone, P2 on CRT Royale: {res['fps_with_p2_on_royale']}")
            grab().save(OUT / "couch-2-royale.png")
            for who, look in (("P1", "scanlines"), ("P2", "plain"), ("W1", "plain")):
                self.set_look(who, look)
            time.sleep(8)

            p2, w1 = self.copies["P2"], self.copies["W1"]

            # ---- switching windows with pausing allowed
            def flip():
                for c in (w1, p2, host, w1):
                    h = c.main_window()
                    if h:
                        u32.SetForegroundWindow(h)
                    time.sleep(1.5)
            e = self.timed("windows switched in front, pausing allowed", flip, 1)
            res["window_switch_longest_stop_ms"] = e["stopped_ms"]
            if max(e["stopped_ms"].values()) > 1500:
                fail(f"couch: switching windows paused the game ({e['stopped_ms']})")

            # ---- "your menu is open": RetroArch's own menu, open and hidden, for P2 only
            res["menu"] = {"p2_picture_menu_closed": self.window_picture("P2", "couch-3-p2-menu-closed"),
                           "pad_b_reaches_game_before": self.seat_check({2: pads[2]}, "before P2's menu opens")}
            e = self.timed("P2's RetroArch menu opens", lambda: p2.send("MENU_TOGGLE"), 4)
            res["menu"]["open"] = e
            res["menu"]["pad_b_goes_nowhere"] = self.pad_goes_nowhere(pads[2], "P2's menu open, pad B")
            res["menu"]["p2_picture_menu_open"] = self.window_picture("P2", "couch-3-p2-menu-open")
            mash_b = self.masher(pads[2], 15, "menu")
            r = self.mash_and_compare({1: pads[1]}, 15, "P2's menu open: pad A plays, pad B pressed into the menu", mash_b)
            res["menu"]["sync_with_menu_open"] = r
            res["menu"]["p2_still_running"] = p2.alive()
            grab().save(OUT / "couch-4-p2-menu-after-presses.png")
            e = self.timed("P2's RetroArch menu closes", lambda: p2.send("MENU_TOGGLE"), 4)
            res["menu"]["close"] = e
            ok = self.seat_check(owners, "after P2's menu closed: pad B plays again")
            if not ok:
                say("  pad B doesn't reach the game after closing: maybe the presses closed the menu already; toggling once more")
                p2.send("MENU_TOGGLE")
                time.sleep(3)
                res["menu"]["needed_second_toggle"] = self.seat_check(owners, "after a second toggle")
            res["menu"]["blocks_own_presses"] = bool(res["menu"]["pad_b_reaches_game_before"]) and bool(res["menu"]["pad_b_goes_nowhere"]) \
                and not r["seat_states_not_from_their_pad"] and r["frames_compared"] > 0
            res["menu"]["game_kept_going"] = max(res["menu"]["open"]["stopped_ms"].values()) < 1500
            pic = res["menu"].get("p2_picture_menu_open") or {}
            res["menu"]["invisible_while_open"] = pic.get("pattern") is not None and pic["pattern"] < 3 and (pic.get("changed_share") or 0) > 0.3
            say(f"  P2's window with its RetroArch menu open: {pic} (menu invisible and game live: {res['menu']['invisible_while_open']})")
            if not res["menu"]["blocks_own_presses"]:
                fail("couch: with P2's menu open, pad B still reached the game")

            # ---- the known way, for comparison: switch to watching and back
            res["watch_way"] = [self.timed("P2 switches to watching", lambda: p2.send("NETPLAY_GAME_WATCH"), 4)]
            res["watch_way_pad_b_goes_nowhere"] = self.pad_goes_nowhere(pads[2], "P2 watching, pad B")
            res["watch_way"].append(self.timed("P2 back to playing", lambda: p2.send("NETPLAY_GAME_WATCH"), 4))
            self.seat_check(owners, "P2 back to playing")
            # ---- pause for everyone (last: in run 41221344002 a FRIEND's pause stuck the game for the others and
            # their resume never reached them, so the host's way and the friend's way are measured separately)
            res["pause"] = {}
            for who, name in (("P1", "host"), ("P2", "friend")):
                steps = [self.timed(f"{name} ({who}) pauses for everyone", lambda w=who: self.copies[w].send("PAUSE_TOGGLE"), 6),
                         self.timed(f"{name} ({who}) resumes", lambda w=who: self.copies[w].send("PAUSE_TOGGLE"), 6)]
                stops = [x["stopped_ms"] for x in steps]
                works = min(stops[0].values()) > 4000 and max(stops[1].values()) < 1500
                still = all(c.alive() for c in self.copies.values()) and not any(
                    "disconnected" in l for c in self.copies.values() for l in c.new_netplay_lines())
                res["pause"][name] = {"steps": steps, "works": works, "everyone_still_connected": still,
                                      "paused_by_lines": {k: [l for l in c.log_text().splitlines() if "paused" in l.lower()][-3:]
                                                          for k, c in self.copies.items()}}
                say(f"  {name} pause for everyone works: {works}; everyone still connected: {still}")
                self.ensure_running()
                if not works:
                    break
            res["pause_works_host"] = res["pause"]["host"]["works"]
            res["pause_works_friend"] = res["pause"].get("friend", {}).get("works")
            if not res["pause_works_host"]:
                fail(f"couch: the host's pause for everyone didn't stop and restart the game for everyone: {res['pause']['host']['steps']}")
            self.seat_check(owners, "after the pause checks")
            self.mash_and_compare(owners, 30, "end: everyone back")
            grab().save(OUT / "couch-5-end.png")
            res["ok"] = not [f for f in cl.failures if f.startswith("couch")]
            return res
        finally:
            for w in watches.values():
                w.stop.set()
            for c in self.copies.values():
                if c.proc:
                    c.quit()
            subprocess.run(["taskkill", "/F", "/IM", "retroarch.exe"], capture_output=True)
            time.sleep(2)

    def timed(self, label, action, seconds):
        """Runs something and measures, for every copy, the longest time its game stood still."""
        say(f"\n-- {label}")
        t0 = time.perf_counter()
        note = action()
        time.sleep(seconds)
        t1 = time.perf_counter()
        stopped = {k: w.longest_stop_ms(t0, t1) or 0 for k, w in self.watches.items()}
        logs = {k: c.new_netplay_lines()[-5:] for k, c in self.copies.items()}
        say(f"   longest stop per copy (ms): {stopped}")
        for k, v in logs.items():
            for line in v:
                say(f"   | {k}: {line}")
        return {"what": label, "stopped_ms": stopped, "note": note, "netplay_log": {k: v for k, v in logs.items() if v}}

    def window_picture(self, who, name):
        """How P2's game window looks: is the game live in it, and is anything drawn on top (a plain look on a
        flat-colour game has no pattern, so menu text would show as pattern)."""
        h = self.copies[who].main_window()
        if not h:
            return None
        rect = cl.client_screen_rect(h)
        box, imgs = changed_box()
        imgs[-1].crop((rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3])).save(OUT / f"{name}.png")
        live = cl.live_in((rect[0] + 8, rect[1] + 8, rect[2] - 16, rect[3] - 16))[0]
        return {"window": rect, "pattern": structure(imgs, rect), "changed_share": live["changed_share"]}

    def ensure_running(self):
        """After the pause checks: make sure nobody is left paused."""
        time.sleep(1)
        before = {k: c.frame() for k, c in self.copies.items()}
        time.sleep(1)
        stuck = [k for k, c in self.copies.items() if c.frame() == before[k]]
        if stuck:
            say(f"  still paused after the pause checks: {stuck}; the host toggles once more")
            self.copies["P1"].send("PAUSE_TOGGLE")
            time.sleep(2)

    def masher(self, pad, seconds, seed):
        rng = random.Random(seed)

        def go():
            end = time.time() + seconds
            while time.time() < end:
                chosen = [b for _, b, v in SNES if rng.random() < 0.25]
                set_pad(pad, chosen)
                time.sleep(rng.uniform(0.05, 0.2))
            set_pad(pad, [])
        return go


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    rom = WORK / "ingame-test.sfc"
    rom.write_bytes(cart.rom())
    say(f"RetroArch: {cl.EXE}; screen {cl.screen_size()}; looks: " + ", ".join(f"{k} {'ok' if p.is_file() else 'MISSING'}" for k, p in LOOKS.items()))
    missing = [k for k, p in LOOKS.items() if not p.is_file()]
    if missing:
        fail(f"looks missing from the player folder: {missing}")
    pads, slots = {}, {}
    for seat, label in zip((1, 2), "AB"):
        pads[seat], slots[seat] = np.plug(label)
    if None in slots.values() or len(set(slots.values())) < 2:
        say("  couldn't read the Xbox slots; assuming A, B = 0, 1")
        slots = {1: 0, 2: 1}

    def run_part(name, fn):
        if ONLY and name not in ONLY:
            return
        try:
            results["parts"].append(fn())
        except Exception as e:  # noqa: BLE001 - one broken part shouldn't hide the others' numbers
            where = traceback.format_exc()
            say(where)
            fail(f"{name}: stopped with {type(e).__name__}: {e}")
            results["parts"].append({"part": name, "error": f"{type(e).__name__}: {e}", "where": where})
            subprocess.run(["taskkill", "/F", "/IM", "retroarch.exe"], capture_output=True)

    run_part("looks", lambda: part_looks(rom, pads[1], slots[1]))
    run_part("couch", lambda: Trio("couch", rom, pads, slots).run())
    results["ok"] = not cl.failures
    results["failures"] = cl.failures
    (OUT / "results.json").write_text(json.dumps(results, indent=2, default=str))
    say("\n================ summary ================")
    say(json.dumps(results, indent=2, default=str)[:60000])
    if cl.failures:
        for f in cl.failures:
            print(f"::error::in-game menu test: {f}", flush=True)
        sys.exit(1)
    say("\nall parts passed")


if __name__ == "__main__":
    main()
