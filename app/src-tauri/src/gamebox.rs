//! Couch Play's game box: the live game shown inside the lobby screen.
//!
//! Measured way ("way B", tools/e2e/couch_lobby_test.py on branch claude/project-thread-6m71fx): RetroArch keeps
//! its own window, without borders, *owned* by Game Night's window (so it stays just above it and hides with it)
//! and placed exactly over the box. Full screen = Game Night resizes that window to cover the monitor; RetroArch's
//! own full screen switch is off (it throws its window away). Game Night follows its own window when it moves
//! or changes size by checking a few times a second.
//!
//! Who gets the controller: the game is live in the box too (the pad reaches RetroArch whatever window is in
//! front; measured). Game Night's window keeps the keyboard focus, so the lobby screen still sees its own
//! buttons (Back/View to leave, Y for full screen). Nothing here blocks RetroArch's input.

use std::sync::{Arc, Mutex};

/// Where a box given in CSS pixels of the window lands on the screen, in screen pixels.
/// `origin`: the top-left of the window's content on the screen; `scale`: the window's scale (DPI / 96).
#[cfg_attr(not(windows), allow(dead_code))]
pub fn screen_rect(origin: (i32, i32), scale: f64, css: (f64, f64, f64, f64)) -> (i32, i32, i32, i32) {
    let s = if scale.is_finite() && scale > 0.0 { scale } else { 1.0 };
    let px = |v: f64| if v.is_finite() { (v * s).round().clamp(-100_000.0, 100_000.0) as i32 } else { 0 };
    let x = origin.0 + px(css.0);
    let y = origin.1 + px(css.1);
    // Right and bottom edges rounded the same way, so neighbouring boxes never leave a 1-pixel gap.
    let w = (origin.0 + px(css.0 + css.2) - x).max(1);
    let h = (origin.1 + px(css.1 + css.3) - y).max(1);
    (x, y, w, h)
}

#[derive(Clone, Debug, Default, PartialEq)]
struct Want {
    /// RetroArch's process; None = no game.
    pid: Option<u32>,
    /// Game Night's main window (Windows HWND as a number).
    main: isize,
    /// The box in CSS pixels; None = not given yet; zero size = hidden.
    rect: Option<(f64, f64, f64, f64)>,
    full: bool,
}

#[derive(Default)]
pub struct GameBox {
    want: Arc<Mutex<Want>>,
    #[cfg_attr(not(windows), allow(dead_code))]
    started: std::sync::atomic::AtomicBool,
}

impl GameBox {
    /// Starts keeping RetroArch (process `pid`) over the box of window `main`.
    pub fn attach(&self, pid: u32, main: isize) {
        {
            let mut w = self.want.lock().unwrap_or_else(|e| e.into_inner());
            w.pid = Some(pid);
            w.main = main;
        }
        #[cfg(windows)]
        {
            let want = self.want.clone();
            if !self.started.swap(true, std::sync::atomic::Ordering::SeqCst) {
                std::thread::spawn(move || win::follow(want));
            }
        }
    }

    pub fn detach(&self) {
        let mut w = self.want.lock().unwrap_or_else(|e| e.into_inner());
        w.pid = None;
        w.full = false;
    }

    pub fn set_box(&self, x: f64, y: f64, w: f64, h: f64) {
        self.want.lock().unwrap_or_else(|e| e.into_inner()).rect = Some((x, y, w, h));
    }

    pub fn set_fullscreen(&self, on: bool) {
        self.want.lock().unwrap_or_else(|e| e.into_inner()).full = on;
    }

    pub fn fullscreen(&self) -> bool {
        self.want.lock().unwrap_or_else(|e| e.into_inner()).full
    }

    /// Where the game window should start (screen pixels), if the box is known; best guess before it's found.
    pub fn start_rect(&self) -> Option<(i32, i32, i32, i32)> {
        #[cfg(windows)]
        {
            let w = self.want.lock().unwrap_or_else(|e| e.into_inner()).clone();
            if w.main != 0 {
                return win::target(&w).map(|t| t.0);
            }
        }
        None
    }
}

