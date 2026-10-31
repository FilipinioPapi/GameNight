"""CI only (Windows): watches where the Couch Play game window really is, many times a second, so a flicker,
a wrong size or a window outside the box is measured instead of guessed. Used by couch_app_test.py.

All numbers are screen pixels (this process asks Windows for real pixels, not scaled ones).
"""
import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2: real pixels
except (AttributeError, OSError):
    pass

ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.GetParent.restype = wintypes.HWND
user32.GetMenu.restype = wintypes.HMENU


def _rect(h):
    r = wintypes.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def _client(h):
    """The inside of a window, in screen pixels."""
    r = wintypes.RECT()
    user32.GetClientRect(h, ctypes.byref(r))
    p = wintypes.POINT(0, 0)
    user32.ClientToScreen(h, ctypes.byref(p))
    return (p.x, p.y, r.right - r.left, r.bottom - r.top)


def _class(h):
    b = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(h, b, 64)
    return b.value


def _pid(h):
    p = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(p))
    return p.value


def _tops():
    out = []
    user32.EnumWindows(ENUM(lambda h, _: out.append(h) or True), 0)
    return out


def _children(h):
    out = []
    user32.EnumChildWindows(h, ENUM(lambda c, _: out.append(c) or True), 0)
    return out


def main_window(pid):
    """Game Night's main window: its biggest visible top-level window."""
    best, area = None, -1
    for h in _tops():
        if _pid(h) == pid and user32.IsWindowVisible(h):
            x, y, w, hh = _rect(h)
            if w * hh > area:
                best, area = h, w * hh
    return best


def game_window(main):
    """RetroArch's window: a child of Game Night's window, or (if it wasn't adopted) a window of its own."""
    for c in _children(main) if main else []:
        if _class(c) == "RetroArch":
            return c, True
    for h in _tops():
        if _class(h) == "RetroArch" and user32.IsWindowVisible(h):
            return h, False
    return None, False


def watch(app_pid, seconds, hz=25):
    """Samples the game window's place for `seconds`. Returns a summary and the samples."""
    samples, t0 = [], time.time()
    while time.time() - t0 < seconds:
        main = main_window(app_pid)
        g, child = game_window(main)
        samples.append({
            "t": round(time.time() - t0, 3),
            "game": _rect(g) if g else None,
            "child": child,
            "visible": bool(g and user32.IsWindowVisible(g)),
            "menu_bar": bool(g and user32.GetMenu(g)),
            "app_inside": _client(main) if main else None,
            "app_full_screen": bool(main and _rect(main)[2] >= user32.GetSystemMetrics(0) and _rect(main)[3] >= user32.GetSystemMetrics(1)),
        })
        time.sleep(1 / hz)
    places = [s["game"] for s in samples]
    changes = sum(1 for a, b in zip(places, places[1:]) if a != b)
    last = samples[-1] if samples else {}
    inside = None
    if last.get("game") and last.get("app_inside"):
        gx, gy, gw, gh = last["game"]
        ax, ay, aw, ah = last["app_inside"]
        inside = gx >= ax and gy >= ay and gx + gw <= ax + aw and gy + gh <= ay + ah
    summary = {
        "samples": len(samples),
        "place_changes": changes,
        "different_places": len({p for p in places}),
        "always_child": all(s["child"] for s in samples) if samples else False,
        "ever_hidden": any(not s["visible"] for s in samples),
        "ever_menu_bar": any(s["menu_bar"] for s in samples),
        "last_game": last.get("game"),
        "last_app_inside": last.get("app_inside"),
        "app_full_screen": last.get("app_full_screen"),
        "game_inside_app": inside,
        "screen": (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)),
    }
    return summary, samples


def move_app(app_pid, x, y, w, h):
    """Moves and resizes Game Night's window (only used when it's a window, not full screen)."""
    main = main_window(app_pid)
    if main:
        user32.ShowWindow(main, 9)  # restore
        user32.SetWindowPos(main, None, x, y, w, h, 0x0004 | 0x0010)  # no z-order change, no activate
    return main is not None


def front_is_app(app_pid):
    return _pid(user32.GetForegroundWindow()) == app_pid


def focus_app(app_pid):
    """Puts Game Night in front (as a player would by clicking it): a click on an empty spot near the bottom
    of its window. Game Night only listens to the pad while it's the window in front."""
    main = main_window(app_pid)
    if not main:
        return False
    user32.SetForegroundWindow(main)
    time.sleep(0.3)
    if not front_is_app(app_pid):
        x, y, w, h = _client(main)
        user32.SetCursorPos(x + w // 2, y + h - 40)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # left up
        time.sleep(0.3)
    return front_is_app(app_pid)
