//! Couch Play online: lobbies on Game Night's server, and the game itself through libretro's relay the
//! private way (nothing listed publicly anywhere). Contract: docs/COUCH_PLAY_SPEC.md.
//!
//! - Host: makes the lobby, holds a relay session with Game Night's own bridge (relay.rs), starts RetroArch as
//!   the netplay host (the bridge passes friends to it on this PC), and gives the session to the server, which
//!   only hands it to people in the lobby.
//! - Friend: joins on the server, then starts RetroArch connecting through the relay with that session, asking
//!   for their seat (or watching).
//! - Everyone: a heartbeat every 3 s tells the server whether the local game is running and brings back the
//!   lobby; seat changes from the host restart the local game in the new seat; the play/watch switch is
//!   RetroArch's NETPLAY_GAME_WATCH command on this PC. The game shows in the lobby's box (gamebox.rs).
//!
//! Logs on this PC only: couch.log and relay.log next to RetroArch's log (no passes or session ids in them).

use crate::account::{Account, SendError};
use crate::gamebox::GameBox;
use crate::games::{self, Netplay, PlaySettings};
use crate::relay;
use serde_json::{json, Value};
use std::fs;
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicIsize, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager, Runtime};

const CODE_LETTERS: &str = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
const BEAT: Duration = Duration::from_secs(3);
/// No answer from the server for this long (while the app is open) = give up on the lobby.
const GIVE_UP_BEATS: u32 = 20;
/// A RetroArch that closes this soon after starting is started once more (measured: occasional crash at start).
const QUICK_EXIT: Duration = Duration::from_secs(2);

/// A lobby code as typed (any case, spaces or dashes) -> the code, if it can be one.
pub fn normalize_code(raw: &str) -> Option<String> {
    let c: String = raw.chars().filter(|c| !c.is_whitespace() && *c != '-').collect::<String>().to_ascii_uppercase();
    (c.chars().count() == 6 && c.chars().all(|ch| CODE_LETTERS.contains(ch))).then_some(c)
}

/// Most players a game takes, from RomM's text ("1", "1-2", "1-4", "2 players"...). Unknown = 2.
pub fn most_players(raw: &str) -> u8 {
    raw.split(|c: char| !c.is_ascii_digit())
        .filter_map(|n| n.parse::<u32>().ok())
        .filter(|n| (1..=16).contains(n))
        .max()
        .map(|n| n as u8)
        .unwrap_or(2)
}

/// The relay details from a lobby, only if they look right (the server checks them too).
fn relay_of(lobby: &Value) -> Option<(String, u16, String)> {
    let r = lobby.get("relay")?;
    let server = r.get("server")?.as_str()?;
    let port = u16::try_from(r.get("port")?.as_u64()?).ok().filter(|p| *p > 0)?;
    let session = r.get("session")?.as_str()?;
    relay::parse_tunnel(&format!("tunnel_addr={server}\ntunnel_port={port}"))?;
    use base64::Engine;
    let ok = session.len() == 16 && base64::engine::general_purpose::STANDARD.decode(session).is_ok_and(|b| b.len() == 12);
    ok.then(|| (server.to_string(), port, session.to_string()))
}

/// (role, seat) of this PC's person in a lobby.
fn you(lobby: &Value) -> (String, Option<u8>) {
    let y = &lobby["you"];
    let role = y["role"].as_str().unwrap_or("watch").to_string();
    let seat = y["seat"].as_u64().and_then(|s| u8::try_from(s).ok()).filter(|s| (1..=4).contains(s));
    (role, seat)
}

fn ended(lobby: &Value) -> Option<String> {
    lobby.get("ended").and_then(|e| e.as_str()).map(String::from)
}

/// Plain-English message for a failed server call.
fn say(e: SendError) -> String {
    match e {
        SendError::SignedOut => "signed-out".into(),
        SendError::Offline => "Couldn't reach the Game Night server.".into(),
        SendError::Refused(_, Some(msg)) => msg,
        SendError::Refused(404, None) => "That code doesn't match an open lobby.".into(),
        SendError::Refused(403, None) => "Only the host can do that.".into(),
        SendError::Refused(429, None) => "Too many tries. Wait a minute, then try again.".into(),
        SendError::Refused(..) => "The Game Night server couldn't do that. Try again.".into(),
        SendError::Odd => "The server sent something odd.".into(),
    }
}

async fn api<R: Runtime>(app: &AppHandle<R>, method: reqwest::Method, path: &str, body: Option<Value>) -> Result<Value, SendError> {
    app.state::<Account>().send_json(app, method, path, body.as_ref()).await
}

async fn call<R: Runtime>(app: &AppHandle<R>, method: reqwest::Method, path: &str, body: Option<Value>) -> Result<Value, String> {
    api(app, method, path, body).await.map_err(say)
}

// ---------- logs ----------

/// A fresh gamebox.log for each game start (see gamebox.rs).
fn box_log<R: Runtime>(app: &AppHandle<R>) -> crate::gamebox::BoxLog {
    crate::gamebox::BoxLog::new(app.path().app_cache_dir().ok().map(|d| d.join("player").join("logs").join("gamebox.log")))
}

#[derive(Clone)]
struct FileLog {
    path: Option<PathBuf>,
    t0: Instant,
}

impl FileLog {
    /// A fresh log in the player logs folder.
    fn new<R: Runtime>(app: &AppHandle<R>, name: &str) -> FileLog {
        let path = app.path().app_cache_dir().ok().map(|d| d.join("player").join("logs").join(name));
        if let Some(p) = &path {
            if let Some(dir) = p.parent() {
                let _ = fs::create_dir_all(dir);
            }
            let _ = fs::write(p, "");
        }
        FileLog { path, t0: Instant::now() }
    }

