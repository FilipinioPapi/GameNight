//! Couch Play's game box: the live game shown inside the lobby screen.
//!
//! The game lives inside Game Night's window: RetroArch's window, without borders or menu bar, becomes a *child*
//! of Game Night's window (measured as "way A" in tools/e2e/couch_lobby_test.py) placed exactly over the box. It
//! moves, hides and closes with Game Night, and can't sit over the seat list or another app. Full screen = the
//! game fills Game Night's window (Game Night itself goes full screen too, see couch.rs). RetroArch's own full
//! screen switch is off (it throws its window away), and RetroArch always opens at the box's size, never a size
//! of its own (its own size fought the box: 0.3.5 flickered on Jayden's PC). gamebox.log records every move.
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

/// gamebox.log in the player logs folder: where the game window was asked to go and where it really was,
/// so a flicker or a wrong size can be measured on any PC. Nothing private in it.
#[derive(Clone, Default)]
pub struct BoxLog {
    path: Option<std::path::PathBuf>,
    t0: Option<std::time::Instant>,
}

impl BoxLog {
    pub fn new(path: Option<std::path::PathBuf>) -> BoxLog {
        if let Some(p) = &path {
            if let Some(d) = p.parent() {
                let _ = std::fs::create_dir_all(d);
            }
            let _ = std::fs::write(p, "");
        }
        BoxLog { path, t0: Some(std::time::Instant::now()) }
    }
    #[cfg_attr(not(windows), allow(dead_code))]
    pub fn line(&self, s: &str) {
        use std::io::Write;
        let (Some(p), Some(t0)) = (&self.path, self.t0) else { return };
        if let Ok(mut f) = std::fs::OpenOptions::new().append(true).create(true).open(p) {
            let _ = writeln!(f, "[{:8.2} s] {s}", t0.elapsed().as_secs_f64());
        }
    }
}

#[derive(Default)]
pub struct GameBox {
    want: Arc<Mutex<Want>>,
    log: Arc<Mutex<BoxLog>>,
    #[cfg_attr(not(windows), allow(dead_code))]
    started: std::sync::atomic::AtomicBool,
}