#[cfg(windows)]
mod win {
    use super::{screen_rect, Want};
    use std::sync::{Arc, Mutex};
    use std::time::Duration;
    use windows::core::BOOL;
    use windows::Win32::Foundation::{HWND, LPARAM, POINT, RECT};
    use windows::Win32::Graphics::Gdi::{ClientToScreen, GetMonitorInfoW, MonitorFromWindow, MONITORINFO, MONITOR_DEFAULTTONEAREST};
    use windows::Win32::UI::HiDpi::GetDpiForWindow;
    use windows::Win32::UI::WindowsAndMessaging::{
        EnumWindows, GetClassNameW, GetWindowLongPtrW, GetWindowRect, GetWindowThreadProcessId, IsIconic, IsWindow,
        IsWindowVisible, SetWindowLongPtrW, SetWindowPos, ShowWindow, GWLP_HWNDPARENT, GWL_STYLE, HWND_NOTOPMOST,
        HWND_TOPMOST, SWP_FRAMECHANGED, SWP_NOACTIVATE, SWP_NOZORDER, SWP_SHOWWINDOW, SW_HIDE, SW_SHOWNOACTIVATE,
        WS_CAPTION, WS_MAXIMIZEBOX, WS_MINIMIZEBOX, WS_POPUP, WS_SYSMENU, WS_THICKFRAME, WS_VISIBLE,
    };

    fn hwnd(v: isize) -> HWND {
        HWND(v as *mut core::ffi::c_void)
    }

    struct Found {
        pid: u32,
        best: isize,
        area: i64,
        retroarch_class: bool,
    }

    unsafe extern "system" fn each(h: HWND, data: LPARAM) -> BOOL {
        let f = &mut *(data.0 as *mut Found);
        let mut pid = 0u32;
        GetWindowThreadProcessId(h, Some(&mut pid));
        if pid == f.pid && IsWindowVisible(h).as_bool() {
            let mut r = RECT::default();
            let _ = GetWindowRect(h, &mut r);
            let area = (r.right - r.left) as i64 * (r.bottom - r.top) as i64;
            let mut name = [0u16; 64];
            let n = GetClassNameW(h, &mut name).max(0) as usize;
            let is_ra = String::from_utf16_lossy(&name[..n]) == "RetroArch";
            // RetroArch's own game window first, then the biggest.
            if (is_ra, area) > (f.retroarch_class, f.area) {
                f.best = h.0 as isize;
                f.area = area;
                f.retroarch_class = is_ra;
            }
        }
        BOOL(1)
    }

    /// RetroArch's game window, found by its process number.
    fn find(pid: u32) -> Option<isize> {
        let mut f = Found { pid, best: 0, area: -1, retroarch_class: false };
        unsafe {
            let _ = EnumWindows(Some(each), LPARAM(&mut f as *mut Found as isize));
        }
        (f.best != 0).then_some(f.best)
    }

    /// Where the game window should be (screen pixels) and whether it covers the screen; None = hidden/unknown.
    pub(super) fn target(w: &Want) -> Option<((i32, i32, i32, i32), bool)> {
        let main = hwnd(w.main);
        unsafe {
            if w.full {
                let mon = MonitorFromWindow(main, MONITOR_DEFAULTTONEAREST);
                let mut mi = MONITORINFO { cbSize: std::mem::size_of::<MONITORINFO>() as u32, ..Default::default() };
                if GetMonitorInfoW(mon, &mut mi).as_bool() {
                    let r = mi.rcMonitor;
                    return Some(((r.left, r.top, r.right - r.left, r.bottom - r.top), true));
                }
                return None;
            }
            let (x, y, bw, bh) = w.rect?;
            if bw <= 0.0 || bh <= 0.0 {
                return None;
            }
            let mut p = POINT { x: 0, y: 0 };
            if !ClientToScreen(main, &mut p).as_bool() {
                return None;
            }
            let dpi = GetDpiForWindow(main);
            let scale = if dpi == 0 { 1.0 } else { dpi as f64 / 96.0 };
            Some((screen_rect((p.x, p.y), scale, (x, y, bw, bh)), false))
        }
    }