    fn line(&self, s: &str) {
        if let Some(p) = &self.path {
            if let Ok(mut f) = fs::OpenOptions::new().append(true).create(true).open(p) {
                let _ = writeln!(f, "[{:7.1} s] {s}", self.t0.elapsed().as_secs_f64());
            }
        }
    }
}

// ---------- state ----------

#[derive(Clone, Copy, Debug, Default, PartialEq)]
enum RaState {
    Starting,
    Running,
    #[default]
    Stopped,
}

/// The local RetroArch, as the monitor thread sees it.
#[derive(Default)]
struct Local {
    /// Bumped for every start and stop, so an old monitor knows it's been replaced.
    gen: u64,
    state: RaState,
    /// RetroArch said netplay disconnected (it then plays on alone): offer rejoin.
    disconnected: bool,
    /// What it was started as: seat (None = watcher), and whether it's watching now.
    seat: Option<u8>,
    watching: bool,
    cmd_port: u16,
    /// The host's relay bridge stopped for good (friends already in carry on; nobody new can join).
    relay_lost: bool,
}

struct Game {
    root: PathBuf,
    id: String,
    console: String,
    settings: PlaySettings,
    /// Most players the game takes (from the lobby; RomM's "1-4" etc.).
    players: u8,
}

struct Ra {
    child: Arc<Mutex<Option<std::process::Child>>>,
}

struct Session {
    code: String,
    host: bool,
    game: Game,
    /// For friends: the relay details the server gave (updated by every heartbeat).
    relay: Option<(String, u16, String)>,
    bridge: Option<relay::Bridge>,
    netplay_port: u16,
    ra: Option<Ra>,
    heartbeat: Option<tauri::async_runtime::JoinHandle<()>>,
    epoch: u64,
    log: FileLog,
}

#[derive(Default)]
pub struct Couch {
    session: tokio::sync::Mutex<Option<Session>>,
    latest: Mutex<Option<Value>>,
    local: Arc<Mutex<Local>>,
    gamebox: GameBox,
    epoch: AtomicU64,
    main_hwnd: AtomicIsize,
}

fn lock<T>(m: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

impl Couch {
    /// The lobby as the screens see it: the server's copy plus "local" (this PC's game).
    fn view(&self) -> Option<Value> {
        let mut v = lock(&self.latest).clone()?;
        let l = lock(&self.local);
        let state = match l.state {
            RaState::Starting => "starting",
            RaState::Running => "running",
            RaState::Stopped => "stopped",
        };
        // This PC's own game, for the screens (lock the pad while playing, offer Rejoin).
        let game = if l.disconnected && l.state != RaState::Stopped { "disconnected" } else { state };
        if v.get("you").is_some_and(Value::is_object) {
            v["you"]["game"] = json!(game);
        }
        v["local"] = json!({
            "retroarch": state,
            "netplay": if l.disconnected { "disconnected" } else { "ok" },
            "watching": l.watching,
            "fullscreen": self.gamebox.fullscreen(),
            "relay": if l.relay_lost { "lost" } else { "ok" },
            "rejoin": l.state == RaState::Stopped || l.disconnected,
        });
        Some(v)
    }

    /// What the heartbeat reports.
    fn beat_state(&self) -> &'static str {
        let l = lock(&self.local);
        match (l.state, l.disconnected) {
            (_, true) | (RaState::Stopped, _) => "stopped",
            (RaState::Starting, _) => "starting",
            (RaState::Running, _) => "running",
        }
    }
}

fn emit_update<R: Runtime>(app: &AppHandle<R>) {
    if let Some(v) = app.state::<Couch>().view() {
        let _ = app.emit("couch-update", v);
    }
}

fn main_hwnd<R: Runtime>(app: &AppHandle<R>) -> isize {
    let couch = app.state::<Couch>();
    let have = couch.main_hwnd.load(Ordering::Relaxed);
    if have != 0 {
        return have;
    }
    #[cfg(windows)]
    {
        let h = app.get_webview_window("main").and_then(|w| w.hwnd().ok()).map(|h| h.0 as isize).unwrap_or(0);
        couch.main_hwnd.store(h, Ordering::Relaxed);
        h
    }
    #[cfg(not(windows))]
    0
}

fn free_tcp_port() -> Result<u16, String> {
    let l = std::net::TcpListener::bind(("127.0.0.1", 0)).map_err(|_| "Couldn't find a free network port.")?;
    l.local_addr().map(|a| a.port()).map_err(|_| "Couldn't find a free network port.".into())
}

fn free_udp_port() -> Result<u16, String> {
    let s = std::net::UdpSocket::bind(("127.0.0.1", 0)).map_err(|_| "Couldn't find a free network port.")?;
    s.local_addr().map(|a| a.port()).map_err(|_| "Couldn't find a free network port.".into())
}

/// Sends a command to the local RetroArch (this PC only).
fn send_cmd(port: u16, cmd: &str) {
    if let Ok(s) = std::net::UdpSocket::bind(("127.0.0.1", 0)) {
        let _ = s.send_to(cmd.as_bytes(), ("127.0.0.1", port));
    }
}

/// New text added to a log file since `offset`.
fn new_log_text(path: &Path, offset: &mut u64) -> String {
    let Ok(mut f) = fs::File::open(path) else { return String::new() };
    let len = f.metadata().map(|m| m.len()).unwrap_or(0);
    if len < *offset {
        *offset = 0; // a new log
    }
    let mut buf = Vec::new();
    if f.seek(SeekFrom::Start(*offset)).is_ok() && f.take(1 << 20).read_to_end(&mut buf).is_ok() {
        *offset += buf.len() as u64;
    }
    String::from_utf8_lossy(&buf).into_owned()
}