impl GameBox {
    /// Starts keeping RetroArch (process `pid`) over the box of window `main`.
    pub fn attach(&self, pid: u32, main: isize, log: BoxLog) {
        *self.log.lock().unwrap_or_else(|e| e.into_inner()) = log;
        {
            let mut w = self.want.lock().unwrap_or_else(|e| e.into_inner());
            w.pid = Some(pid);
            w.main = main;
        }
        #[cfg(windows)]
        {
            let want = self.want.clone();
            let log = self.log.clone();
            if !self.started.swap(true, std::sync::atomic::Ordering::SeqCst) {
                std::thread::spawn(move || win::follow(want, log));
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

    /// Where RetroArch should open its window (screen pixels): over the box if it's known, otherwise over all
    /// of Game Night's window `main`. Never left to RetroArch, which would pick a size of its own.
    pub fn start_rect(&self, main: isize) -> Option<(i32, i32, i32, i32)> {
        #[cfg(windows)]
        {
            let mut w = self.want.lock().unwrap_or_else(|e| e.into_inner()).clone();
            w.main = main;
            if main != 0 {
                return win::start(&w);
            }
        }
        let _ = main;
        None
    }
}

#[cfg(windows)]
mod win {
    use super::{screen_rect, BoxLog, Want};
    use std::sync::{Arc, Mutex};
    use std::time::Duration;
    use windows::core::BOOL;
    use windows::Win32::Foundation::{HWND, LPARAM, POINT, RECT};
    use windows::Win32::Graphics::Gdi::{ClientToScreen, ScreenToClient};
    use windows::Win32::UI::HiDpi::GetDpiForWindow;
    use windows::Win32::UI::WindowsAndMessaging::{
        EnumWindows, GetClassNameW, GetClientRect, GetParent, GetWindowLongPtrW, GetWindowRect, GetWindowThreadProcessId,
        IsIconic, IsWindow, IsWindowVisible, SetParent, SetWindowLongPtrW, SetWindowPos, ShowWindow, GWL_STYLE, HWND_TOP,
        SWP_FRAMECHANGED, SWP_NOACTIVATE, SWP_SHOWWINDOW, SW_HIDE, SW_SHOWNOACTIVATE, WS_CAPTION, WS_CHILD,
        WS_CLIPSIBLINGS, WS_MAXIMIZEBOX, WS_MINIMIZEBOX, WS_POPUP, WS_SYSMENU, WS_THICKFRAME, WS_VISIBLE,
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

    /// RetroArch's game window (still a window of its own), found by its process number.
    fn find(pid: u32) -> Option<isize> {
        let mut f = Found { pid, best: 0, area: -1, retroarch_class: false };
        unsafe {
            let _ = EnumWindows(Some(each), LPARAM(&mut f as *mut Found as isize));
        }
        (f.best != 0).then_some(f.best)
    }

    /// Where the game should be, in pixels inside Game Night's window, and whether that's the whole window.
    /// None = hidden or not known yet.
    pub(super) fn target(w: &Want) -> Option<((i32, i32, i32, i32), bool)> {
        let main = hwnd(w.main);
        unsafe {
            if w.full {
                let mut c = RECT::default();
                GetClientRect(main, &mut c).ok()?;
                return Some(((0, 0, c.right - c.left, c.bottom - c.top), true));
            }
            let (x, y, bw, bh) = w.rect?;
            if bw <= 0.0 || bh <= 0.0 {
                return None;
            }
            let dpi = GetDpiForWindow(main);
            let scale = if dpi == 0 { 1.0 } else { dpi as f64 / 96.0 };
            Some((screen_rect((0, 0), scale, (x, y, bw, bh)), false))
        }
    }

    /// Where RetroArch should open its window (screen pixels) before it's moved inside Game Night: the box if
    /// it's known, otherwise all of Game Night's window. RetroArch then never opens at a size of its own.
    pub(super) fn start(w: &Want) -> Option<(i32, i32, i32, i32)> {
        let main = hwnd(w.main);
        let inside = target(w).map(|t| t.0).or_else(|| unsafe {
            let mut c = RECT::default();
            GetClientRect(main, &mut c).ok()?;
            Some((0, 0, c.right - c.left, c.bottom - c.top))
        })?;
        let mut p = POINT { x: inside.0, y: inside.1 };
        unsafe { ClientToScreen(main, &mut p).as_bool() }.then_some((p.x, p.y, inside.2, inside.3))
    }

    /// The game window's place inside Game Night's window.
    unsafe fn place_of(g: HWND, main: HWND) -> (i32, i32, i32, i32) {
        let mut r = RECT::default();
        let _ = GetWindowRect(g, &mut r);
        let mut p = POINT { x: r.left, y: r.top };
        let _ = ScreenToClient(main, &mut p);
        (p.x, p.y, r.right - r.left, r.bottom - r.top)
    }

    /// Keeps the game inside Game Night's window, over the box (or filling the window), a few times a second.
    /// The game window becomes a child of Game Night's window: it moves, hides and closes with it, and can
    /// never sit over another app or the seat list.
    pub(super) fn follow(want: Arc<Mutex<Want>>, log: Arc<Mutex<BoxLog>>) {
        let say = |s: &str| log.lock().unwrap_or_else(|e| e.into_inner()).line(s);
        let mut moves: u64 = 0; // times the game window had to be put back
        let mut last_want: Option<(Option<(f64, f64, f64, f64)>, bool)> = None;
        let mut game: isize = 0; // the game window being kept
        let mut adopted: isize = 0; // the window already made a child of Game Night's window
        let mut hidden = false;
        loop {
            let w = want.lock().unwrap_or_else(|e| e.into_inner()).clone();
            let Some(pid) = w.pid else {
                game = 0;
                adopted = 0;
                hidden = false;
                last_want = None;
                std::thread::sleep(Duration::from_millis(250));
                continue;
            };
            std::thread::sleep(Duration::from_millis(40));
            unsafe {
                let main = hwnd(w.main);
                if w.main == 0 || !IsWindow(Some(main)).as_bool() {
                    continue;
                }
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
                    let mut r = RECT::default();
                    let _ = GetWindowRect(hwnd(game), &mut r);
                    moves = 0;
                    say(&format!(
                        "found the game window: at {},{} size {}x{}, its scale {}%, Game Night's scale {}%",
                        r.left, r.top, r.right - r.left, r.bottom - r.top,
                        GetDpiForWindow(hwnd(game)) * 100 / 96, GetDpiForWindow(main) * 100 / 96
                    ));
                }
                let g = hwnd(game);
                if IsIconic(main).as_bool() {
                    continue; // a child: it's out of sight along with Game Night's window
                }
                if last_want != Some((w.rect, w.full)) {
                    last_want = Some((w.rect, w.full));
                    say(&format!(
                        "asked: box {:?} (window pixels), full screen {}; Game Night's scale {}% -> {:?}",
                        w.rect, w.full, GetDpiForWindow(main) * 100 / 96, target(&w)
                    ));
                }
                let Some((rect, full)) = target(&w) else {
                    // A zero-size box: out of sight until the box comes back.
                    if adopted == game && w.rect.is_some_and(|r| r.2 <= 0.0 || r.3 <= 0.0) && !w.full && !hidden {
                        let _ = ShowWindow(g, SW_HIDE);
                        hidden = true;
                        say("hidden (a panel covers the box)");
                    }
                    continue;
                };
                let (x, y, cw, ch) = rect;
                if adopted != game {
                    // Borderless child window, with no menu bar, drawn only in its own place.
                    let style = GetWindowLongPtrW(g, GWL_STYLE) as u32;
                    let decor = (WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU | WS_POPUP).0;
                    let new = (style & !decor) | WS_CHILD.0 | WS_CLIPSIBLINGS.0 | WS_VISIBLE.0;
                    SetWindowLongPtrW(g, GWL_STYLE, new as i32 as isize);
                    let _ = SetParent(g, Some(main));
                    let _ = SetWindowPos(g, Some(HWND_TOP), x, y, cw, ch, SWP_FRAMECHANGED | SWP_NOACTIVATE | SWP_SHOWWINDOW);
                    adopted = game;
                    hidden = false;
                    let parent_ok = GetParent(g).map(|p| p == main).unwrap_or(false);
                    say(&format!("moved inside Game Night's window (child: {parent_ok}), placed at {rect:?}"));
                    continue;
                }
                if hidden {
                    let _ = ShowWindow(g, SW_SHOWNOACTIVATE);
                    let _ = SetWindowPos(g, Some(HWND_TOP), x, y, cw, ch, SWP_NOACTIVATE);
                    hidden = false;
                    say(&format!("shown again at {rect:?}"));
                    continue;
                }
                let have = place_of(g, main);
                if have != rect {
                    moves += 1;
                    // Every move at first, then now and then: a window being put back over and over is a flicker.
                    if moves <= 20 || moves % 100 == 0 {
                        say(&format!("move #{moves}: it was at {have:?}, putting it at {rect:?}{}", if full { " (full screen)" } else { "" }));
                    }
                    let _ = SetWindowPos(g, Some(HWND_TOP), x, y, cw, ch, SWP_NOACTIVATE);
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
        gn.attach(1, 0, BoxLog::default());
        gn.detach();
        assert!(!gn.fullscreen());
    }
}