    /// Keeps the game window where it should be, a few times a second. Runs for the whole app.
    pub(super) fn follow(want: Arc<Mutex<Want>>) {
        let mut game: isize = 0; // the game window being kept
        let mut styled: isize = 0; // the window already made borderless and owned
        let mut on_top = false;
        let mut hidden = false;
        loop {
            let w = want.lock().unwrap_or_else(|e| e.into_inner()).clone();
            let Some(pid) = w.pid else {
                game = 0;
                styled = 0;
                on_top = false;
                hidden = false;
                std::thread::sleep(Duration::from_millis(250));
                continue;
            };
            std::thread::sleep(Duration::from_millis(40));
            unsafe {
                if game == 0 || !IsWindow(Some(hwnd(game))).as_bool() {
                    game = find(pid).unwrap_or(0);
                    if game == 0 {
                        std::thread::sleep(Duration::from_millis(100));
                        continue;
                    }
                    // Make sure it's this process's window (a closed one's number can be reused).
                    let mut owner = 0u32;
                    GetWindowThreadProcessId(hwnd(game), Some(&mut owner));
                    if owner != pid {
                        game = 0;
                        continue;
                    }
                }
                let g = hwnd(game);
                let main = hwnd(w.main);
                if w.main == 0 || !IsWindow(Some(main)).as_bool() || IsIconic(main).as_bool() {
                    continue; // owned: it hides along with Game Night's window
                }
                let Some((rect, full)) = target(&w) else {
                    // A zero-size box: out of sight until the box comes back.
                    if w.rect.is_some_and(|r| r.2 <= 0.0 || r.3 <= 0.0) && !w.full && !hidden {
                        let _ = ShowWindow(g, SW_HIDE);
                        hidden = true;
                    }
                    continue;
                };
                if styled != game {
                    let style = GetWindowLongPtrW(g, GWL_STYLE) as u32;
                    let decor = (WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU).0;
                    let new = (style & !decor) | WS_POPUP.0 | WS_VISIBLE.0;
                    SetWindowLongPtrW(g, GWL_STYLE, new as i32 as isize);
                    SetWindowLongPtrW(g, GWLP_HWNDPARENT, w.main);
                    let (x, y, cw, ch) = rect;
                    let _ = SetWindowPos(g, None, x, y, cw, ch, SWP_FRAMECHANGED | SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW);
                    styled = game;
                    hidden = false;
                    on_top = false;
                }
                if hidden {
                    let _ = ShowWindow(g, SW_SHOWNOACTIVATE);
                    hidden = false;
                }
                let mut now = RECT::default();
                let _ = GetWindowRect(g, &mut now);
                let have = (now.left, now.top, now.right - now.left, now.bottom - now.top);
                if have != rect || full != on_top {
                    let (x, y, cw, ch) = rect;
                    let (after, flags) = if full != on_top {
                        (Some(if full { HWND_TOPMOST } else { HWND_NOTOPMOST }), SWP_NOACTIVATE | SWP_SHOWWINDOW)
                    } else {
                        (None, SWP_NOZORDER | SWP_NOACTIVATE)
                    };
                    let _ = SetWindowPos(g, after, x, y, cw, ch, flags);
                    on_top = full;
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn box_to_screen_pixels() {
        assert_eq!(screen_rect((100, 50), 1.0, (10.0, 20.0, 640.0, 480.0)), (110, 70, 640, 480));
        assert_eq!(screen_rect((0, 0), 1.5, (10.0, 20.0, 640.0, 480.0)), (15, 30, 960, 720));
        assert_eq!(screen_rect((-1920, 0), 1.25, (0.5, 0.5, 100.3, 100.3)), (-1919, 1, 125, 125));
        assert_eq!(screen_rect((0, 0), 0.0, (1.0, 2.0, 3.0, 4.0)), (1, 2, 3, 4)); // bad scale: 1
        assert_eq!(screen_rect((0, 0), 1.0, (f64::NAN, 0.0, 0.0, 0.0)), (0, 0, 1, 1));
        let gn = GameBox::default();
        gn.set_fullscreen(true);
        assert!(gn.fullscreen());
        gn.attach(1, 0);
        gn.detach();
        assert!(!gn.fullscreen());
    }
}