/// RetroArch's log says its netplay ended on its own (it plays on alone afterwards).
pub fn netplay_dropped(log: &str, host: bool) -> bool {
    log.contains("Failed to initialize netplay") || (!host && log.contains("Netplay disconnected"))
}

// ---------- the local RetroArch ----------

/// Starts RetroArch for this lobby, in the box. Seat None = watch.
fn start_ra<R: Runtime>(app: &AppHandle<R>, game: &Game, host: bool, seat: Option<u8>, args: Vec<String>, log: &FileLog) -> Result<Ra, String> {
    let couch = app.state::<Couch>();
    let cmd_port = free_udp_port()?;
    // SNES multitap (port 2) only for games that take 3 or more players; 2-player games get plain pads.
    let remaps = if game.console == "snes" && game.players > 2 {
        let dir = app.path().app_config_dir().map_err(|_| "No settings folder.")?.join("player").join("couch-remaps");
        games::write_snes_remap(&dir)?;
        Some(dir)
    } else {
        None
    };
    let nickname = app.state::<Account>().user_name(app).unwrap_or_default();
    let net = Netplay { host, seat, cmd_port, remaps, nickname, window: couch.gamebox.start_rect(main_hwnd(app)), args };
    let launch = games::prepare(app, &game.root, &game.id, &game.settings, Some(&net))?;
    let child = launch.spawn()?;
    let pid = child.id();
    let gen = {
        let mut l = lock(&couch.local);
        l.gen += 1;
        l.state = RaState::Starting;
        l.disconnected = false;
        l.seat = seat;
        l.watching = seat.is_none();
        l.cmd_port = cmd_port;
        l.gen
    };
    log.line(&format!(
        "started RetroArch as {} (process {pid})",
        if host { "host".to_string() } else { seat.map(|s| format!("player {s}")).unwrap_or("watcher".into()) }
    ));
    couch.gamebox.attach(pid, main_hwnd(app), box_log(app));
    let child = Arc::new(Mutex::new(Some(child)));
    let watched = child.clone();
    let app2 = app.clone();
    let log2 = log.clone();
    std::thread::spawn(move || monitor(app2, launch, watched, gen, host, log2));
    Ok(Ra { child })
}

/// Watches the local RetroArch: running after 2 s, one retry if it closes sooner, "disconnected" from its log.
fn monitor<R: Runtime>(app: AppHandle<R>, launch: games::Launch, child: Arc<Mutex<Option<std::process::Child>>>, gen: u64, host: bool, log: FileLog) {
    let couch = app.state::<Couch>();
    let mine = |l: &Local| l.gen == gen;
    let mut started = Instant::now();
    let mut retried = false;
    let mut offset = 0u64;
    let mut last_look = Instant::now();
    loop {
        std::thread::sleep(Duration::from_millis(200));
        if !mine(&lock(&couch.local)) {
            return; // stopped or replaced by Game Night
        }
        let exited = match lock(&child).as_mut() {
            Some(c) => c.try_wait().ok().flatten(),
            None => return,
        };
        if let Some(status) = exited {
            if started.elapsed() < QUICK_EXIT && !retried {
                retried = true;
                log.line(&format!("RetroArch closed straight away ({status}); starting it once more"));
                match launch.spawn() {
                    Ok(c) => {
                        couch.gamebox.attach(c.id(), main_hwnd(&app), box_log(&app));
                        *lock(&child) = Some(c);
                        started = Instant::now();
                        offset = 0;
                        continue;
                    }
                    Err(e) => log.line(&format!("couldn't start it again: {e}")),
                }
            }
            launch.after_exit();
            log.line(&format!("RetroArch closed ({status})"));
            {
                let mut l = lock(&couch.local);
                if !mine(&l) {
                    return;
                }
                l.state = RaState::Stopped;
            }
            couch.gamebox.detach();
            emit_update(&app);
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.set_focus();
            }
            return;
        }
        let mut changed = false;
        {
            let mut l = lock(&couch.local);
            if l.state == RaState::Starting && started.elapsed() >= QUICK_EXIT {
                l.state = RaState::Running;
                changed = true;
            }
        }
        if last_look.elapsed() >= Duration::from_secs(1) {
            last_look = Instant::now();
            let text = new_log_text(&launch.log_file, &mut offset);
            if netplay_dropped(&text, host) {
                let mut l = lock(&couch.local);
                if mine(&l) && !l.disconnected {
                    l.disconnected = true;
                    changed = true;
                    log.line("RetroArch says netplay ended (disconnected)");
                }
            }
        }
        if changed {
            emit_update(&app);
        }
    }
}

fn stop_ra<R: Runtime>(app: &AppHandle<R>, ra: Ra, log: &FileLog) {
    let couch = app.state::<Couch>();
    {
        let mut l = lock(&couch.local);
        l.gen += 1;
        l.state = RaState::Stopped;
    }
    couch.gamebox.detach();
    if let Some(mut c) = lock(&ra.child).take() {
        let _ = c.kill();
        let _ = c.wait();
        log.line("Game Night closed RetroArch");
    }
}

