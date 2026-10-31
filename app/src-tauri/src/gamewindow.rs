//! Puts the game in front when it starts, and Game Night back in front when it closes.
//! Every step is written to the player's `window.txt` log (what Windows had in front, and when),
//! so a problem on any PC can be measured rather than guessed.

use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Manager, Runtime};

/// What happened the last time a game started and closed (read by CI's Windows tests).
#[derive(Clone, Default, serde::Serialize)]
pub struct Outcome {
    /// The game's window showed up.
    pub game_window: bool,
    /// Game Night was minimized once the game's window was up.
    pub minimized: bool,
    /// Windows had the game's window in front after Game Night stepped aside.
    pub game_in_front: bool,
    /// Windows had Game Night in front again after the game closed.
    pub back_in_front: bool,
}

pub static LAST: Mutex<Option<Outcome>> = Mutex::new(None);

/// Called just before a game starts: forget the last game's outcome.
pub fn reset() {
    *LAST.lock().unwrap_or_else(|e| e.into_inner()) = Some(Outcome::default());
}

fn record(f: impl FnOnce(&mut Outcome)) {
    let mut last = LAST.lock().unwrap_or_else(|e| e.into_inner());
    f(last.get_or_insert_with(Outcome::default));
}

/// One timestamped line in the log.
pub struct Log {
    file: PathBuf,
    t0: Instant,
}

impl Log {
    pub fn new(logs: &Path) -> Self {
        let file = logs.join("window.txt");
        let _ = std::fs::remove_file(&file);
        Log { file, t0: Instant::now() }
    }
    pub fn note(&self, line: &str) {
        if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(&self.file) {
            let _ = writeln!(f, "{:>6} ms  {line}", self.t0.elapsed().as_millis());
        }
    }
}

/// Runs on its own thread right after the game starts. Waits (up to 20 s) for the game's window,
/// makes sure it's in front, then minimizes Game Night. If the game closed meanwhile, Game Night is
/// brought straight back, so it's never left minimized with no game running.
pub fn game_started<R: Runtime>(app: &AppHandle<R>, log: &Log, pid: u32, still_playing: impl Fn() -> bool) {
    log.note(&format!("game started (process {pid}); in front: {}", front()));
    let start = Instant::now();
    let game = loop {
        if let Some(w) = os::game_window(pid) {
            break Some(w);
        }
        if start.elapsed() > Duration::from_secs(20) || !still_playing() {
            break None;
        }
        std::thread::sleep(Duration::from_millis(100));
    };
    let Some(game) = game else {
        log.note("the game's window never showed up (or the game closed first): Game Night stays as it is");
        return;
    };
    record(|o| o.game_window = true);
    log.note(&format!("game window up after {} ms; in front: {}", start.elapsed().as_millis(), front()));
    // While Game Night is still in front, Windows lets it hand the front to the game.
    if !os::is_front(game) {
        let ok = os::bring_to_front(game);
        log.note(&format!("asked Windows to put the game in front: {}", if ok { "yes" } else { "refused" }));
    }
    let main = app.get_webview_window("main");
    if let Some(w) = &main {
        let _ = w.minimize();
    }
    std::thread::sleep(Duration::from_millis(300));
    if !still_playing() {
        // The game closed while Game Night was stepping aside: undo it.
        if let Some(w) = &main {
            let _ = w.unminimize();
            let _ = w.set_focus();
        }
        log.note("the game closed while Game Night was minimizing: brought Game Night back");
        return;
    }
    let minimized = main.as_ref().and_then(|w| w.is_minimized().ok()).unwrap_or(false);
    record(|o| o.minimized = minimized);
    log.note(&format!("Game Night minimized: {}", if minimized { "yes" } else { "NO" }));
    std::thread::sleep(Duration::from_millis(700));
    // By process, not window: RetroArch may swap its window when it goes fullscreen.
    let in_front = os::process_in_front(pid);
    record(|o| o.game_in_front = in_front);
    log.note(&format!("1 s later, in front: {} (the game: {})", front(), if in_front { "yes" } else { "NO" }));
}

/// After the game closes: Game Night comes back and is put in front.
pub fn game_closed<R: Runtime>(app: &AppHandle<R>, log: &Log) {
    log.note(&format!("game closed; in front: {}", front()));
    let Some(w) = app.get_webview_window("main") else { return };
    let _ = w.unminimize();
    let _ = w.set_focus();
    std::thread::sleep(Duration::from_millis(500));
    let mut back = os::own_window_in_front();
    if !back {
        // Windows sometimes refuses the first ask (the game was in front, not Game Night). Try once more.
        let _ = w.set_focus();
        std::thread::sleep(Duration::from_millis(500));
        back = os::own_window_in_front();
    }
    record(|o| o.back_in_front = back);
    log.note(&format!("Game Night restored; in front: {} (Game Night: {})", front(), if back { "yes" } else { "NO" }));
}

