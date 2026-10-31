//! Game Night's own in-game menu (boards IG2 and IG3, approved 2026-10-31).
//!
//! - The Xbox / PS button, or holding both stick clicks (L3 + R3) for 1 second, opens it while a game runs
//!   (pads.rs spots the press, even while the game is the window in front). Never Start + Select: Windows and
//!   Steam use it for their own shortcuts.
//! - The menu is a see-through window of its own ("menu", menu.html) laid over the game.
//! - While it's open, RetroArch's own menu is open too, hidden (fully see-through, nothing on it to pick:
//!   display.rs), which stops your presses reaching the game (measured on GitHub's Windows machine). On your own
//!   it also pauses the game; in Couch Play the game keeps going for everyone else.
//! - Players never see RetroArch's menus: Game Night writes RetroArch's settings fresh for every game.
//! - ingame.txt in the player logs folder notes every open, close and action, so a problem can be measured.

#![cfg_attr(not(windows), allow(dead_code))]

use serde::Serialize;
use serde_json::{json, Value};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager, Runtime};

/// A game started on its own (not Couch Play).
#[derive(Clone, Debug)]
pub struct Solo {
    pub pid: u32,
    pub cmd_port: u16,
    pub title: String,
    pub console: String,
    pub look: String,
    pub player: PathBuf,
}

static SOLO: Mutex<Option<Solo>> = Mutex::new(None);
static OPEN: AtomicBool = AtomicBool::new(false);
/// When the menu was last opened or closed by a button (see `toggle`).
static LAST_TOGGLE: Mutex<Option<Instant>> = Mutex::new(None);
static LOG: Mutex<Option<(PathBuf, Instant)>> = Mutex::new(None);