/// (Re)starts the local game for the seat the lobby gives this PC.
fn restart<R: Runtime>(app: &AppHandle<R>, s: &mut Session, lobby: &Value) -> Result<(), String> {
    if let Some(ra) = s.ra.take() {
        stop_ra(app, ra, &s.log);
    }
    let (role, seat) = you(lobby);
    let (seat, args) = if s.host {
        (Some(1), vec!["--host".into(), "--port".into(), s.netplay_port.to_string()])
    } else {
        let (server, port, session) = s.relay.clone().ok_or("The host's game isn't ready yet. Try again in a moment.")?;
        let seat = if role == "play" { seat } else { None };
        (seat, vec!["--connect".into(), server, "--port".into(), port.to_string(), format!("--mitm-session={session}")])
    };
    s.ra = Some(start_ra(app, &s.game, s.host, seat, args, &s.log)?);
    Ok(())
}

/// Brings the local game in line with the lobby: watch/play switch, or a new seat from the host.
fn reconcile<R: Runtime>(app: &AppHandle<R>, s: &mut Session, lobby: &Value) {
    if s.host || s.ra.is_none() {
        return;
    }
    let couch = app.state::<Couch>();
    let (state, disconnected, seat_now, watching, port) = {
        let l = lock(&couch.local);
        (l.state, l.disconnected, l.seat, l.watching, l.cmd_port)
    };
    if state == RaState::Stopped || disconnected {
        return; // the screen offers rejoin
    }
    let (role, seat) = you(lobby);
    if role != "play" {
        if !watching {
            s.log.line("switching to watching (NETPLAY_GAME_WATCH)");
            send_cmd(port, "NETPLAY_GAME_WATCH");
            lock(&couch.local).watching = true;
        }
    } else if seat.is_some() && seat == seat_now {
        if watching {
            s.log.line("switching to playing (NETPLAY_GAME_WATCH)");
            send_cmd(port, "NETPLAY_GAME_WATCH");
            lock(&couch.local).watching = false;
        }
    } else if seat.is_some() {
        s.log.line(&format!("seat changed to {:?}: restarting the game in that seat", seat));
        if let Err(e) = restart(app, s, lobby) {
            s.log.line(&format!("couldn't restart: {e}"));
        }
    }
}

/// Takes a fresh lobby from the server. Returns why it ended, if it has.
fn take_lobby<R: Runtime>(app: &AppHandle<R>, s: &mut Session, lobby: Value) -> Option<String> {
    let couch = app.state::<Couch>();
    if let Some(why) = ended(&lobby) {
        *lock(&couch.latest) = Some(lobby);
        return Some(why);
    }
    if !s.host {
        if let Some(r) = relay_of(&lobby) {
            s.relay = Some(r);
        }
    }
    let changed = lock(&couch.latest).as_ref() != Some(&lobby);
    *lock(&couch.latest) = Some(lobby.clone());
    reconcile(app, s, &lobby);
    if changed {
        emit_update(app);
    }
    None
}

/// Ends this PC's part in the lobby: closes the game and the relay session.
async fn teardown<R: Runtime>(app: &AppHandle<R>, mut s: Session, from_heartbeat: bool) {
    let couch = app.state::<Couch>();
    couch.epoch.fetch_add(1, Ordering::SeqCst);
    if !from_heartbeat {
        if let Some(h) = s.heartbeat.take() {
            h.abort();
        }
    }
    if let Some(ra) = s.ra.take() {
        stop_ra(app, ra, &s.log);
    }
    couch.gamebox.detach();
    couch.gamebox.set_fullscreen(false);
    if let Some(b) = s.bridge.take() {
        b.stop().await;
    }
    {
        let mut l = lock(&couch.local);
        *l = Local { gen: l.gen + 1, ..Default::default() };
    }
    *lock(&couch.latest) = None;
    games::release(app);
    s.log.line("left the lobby");
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.set_focus();
    }
}

async fn end<R: Runtime>(app: &AppHandle<R>, epoch: u64, reason: &str) {
    let couch = app.state::<Couch>();
    let mut g = couch.session.lock().await;
    if g.as_ref().is_some_and(|s| s.epoch == epoch) {
        if let Some(s) = g.take() {
            s.log.line(&format!("the lobby ended: {reason}"));
            teardown(app, s, true).await;
        }
        drop(g);
        let _ = app.emit("couch-ended", json!({ "reason": reason }));
    }
}

fn start_heartbeat<R: Runtime>(app: &AppHandle<R>, code: String, epoch: u64) -> tauri::async_runtime::JoinHandle<()> {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let mut fails = 0u32;
        loop {
            tokio::time::sleep(BEAT).await;
            let couch = app.state::<Couch>();
            if couch.epoch.load(Ordering::SeqCst) != epoch {
                return;
            }
            let body = json!({ "retroarch": couch.beat_state() });
            match api(&app, reqwest::Method::POST, &format!("/api/lobbies/{code}/heartbeat"), Some(body)).await {
                Ok(lobby) => {
                    fails = 0;
                    let why = {
                        let mut g = couch.session.lock().await;
                        match g.as_mut() {
                            Some(s) if s.epoch == epoch => take_lobby(&app, s, lobby),
                            _ => return,
                        }
                    };
                    if let Some(why) = why {
                        end(&app, epoch, &why).await;
                        return;
                    }
                }
                Err(SendError::SignedOut) => return end(&app, epoch, "signed-out").await,
                Err(SendError::Refused(404, _)) => return end(&app, epoch, "closed").await,
                Err(_) => {
                    fails += 1;
                    if fails >= GIVE_UP_BEATS {
                        return end(&app, epoch, "offline").await;
                    }
                }
            }
        }
    })
}

fn new_session<R: Runtime>(app: &AppHandle<R>, s: Session, lobby: Value) -> Session {
    let couch = app.state::<Couch>();
    let mut s = s;
    s.epoch = couch.epoch.fetch_add(1, Ordering::SeqCst) + 1;
    s.heartbeat = Some(start_heartbeat(app, s.code.clone(), s.epoch));
    *lock(&couch.latest) = Some(lobby);
    s
}