/// The window in front, as "title" (process N), for the log.
fn front() -> String {
    os::front()
}

#[cfg_attr(not(windows), allow(dead_code))]
/// Where the game's window is on the screen (x, y, width, height), for the in-game menu to cover it.
pub fn window_rect(pid: u32) -> Option<(i32, i32, u32, u32)> {
    os::game_window(pid).and_then(os::rect)
}

/// Puts the game's window in front again (after the in-game menu closes).
pub fn focus_game(pid: u32) -> bool {
    os::game_window(pid).map(os::bring_to_front).unwrap_or(false)
}

#[cfg(windows)]
mod os {
    use windows::core::BOOL;
    use windows::Win32::Foundation::{HWND, LPARAM};
    use windows::Win32::UI::WindowsAndMessaging::{
        EnumWindows, GetForegroundWindow, GetWindow, GetWindowTextW, GetWindowThreadProcessId, IsWindowVisible,
        SetForegroundWindow, GW_OWNER,
    };

    fn pid_of(w: HWND) -> u32 {
        let mut pid = 0u32;
        unsafe { GetWindowThreadProcessId(w, Some(&mut pid as *mut u32)) };
        pid
    }

    struct Find {
        pid: u32,
        found: Option<HWND>,
    }

    unsafe extern "system" fn each(w: HWND, data: LPARAM) -> BOOL {
        let f = &mut *(data.0 as *mut Find);
        // A visible top-level window (not a tool or helper window owned by another) of the game's process.
        let owned = GetWindow(w, GW_OWNER).map(|o| !o.is_invalid()).unwrap_or(false);
        if pid_of(w) == f.pid && IsWindowVisible(w).as_bool() && !owned {
            f.found = Some(w);
            return BOOL(0);
        }
        BOOL(1)
    }

    /// The game's main window, once it's on screen. Window handles are passed around as numbers so the
    /// caller's thread doesn't matter.
    pub fn game_window(pid: u32) -> Option<isize> {
        let mut f = Find { pid, found: None };
        unsafe {
            let _ = EnumWindows(Some(each), LPARAM(&mut f as *mut Find as isize));
        }
        f.found.map(|w| w.0 as isize)
    }

    pub fn is_front(w: isize) -> bool {
        unsafe { GetForegroundWindow().0 as isize == w }
    }

    pub fn rect(w: isize) -> Option<(i32, i32, u32, u32)> {
        let mut r = windows::Win32::Foundation::RECT::default();
        unsafe { windows::Win32::UI::WindowsAndMessaging::GetWindowRect(HWND(w as *mut _), &mut r) }.ok()?;
        let (cw, ch) = (r.right - r.left, r.bottom - r.top);
        (cw > 0 && ch > 0).then_some((r.left, r.top, cw as u32, ch as u32))
    }

    pub fn bring_to_front(w: isize) -> bool {
        unsafe { SetForegroundWindow(HWND(w as *mut _)).as_bool() }
    }

    pub fn process_in_front(pid: u32) -> bool {
        let w = unsafe { GetForegroundWindow() };
        !w.is_invalid() && pid_of(w) == pid
    }

    pub fn own_window_in_front() -> bool {
        process_in_front(std::process::id())
    }

    pub fn front() -> String {
        let w = unsafe { GetForegroundWindow() };
        if w.is_invalid() {
            return "nothing".into();
        }
        let mut buf = [0u16; 128];
        let n = unsafe { GetWindowTextW(w, &mut buf) }.max(0) as usize;
        let who = if pid_of(w) == std::process::id() { " = Game Night" } else { "" };
        format!("\"{}\" (process {}{who})", String::from_utf16_lossy(&buf[..n]), pid_of(w))
    }
}

#[cfg(not(windows))]
mod os {
    pub fn game_window(_pid: u32) -> Option<isize> {
        None
    }
    pub fn is_front(_w: isize) -> bool {
        false
    }
    #[allow(dead_code)]
    pub fn rect(_w: isize) -> Option<(i32, i32, u32, u32)> {
        None
    }
    pub fn bring_to_front(_w: isize) -> bool {
        false
    }
    pub fn process_in_front(_pid: u32) -> bool {
        false
    }
    pub fn own_window_in_front() -> bool {
        false
    }
    pub fn front() -> String {
        "unknown (not Windows)".into()
    }
}