fn lock<T>(m: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

pub fn note<R: Runtime>(app: &AppHandle<R>, line: &str) {
    use std::io::Write;
    let mut g = lock(&LOG);
    if g.is_none() {
        if let Ok(d) = app.path().app_cache_dir() {
            let p = d.join("player").join("logs").join("ingame.txt");
            if let Some(dir) = p.parent() {
                let _ = std::fs::create_dir_all(dir);
            }
            let _ = std::fs::write(&p, "");
            *g = Some((p, Instant::now()));
        }
    }
    if let Some((p, t0)) = g.as_ref() {
        if let Ok(mut f) = std::fs::OpenOptions::new().append(true).create(true).open(p) {
            let _ = writeln!(f, "[{:8.2} s] {line}", t0.elapsed().as_secs_f64());
        }
    }
}

/// Sends a command to the local RetroArch (this PC only).
pub fn send_cmd(port: u16, cmd: &str) {
    if port == 0 {
        return;
    }
    if let Ok(s) = std::net::UdpSocket::bind(("127.0.0.1", 0)) {
        let _ = s.send_to(cmd.as_bytes(), ("127.0.0.1", port));
    }
}

/// A free local port for RetroArch's command port.
pub fn free_port() -> u16 {
    std::net::UdpSocket::bind(("127.0.0.1", 0)).ok().and_then(|s| s.local_addr().ok()).map(|a| a.port()).unwrap_or(0)
}

// ---------------------------------------------------------------- which game is running

/// Called by games.rs once a game on your own has started.
pub fn solo_started<R: Runtime>(app: &AppHandle<R>, game: Solo) {
    note(app, &format!("game started on its own: {} ({}), process {}, command port {}", game.title, game.console, game.pid, game.cmd_port));
    *lock(&SOLO) = Some(game);
}

/// Called by games.rs once a game on your own has closed.
pub fn solo_ended<R: Runtime>(app: &AppHandle<R>) {
    *lock(&SOLO) = None;
    if OPEN.load(Ordering::SeqCst) {
        close(app, "the game closed");
    }
}

/// What the menu needs to know about the game that's running.
enum Playing {
    Solo(Solo),
    Couch(crate::couch::MenuContext),
}

fn playing<R: Runtime>(app: &AppHandle<R>) -> Option<Playing> {
    if let Some(s) = lock(&SOLO).clone() {
        return Some(Playing::Solo(s));
    }
    crate::couch::menu_context(app).filter(|c| c.running).map(Playing::Couch)
}

/// A game is running, so the Xbox / PS button means "open the menu".
pub fn active<R: Runtime>(app: &AppHandle<R>) -> bool {
    lock(&SOLO).is_some() || crate::couch::menu_context(app).is_some_and(|c| c.running)
}

pub fn is_open() -> bool {
    OPEN.load(Ordering::SeqCst)
}

fn cmd_port(p: &Playing) -> u16 {
    match p {
        Playing::Solo(s) => s.cmd_port,
        Playing::Couch(c) => c.cmd_port,
    }
}

// ---------------------------------------------------------------- the menu window

#[derive(Serialize, Clone)]
pub struct MenuInfo {
    pub open: bool,
    /// "solo" or "couch".
    pub mode: &'static str,
    pub title: String,
    pub console: String,
    /// The look (shader) on this screen now.
    pub look: String,
    pub host: bool,
    pub watching: bool,
    pub fullscreen: bool,
    /// The lobby as the lobby screen sees it (Couch Play only).
    pub lobby: Value,
}

fn info<R: Runtime>(app: &AppHandle<R>) -> Option<MenuInfo> {
    let open = is_open();
    Some(match playing(app)? {
        Playing::Solo(s) => MenuInfo {
            open,
            mode: "solo",
            title: s.title,
            console: s.console,
            look: s.look,
            host: true,
            watching: false,
            fullscreen: true,
            lobby: Value::Null,
        },
        Playing::Couch(c) => MenuInfo {
            open,
            mode: "couch",
            title: c.title,
            console: c.console,
            look: c.look,
            host: c.host,
            watching: c.watching,
            fullscreen: c.fullscreen,
            lobby: c.view,
        },
    })
}

/// Where the menu goes, in screen pixels: over the game's own window on your own, over Game Night's window in Couch Play.
fn place<R: Runtime>(app: &AppHandle<R>, p: &Playing) -> Option<(i32, i32, u32, u32)> {
    let main = app.get_webview_window("main");
    if let Playing::Solo(s) = p {
        if let Some(r) = crate::gamewindow::window_rect(s.pid) {
            return Some(r);
        }
        // Not found: the whole screen Game Night is on.
        let m = main.as_ref().and_then(|w| w.current_monitor().ok().flatten()).or_else(|| app.primary_monitor().ok().flatten())?;
        return Some((m.position().x, m.position().y, m.size().width, m.size().height));
    }
    let w = main?;
    let pos = w.inner_position().ok()?;
    let size = w.inner_size().ok()?;
    Some((pos.x, pos.y, size.width, size.height))
}

const LABEL: &str = "menu";

/// The menu window, made once (hidden) the first time it's needed.
fn window<R: Runtime>(app: &AppHandle<R>) -> Option<tauri::WebviewWindow<R>> {
    if let Some(w) = app.get_webview_window(LABEL) {
        return Some(w);
    }
    let built = tauri::WebviewWindowBuilder::new(app, LABEL, tauri::WebviewUrl::App("menu.html".into()))
        .title("Game Night menu")
        .decorations(false)
        .transparent(true)
        .background_color(tauri::window::Color(0, 0, 0, 0))
        .shadow(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .resizable(false)
        .focused(false)
        .visible(false)
        .build();
    match built {
        Ok(w) => {
            note(app, "made the menu window");
            Some(w)
        }
        Err(e) => {
            note(app, &format!("couldn't make the menu window: {e}"));
            None
        }
    }
}

/// Makes the menu window ahead of time (when a game starts), so the first open is quick.
pub fn prepare<R: Runtime>(app: &AppHandle<R>) {
    let app = app.clone();
    std::thread::spawn(move || {
        let _ = window(&app);
    });
}

fn emit_state<R: Runtime>(app: &AppHandle<R>) {
    let v = info(app).map(|i| serde_json::to_value(i).unwrap_or(Value::Null)).unwrap_or(json!({ "open": false }));
    let _ = app.emit("ingame-menu", v);
}

/// The Xbox / PS button or L3 + R3 (pads.rs). Presses that come in too quickly after each other (one press
/// seen through two ways of reading the pad) count once.
pub fn toggle<R: Runtime>(app: &AppHandle<R>, why: &str) {
    {
        let mut last = lock(&LAST_TOGGLE);
        if last.is_some_and(|t| t.elapsed() < Duration::from_millis(450)) {
            return;
        }
        *last = Some(Instant::now());
    }
    let app = app.clone();
    let why = why.to_string();
    std::thread::spawn(move || {
        if is_open() {
            close(&app, &why);
        } else {
            open(&app, &why);
        }
    });
}

pub fn open<R: Runtime>(app: &AppHandle<R>, why: &str) {
    let Some(p) = playing(app) else {
        note(app, &format!("{why}: no game running, menu not opened"));
        return;
    };
    let Some(w) = window(app) else { return };
    if OPEN.swap(true, Ordering::SeqCst) {
        return;
    }
    // Your presses stop reaching the game (and on your own the game pauses).
    send_cmd(cmd_port(&p), "MENU_TOGGLE");
    if let Some((x, y, cw, ch)) = place(app, &p) {
        let _ = w.set_position(tauri::PhysicalPosition::new(x, y));
        let _ = w.set_size(tauri::PhysicalSize::new(cw.max(200), ch.max(200)));
    }
    emit_state(app);
    let _ = w.show();
    let _ = w.set_always_on_top(true);
    // Keyboard and mouse work in the menu once it's in front. Windows may say no while the game is in front;
    // the controller works either way.
    let focused = w.set_focus().is_ok();
    note(app, &format!("menu opened ({why}); {}; focus asked: {focused}", if matches!(p, Playing::Solo(_)) { "on your own" } else { "Couch Play" }));
}

pub fn close<R: Runtime>(app: &AppHandle<R>, why: &str) {
    if !OPEN.swap(false, Ordering::SeqCst) {
        return;
    }
    let p = playing(app);
    if let Some(p) = &p {
        send_cmd(cmd_port(p), "MENU_TOGGLE");
    }
    // Still paused for everyone: the window stays, showing "Paused by ..." (board IG3).
    let paused = matches!(&p, Some(Playing::Couch(c)) if c.view.get("paused").is_some_and(Value::is_object));
    PAUSE_SHOWN.store(paused, Ordering::SeqCst);
    if !paused {
        if let Some(w) = app.get_webview_window(LABEL) {
            let _ = w.hide();
        }
    }
    emit_state(app);
    // Back to the game: on your own the game's window goes in front again; in Couch Play, Game Night's.
    match &p {
        Some(Playing::Solo(s)) => {
            let ok = crate::gamewindow::focus_game(s.pid);
            note(app, &format!("menu closed ({why}); game window put in front: {ok}"));
        }
        _ => {
            if let Some(m) = app.get_webview_window("main") {
                let _ = m.set_focus();
            }
            note(app, &format!("menu closed ({why})"));
        }
    }
}

/// Once a second from pads.rs: close the menu if the game stopped.
pub fn check<R: Runtime>(app: &AppHandle<R>) {
    if is_open() && !active(app) {
        close(app, "the game isn't running any more");
    }
    if PAUSE_SHOWN.load(Ordering::SeqCst) {
        lobby_changed(app);
    }
}

/// The "Paused by" screen (board IG3) is showing over the game.
static PAUSE_SHOWN: AtomicBool = AtomicBool::new(false);

/// Couch Play: the lobby changed (pause, seats). The menu shows the new lobby, and while someone has paused the
/// game for everyone (and your menu is closed) the same window shows "Paused by ..." over the game.
pub fn lobby_changed<R: Runtime>(app: &AppHandle<R>) {
    let ctx = crate::couch::menu_context(app);
    let paused = ctx.as_ref().is_some_and(|c| c.running && c.view.get("paused").is_some_and(Value::is_object));
    if is_open() {
        emit_state(app);
        return;
    }
    if paused {
        let Some(w) = window(app) else { return };
        emit_state(app);
        if !PAUSE_SHOWN.swap(true, Ordering::SeqCst) {
            if let Some((x, y, cw, ch)) = ctx.map(Playing::Couch).and_then(|p| place(app, &p)) {
                let _ = w.set_position(tauri::PhysicalPosition::new(x, y));
                let _ = w.set_size(tauri::PhysicalSize::new(cw.max(200), ch.max(200)));
            }
            let _ = w.show();
            note(app, "showing \"Paused by\" over the game");
        }
    } else if PAUSE_SHOWN.swap(false, Ordering::SeqCst) {
        emit_state(app);
        if let Some(w) = app.get_webview_window(LABEL) {
            let _ = w.hide();
        }
        note(app, "\"Paused by\" gone (the game carries on)");
    }
}

// ---------------------------------------------------------------- what the menu asks for

#[tauri::command]
pub fn ingame_info<R: Runtime>(app: AppHandle<R>) -> Option<MenuInfo> {
    info(&app)
}

#[tauri::command]
pub fn ingame_close<R: Runtime>(app: AppHandle<R>) {
    close(&app, "menu: back to the game");
}

/// A line from the menu page for ingame.txt (what it showed and did), kept short and plain.
#[tauri::command]
pub fn ingame_note<R: Runtime>(app: AppHandle<R>, text: String) {
    let clean: String = text.chars().filter(|c| !c.is_control()).take(200).collect();
    note(&app, &format!("menu page: {clean}"));
}

/// The looks the menu can switch between (display.rs names).
const LOOKS: &[&str] = &["sharp", "scanlines", "lottes", "lottesfast", "geom", "easymode", "royale", "hyllian", "sharpsmooth", "xbr", "scalefx", "hq4x"];

/// One thing picked in the menu. Answers with the menu's new state.
#[tauri::command]
pub async fn ingame_do<R: Runtime>(app: AppHandle<R>, action: String, value: Option<String>) -> Result<Option<MenuInfo>, String> {
    let p = playing(&app).ok_or("The game isn't running.")?;
    note(&app, &format!("action {action} {}", value.as_deref().unwrap_or("")));
    let port = cmd_port(&p);
    match (action.as_str(), &p) {
        ("resume", _) => close(&app, "Resume"),
        ("look", _) => {
            let look = value.filter(|v| LOOKS.contains(&v.as_str())).ok_or("That look isn't there.")?;
            let player = match &p {
                Playing::Solo(s) => s.player.clone(),
                Playing::Couch(c) => c.player.clone(),
            };
            let preset = crate::display::look_preset(&player, &look).unwrap_or_else(|| crate::display::plain_preset(&player));
            send_cmd(port, &format!("SET_SHADER {}", preset.to_string_lossy()));
            match &p {
                Playing::Solo(_) => {
                    if let Some(s) = lock(&SOLO).as_mut() {
                        s.look = look;
                    }
                }
                Playing::Couch(_) => crate::couch::set_menu_look(&app, &look),
            }
        }
        // ---- on your own
        ("save_state", Playing::Solo(_)) => send_cmd(port, "SAVE_STATE"),
        ("load_state", Playing::Solo(_)) => {
            send_cmd(port, "LOAD_STATE");
            close(&app, "Load state");
        }
        ("restart", Playing::Solo(_)) => {
            send_cmd(port, "RESET");
            close(&app, "Restart game");
        }
        ("quit", Playing::Solo(_)) => {
            close(&app, "Quit to Library");
            std::thread::sleep(Duration::from_millis(150));
            send_cmd(port, "QUIT");
        }
        // ---- Couch Play
        ("lobby", Playing::Couch(_)) => {
            close(&app, "Back to lobby");
            crate::couch::couch_fullscreen(app.clone(), false);
        }
        ("fullscreen", Playing::Couch(_)) => {
            close(&app, "Full screen");
            crate::couch::couch_fullscreen(app.clone(), true);
        }
        ("refresh", Playing::Couch(_)) => {
            close(&app, "Refresh game");
            crate::couch::couch_refresh(app.clone()).await?;
        }
        ("watch" | "play", Playing::Couch(_)) => {
            close(&app, "Switch play / watch");
            crate::couch::couch_switch(app.clone(), action.clone()).await?;
        }
        ("pause_all", Playing::Couch(_)) => {
            crate::couch::pause_for_everyone(&app, true).await?;
        }
        ("unpause_all", Playing::Couch(_)) => {
            crate::couch::pause_for_everyone(&app, false).await?;
        }
        ("leave", Playing::Couch(_)) => {
            close(&app, "Leave / end game");
            crate::couch::couch_leave(app.clone()).await?;
            let _ = app.emit("ingame-left-lobby", ());
        }
        _ => return Err("That can't be done here.".into()),
    }
    Ok(info(&app))
}