// ---------- commands ----------

#[tauri::command]
pub async fn couch_list<R: Runtime>(app: AppHandle<R>) -> Result<Value, String> {
    // CI's controller tests only (the "e2e" build, never shipped): their test player has no sign-in pass,
    // so the main menu's open-lobby list is simply empty instead of signing them out.
    #[cfg(feature = "e2e")]
    if matches!(std::env::var("GAMENIGHT_E2E").as_deref(), Ok("menus" | "padgame" | "play")) {
        return Ok(json!([]));
    }
    let v = call(&app, reqwest::Method::GET, "/api/lobbies", None).await?;
    Ok(v.get("lobbies").cloned().filter(Value::is_array).unwrap_or_else(|| json!([])))
}

#[tauri::command]
pub async fn couch_lookup<R: Runtime>(app: AppHandle<R>, code: String) -> Result<Value, String> {
    let code = normalize_code(&code).ok_or("That code doesn't look right. It's 6 letters and numbers.")?;
    call(&app, reqwest::Method::GET, &format!("/api/lobbies/{code}"), None).await
}

#[tauri::command]
pub fn couch_state<R: Runtime>(app: AppHandle<R>) -> Option<Value> {
    app.state::<Couch>().view()
}

/// Hosts a lobby for a game on this PC.
#[tauri::command]
pub async fn couch_host<R: Runtime>(app: AppHandle<R>, root: String, game_id: String, open: bool, settings: PlaySettings) -> Result<Value, String> {
    if game_id.is_empty() || game_id.len() > 12 || !game_id.chars().all(|c| c.is_ascii_digit()) {
        return Err("That game can't be hosted.".into());
    }
    let root = games::root_of(&root)?;
    let console = games::console_of(&root, &game_id).ok_or("That game isn't on this PC yet. Download it first.")?;
    if console != "nes" && console != "snes" {
        return Err("Only NES and SNES games can be played online for now.".into());
    }
    let couch = app.state::<Couch>();
    let mut g = couch.session.lock().await;
    if g.is_some() {
        return Err("You're already in a lobby. Leave it first.".into());
    }
    if !games::claim(&app, "couch") {
        return Err("A game is already running.".into());
    }
    let log = FileLog::new(&app, "couch.log");
    let game = Game { root, id: game_id, console, settings, players: 2 };
    match host_steps(&app, game, open, &log).await {
        Ok(s) => {
            *g = Some(s);
            drop(g);
            emit_update(&app);
            Ok(couch.view().unwrap_or(Value::Null))
        }
        Err(e) => {
            log.line(&format!("hosting failed: {e}"));
            games::release(&app);
            Err(e)
        }
    }
}

async fn host_steps<R: Runtime>(app: &AppHandle<R>, mut game: Game, open: bool, log: &FileLog) -> Result<Session, String> {
    let lobby = call(app, reqwest::Method::POST, "/api/lobbies", Some(json!({ "game_id": game.id, "open": open }))).await?;
    let code = lobby["code"].as_str().and_then(normalize_code).ok_or("The server sent something odd.")?;
    game.players = most_players(lobby["game"]["players"].as_str().unwrap_or(""));
    log.line(&format!("hosting lobby {code} (game {}, {})", game.id, if open { "open" } else { "code only" }));
    let mut s = Session {
        code: code.clone(),
        host: true,
        game,
        relay: None,
        bridge: None,
        netplay_port: 0,
        ra: None,
        heartbeat: None,
        epoch: 0,
        log: log.clone(),
    };
    let result: Result<Value, String> = async {
        s.netplay_port = free_tcp_port()?;
        let rlog_file = FileLog::new(app, "relay.log");
        let rlog: relay::Log = Arc::new(move |line: String| rlog_file.line(&line));
        let relay_at = relay::choose_relay(&rlog).await?;
        let (app_a, app_b, code_a) = (app.clone(), app.clone(), code.clone());
        let (log_a, log_b) = (log.clone(), log.clone());
        let bridge = relay::Bridge::start(
            relay_at,
            s.netplay_port,
            relay::Limits::default(),
            rlog,
            // The relay closed the session and the bridge opened a new one: friends need the new id.
            Box::new(move |session: String| {
                let (app, code, log) = (app_a.clone(), code_a.clone(), log_a.clone());
                tauri::async_runtime::spawn(async move {
                    let couch = app.state::<Couch>();
                    let Some((server, port)) = couch.session.lock().await.as_ref().and_then(|s| s.bridge.as_ref().map(|b| (b.server.clone(), b.port))) else { return };
                    let body = json!({ "server": server, "port": port, "session": session });
                    match call(&app, reqwest::Method::POST, &format!("/api/lobbies/{code}/relay"), Some(body)).await {
                        Ok(_) => log.line("posted the new relay session"),
                        Err(e) => log.line(&format!("couldn't post the new relay session: {e}")),
                    }
                });
            }),
            Box::new(move |why: String| {
                log_b.line(&format!("the relay bridge stopped: {why}"));
                lock(&app_b.state::<Couch>().local).relay_lost = true;
                emit_update(&app_b);
            }),
        )
        .await
        .map_err(|e| {
            log.line(&format!("relay: {e}"));
            "Couldn't reach the online relay. Check your internet and try again.".to_string()
        })?;
        let (server, port, session) = (bridge.server.clone(), bridge.port, bridge.session());
        s.bridge = Some(bridge);
        restart(app, &mut s, &lobby)?;
        // Give friends the session only once the host's game is up (so the first ones don't knock on a closed door).
        let couch = app.state::<Couch>();
        let t = Instant::now();
        loop {
            tokio::time::sleep(Duration::from_millis(200)).await;
            let (state, dropped) = {
                let l = lock(&couch.local);
                (l.state, l.disconnected)
            };
            if dropped {
                return Err("The game couldn't start online. Try again.".into());
            }
            match state {
                RaState::Running => break,
                RaState::Stopped => return Err("The game closed as it started. Try again.".into()),
                RaState::Starting if t.elapsed() > Duration::from_secs(30) => return Err("The game didn't start. Try again.".into()),
                RaState::Starting => {}
            }
        }
        let body = json!({ "server": server, "port": port, "session": session });
        let lobby = call(app, reqwest::Method::POST, &format!("/api/lobbies/{code}/relay"), Some(body)).await?;
        log.line("relay session given to the server; friends can join");
        Ok(lobby)
    }
    .await;
    match result {
        Ok(lobby) => Ok(new_session(app, s, lobby)),
        Err(e) => {
            let _ = api(app, reqwest::Method::POST, &format!("/api/lobbies/{code}/leave"), None).await;
            if let Some(ra) = s.ra.take() {
                stop_ra(app, ra, log);
            }
            if let Some(b) = s.bridge.take() {
                b.stop().await;
            }
            Err(e)
        }
    }
}

/// Joins a lobby by code, to play or watch. Joining the lobby you're already in = rejoin.
#[tauri::command]
pub async fn couch_join<R: Runtime>(app: AppHandle<R>, root: String, code: String, r#as: String, settings: PlaySettings) -> Result<Value, String> {
    let code = normalize_code(&code).ok_or("That code doesn't look right. It's 6 letters and numbers.")?;
    if r#as != "play" && r#as != "watch" {
        return Err("Pick play or watch.".into());
    }
    let root = games::root_of(&root)?;
    let couch = app.state::<Couch>();
    let mut g = couch.session.lock().await;
    if let Some(s) = g.as_mut() {
        if s.code != code {
            return Err("You're already in a lobby. Leave it first.".into());
        }
        rejoin(&app, s, Some(r#as)).await?;
        drop(g);
        return Ok(couch.view().unwrap_or(Value::Null));
    }
    if !games::claim(&app, "couch") {
        return Err("A game is already running.".into());
    }
    let log = FileLog::new(&app, "couch.log");
    match join_steps(&app, root, &code, &r#as, settings, &log).await {
        Ok(s) => {
            *g = Some(s);
            drop(g);
            emit_update(&app);
            Ok(couch.view().unwrap_or(Value::Null))
        }
        Err(e) => {
            log.line(&format!("joining failed: {e}"));
            games::release(&app);
            Err(e)
        }
    }
}

async fn join_steps<R: Runtime>(app: &AppHandle<R>, root: PathBuf, code: &str, as_: &str, settings: PlaySettings, log: &FileLog) -> Result<Session, String> {
    let lobby = call(app, reqwest::Method::POST, &format!("/api/lobbies/{code}/join"), Some(json!({ "as": as_ }))).await?;
    let leave_path = format!("/api/lobbies/{code}/leave");
    let leave = || api(app, reqwest::Method::POST, &leave_path, None);
    let id = lobby["game"]["id"].as_str().unwrap_or_default().to_string();
    let title = lobby["game"]["title"].as_str().unwrap_or("this game").to_string();
    let Some(console) = games::console_of(&root, &id) else {
        let _ = leave().await;
        return Err(format!("Download {title} first, then join."));
    };
    let Some(relay) = relay_of(&lobby) else {
        let _ = leave().await;
        return Err("The host's game isn't ready yet. Try again in a moment.".into());
    };
    log.line(&format!("joined lobby {code} to {as_} (game {id})"));
    let mut s = Session {
        code: code.to_string(),
        host: false,
        game: Game { root, id, console, settings, players: most_players(lobby["game"]["players"].as_str().unwrap_or("")) },
        relay: Some(relay),
        bridge: None,
        netplay_port: 0,
        ra: None,
        heartbeat: None,
        epoch: 0,
        log: log.clone(),
    };
    if let Err(e) = restart(app, &mut s, &lobby) {
        let _ = leave().await;
        return Err(e);
    }
    Ok(new_session(app, s, lobby))
}

/// Starts the local game again (after it closed or netplay disconnected). Friends ask for their seat back.
async fn rejoin<R: Runtime>(app: &AppHandle<R>, s: &mut Session, as_: Option<String>) -> Result<(), String> {
    let lobby = if s.host {
        lock(&app.state::<Couch>().latest).clone().unwrap_or(Value::Null)
    } else {
        let (role, _) = you(lock(&app.state::<Couch>().latest).as_ref().unwrap_or(&Value::Null));
        let as_ = as_.unwrap_or(if role == "play" { "play".into() } else { "watch".into() });
        let lobby = call(app, reqwest::Method::POST, &format!("/api/lobbies/{}/join", s.code), Some(json!({ "as": as_ }))).await?;
        if let Some(r) = relay_of(&lobby) {
            s.relay = Some(r);
        }
        lobby
    };
    s.log.line("rejoining");
    restart(app, s, &lobby)?;
    let _ = take_lobby(app, s, lobby);
    emit_update(app);
    Ok(())
}

/// Starts the local game again in the same lobby (after it closed or disconnected).
#[tauri::command]
pub async fn couch_rejoin<R: Runtime>(app: AppHandle<R>) -> Result<Value, String> {
    let couch = app.state::<Couch>();
    let mut g = couch.session.lock().await;
    let s = g.as_mut().ok_or("You're not in a lobby.")?;
    rejoin(&app, s, None).await?;
    drop(g);
    Ok(couch.view().unwrap_or(Value::Null))
}

/// Runs a server call for the lobby you're in and takes the answer.
async fn lobby_call<R: Runtime>(app: &AppHandle<R>, method: reqwest::Method, tail: &str, body: Option<Value>) -> Result<Value, String> {
    let couch = app.state::<Couch>();
    let mut g = couch.session.lock().await;
    let s = g.as_mut().ok_or("You're not in a lobby.")?;
    let path = format!("/api/lobbies/{}{tail}", s.code);
    let lobby = call(app, method, &path, body).await?;
    if let Some(why) = take_lobby(app, s, lobby) {
        let epoch = s.epoch;
        drop(g);
        end(app, epoch, &why).await;
        return Err("This lobby has ended.".into());
    }
    drop(g);
    Ok(couch.view().unwrap_or(Value::Null))
}

#[tauri::command]
pub async fn couch_switch<R: Runtime>(app: AppHandle<R>, r#as: String) -> Result<Value, String> {
    if r#as != "play" && r#as != "watch" {
        return Err("Pick play or watch.".into());
    }
    lobby_call(&app, reqwest::Method::POST, "/switch", Some(json!({ "as": r#as }))).await
}

#[tauri::command]
pub async fn couch_set_open<R: Runtime>(app: AppHandle<R>, open: bool) -> Result<Value, String> {
    lobby_call(&app, reqwest::Method::PATCH, "", Some(json!({ "open": open }))).await
}

#[tauri::command]
pub async fn couch_seat<R: Runtime>(app: AppHandle<R>, seat: u8, action: String, user: Option<String>) -> Result<Value, String> {
    if !["hold", "give", "empty"].contains(&action.as_str()) || !(1..=4).contains(&seat) {
        return Err("That can't be done to a seat.".into());
    }
    let mut body = json!({ "seat": seat, "action": action });
    if action == "give" {
        let user = user.filter(|u| !u.is_empty() && u.len() <= 25 && u.chars().all(|c| c.is_ascii_digit())).ok_or("Pick who gets the seat.")?;
        body["user"] = json!(user);
    }
    lobby_call(&app, reqwest::Method::POST, "/seat", Some(body)).await
}

#[tauri::command]
pub async fn couch_leave<R: Runtime>(app: AppHandle<R>) -> Result<(), String> {
    let couch = app.state::<Couch>();
    let mut g = couch.session.lock().await;
    if let Some(s) = g.take() {
        let _ = api(&app, reqwest::Method::POST, &format!("/api/lobbies/{}/leave", s.code), None).await;
        teardown(&app, s, false).await;
    }
    Ok(())
}

/// Where the game box is, in CSS pixels of the main window. Zero size = out of sight.
#[tauri::command]
pub fn couch_box<R: Runtime>(app: AppHandle<R>, x: f64, y: f64, w: f64, h: f64) {
    app.state::<Couch>().gamebox.set_box(x, y, w, h);
}

/// Game Night went full screen only for the game (it was windowed before): put it back afterwards.
static MADE_FULL: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

/// The game fills Game Night's window, and Game Night fills the screen (if it wasn't already).
#[tauri::command]
pub fn couch_fullscreen<R: Runtime>(app: AppHandle<R>, on: bool) {
    if let Some(w) = app.get_webview_window("main") {
        if on && !w.is_fullscreen().unwrap_or(true) {
            MADE_FULL.store(w.set_fullscreen(true).is_ok(), Ordering::SeqCst);
        } else if !on && MADE_FULL.swap(false, Ordering::SeqCst) {
            let _ = w.set_fullscreen(false);
        }
    }
    app.state::<Couch>().gamebox.set_fullscreen(on);
    emit_update(&app);
}

/// CI's Couch Play test only (the "e2e" build, never shipped): with GAMENIGHT_E2E=couchhost the app uses the
/// test server and pass from GAMENIGHT_E2E_SERVER / GAMENIGHT_E2E_TOKEN (in memory only) and hosts game "1"
/// from GAMENIGHT_E2E_ROOT as an open lobby, exactly like the host button. Then it writes e2e-couch.json there.
#[cfg(feature = "e2e")]
pub fn e2e_couch<R: Runtime>(app: AppHandle<R>) {
    if std::env::var("GAMENIGHT_E2E").as_deref() != Ok("couchhost") {
        return;
    }
    tauri::async_runtime::spawn(async move {
        let root = std::env::var("GAMENIGHT_E2E_ROOT").unwrap_or_default();
        let out = PathBuf::from(&root).join("e2e-couch.json");
        let server = std::env::var("GAMENIGHT_E2E_SERVER").unwrap_or_default();
        let token = std::env::var("GAMENIGHT_E2E_TOKEN").unwrap_or_default();
        let result = async {
            let server = crate::account::check_server(&server)?;
            app.state::<Account>().e2e_use(server, token);
            let settings: PlaySettings = serde_json::from_value(json!({
                "screen": "4:3", "picture": "scanlines", "rewind": false, "fastForward": false, "showFps": true
            }))
            .map_err(|e| e.to_string())?;
            couch_host(app.clone(), root.clone(), "1".into(), true, settings).await
        }
        .await;
        if result.is_ok() {
            // The lobby screen, like after pressing Host (a few times, in case the page was still loading).
            for _ in 0..3 {
                let _ = app.emit("e2e-show-lobby", ());
                tokio::time::sleep(std::time::Duration::from_millis(700)).await;
            }
        }
        let text = match result {
            Ok(v) => json!({ "code": v["code"], "cmd_port": lock(&app.state::<Couch>().local).cmd_port }),
            Err(e) => json!({ "error": e }),
        };
        let _ = fs::write(out, text.to_string());
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn codes() {
        assert_eq!(normalize_code("abc234").as_deref(), Some("ABC234"));
        assert_eq!(normalize_code("  ab c-234 ").as_deref(), Some("ABC234"));
        assert_eq!(normalize_code("ABC23"), None);
        assert_eq!(normalize_code("ABC2345"), None);
        assert_eq!(normalize_code("ABCDE0"), None); // no 0
        assert_eq!(normalize_code("ABCDEO"), None); // no O
        assert_eq!(normalize_code("ABCDE1"), None);
        assert_eq!(normalize_code("ABCDEI"), None);
        assert_eq!(normalize_code("ABC/../"), None);
        assert_eq!(normalize_code("ÄBC234"), None);
    }

    #[test]
    fn multitap_only_for_3_or_more_players() {
        assert_eq!(most_players("1-4"), 4);
        assert_eq!(most_players("1-2"), 2);
        assert_eq!(most_players("1"), 1);
        assert_eq!(most_players("2 players"), 2);
        assert_eq!(most_players("1-5"), 5);
        assert_eq!(most_players(""), 2);
        assert_eq!(most_players("lots"), 2);
        assert_eq!(most_players("99999999999"), 2);
        assert!(most_players("1-3") > 2 && most_players("1-2") <= 2);
    }

    #[test]
    fn lobby_reading() {
        let l = json!({
            "code": "ABC234",
            "you": {"id": "5", "role": "play", "seat": 3},
            "relay": {"server": "1.2.3.4", "port": 55435, "session": "AAECAwQFBgcICQoL"},
            "ended": null
        });
        assert_eq!(you(&l), ("play".to_string(), Some(3)));
        assert_eq!(relay_of(&l), Some(("1.2.3.4".into(), 55435, "AAECAwQFBgcICQoL".into())));
        assert_eq!(ended(&l), None);
        let w = json!({"you": {"role": "watch", "seat": null}, "relay": null, "ended": "host-left"});
        assert_eq!(you(&w), ("watch".to_string(), None));
        assert_eq!(relay_of(&w), None);
        assert_eq!(ended(&w).as_deref(), Some("host-left"));
        for bad in [
            json!({"relay": {"server": "a b", "port": 1, "session": "AAECAwQFBgcICQoL"}}),
            json!({"relay": {"server": "x.org", "port": 0, "session": "AAECAwQFBgcICQoL"}}),
            json!({"relay": {"server": "x.org", "port": 70000, "session": "AAECAwQFBgcICQoL"}}),
            json!({"relay": {"server": "x.org", "port": 5, "session": "AAECAwQFBgcICQ=="}}),
            json!({"relay": {"server": "x.org", "port": 5, "session": "--option-looking"}}),
        ] {
            assert_eq!(relay_of(&bad), None, "{bad}");
        }
        assert_eq!(you(&json!({"you": {"role": "play", "seat": 9}})).1, None);
    }

    #[test]
    fn messages_are_plain_english() {
        assert_eq!(say(SendError::SignedOut), "signed-out");
        assert_eq!(say(SendError::Refused(409, Some("All 4 seats are taken. You can watch.".into()))), "All 4 seats are taken. You can watch.");
        assert_eq!(say(SendError::Refused(404, None)), "That code doesn't match an open lobby.");
        assert!(!say(SendError::Refused(500, None)).contains("500"));
    }

    #[test]
    fn lobby_view_says_how_the_local_game_is() {
        let c = Couch::default();
        assert!(c.view().is_none());
        *lock(&c.latest) = Some(json!({"code": "ABC234", "you": {"id": "1", "role": "play", "seat": 2}}));
        assert_eq!(c.view().unwrap()["you"]["game"], "stopped");
        assert_eq!(c.beat_state(), "stopped");
        lock(&c.local).state = RaState::Starting;
        assert_eq!(c.view().unwrap()["you"]["game"], "starting");
        assert_eq!(c.beat_state(), "starting");
        lock(&c.local).state = RaState::Running;
        assert_eq!(c.view().unwrap()["you"]["game"], "running");
        lock(&c.local).disconnected = true;
        let v = c.view().unwrap();
        assert_eq!(v["you"]["game"], "disconnected");
        assert_eq!(v["local"]["rejoin"], true);
        assert_eq!(c.beat_state(), "stopped");
        assert_eq!(v["you"]["seat"], 2); // the server's fields are kept
    }

    #[test]
    fn netplay_drop_in_the_log() {
        assert!(netplay_dropped("[INFO] [Netplay] Netplay disconnected\n", false));
        assert!(!netplay_dropped("[INFO] [Netplay] A netplay client has disconnected\n", true));
        assert!(!netplay_dropped("[INFO] [Netplay] Netplay disconnected\n", true)); // host: a friend left
        assert!(netplay_dropped("[ERROR] [Netplay] Failed to initialize netplay.\n", true));
    }

    #[test]
    fn log_reading_carries_on() {
        let p = std::env::temp_dir().join(format!("gn-couch-log-{}", std::process::id()));
        fs::write(&p, "one\n").unwrap();
        let mut at = 0;
        assert_eq!(new_log_text(&p, &mut at), "one\n");
        assert_eq!(new_log_text(&p, &mut at), "");
        fs::OpenOptions::new().append(true).open(&p).unwrap().write_all(b"two\n").unwrap();
        assert_eq!(new_log_text(&p, &mut at), "two\n");
        fs::write(&p, "x\n").unwrap(); // a new, shorter log
        assert_eq!(new_log_text(&p, &mut at), "x\n");
        let _ = fs::remove_file(&p);
    }
}
