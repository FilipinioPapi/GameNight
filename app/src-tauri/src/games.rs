//! Downloading games from the Game Night server and playing them.
//!
//! Games live in the Game Night folder, one folder per console (nes, snes, ...). A small list,
//! library.json in that folder, remembers which file belongs to which game. Unfinished downloads
//! wait in the "downloads" folder so they can carry on where they stopped.
//!
//! Playing uses the copy of RetroArch that comes with Game Night (the "player" folder). Game Night
//! writes RetroArch's settings fresh for every game, with its menus switched off, so players only
//! ever see the game. Saves go in the Game Night folder's "saves" and "states" folders, which
//! "Clear my games" never touches.

use crate::account::Account;
use crate::{is_ours, CONSOLE_FOLDERS};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;
use tauri::{AppHandle, Emitter, Manager, Runtime};

/// The emulator for each console that can be played so far.
pub(crate) const CORES: &[(&str, &str)] = &[("nes", "fceumm_libretro.dll"), ("snes", "snes9x_libretro.dll")];

#[derive(Default)]
pub struct Games {
    /// Downloads in progress, with a "stop" switch each.
    active: Mutex<HashMap<String, Arc<AtomicBool>>>,
    /// The game being played right now, if any.
    playing: Mutex<Option<String>>,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
pub struct Entry {
    pub console: String,
    pub file: String,
    pub size: u64,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WantGame {
    id: String,
    console: String,
    size_bytes: u64,
}

#[derive(Deserialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct PlaySettings {
    screen: String,
    picture: String,
    rewind: bool,
    fast_forward: bool,
    show_fps: bool,
}

/// Couch Play (online) additions to RetroArch's settings. None = a normal game on your own.
#[derive(Clone, Debug, Default)]
pub(crate) struct Netplay {
    /// This PC hosts (its RetroArch takes friends from the relay bridge on this PC).
    pub host: bool,
    /// The seat (1-4) to ask for; None = watch.
    pub seat: Option<u8>,
    /// RetroArch's local command port, for switching play/watch.
    pub cmd_port: u16,
    /// Folder of Game Night's own remap files (SNES multitap), when the game needs it.
    pub remaps: Option<PathBuf>,
    /// The name others see in the game's messages.
    pub nickname: String,
    /// Where the window starts on the screen (x, y, width, height), before Game Night puts it in the box.
    pub window: Option<(i32, i32, i32, i32)>,
    /// Netplay command-line arguments (--host / --connect ...).
    pub args: Vec<String>,
}

#[derive(Serialize, Clone)]
struct Progress {
    id: String,
    done: u64,
    total: u64,
}

pub(crate) fn root_of(path: &str) -> Result<PathBuf, String> {
    let root = PathBuf::from(path);
    if is_ours(&root) {
        Ok(root)
    } else {
        Err("Pick a games folder in Settings first.".into())
    }
}

fn valid_id(id: &str) -> bool {
    !id.is_empty() && id.len() <= 12 && id.chars().all(|c| c.is_ascii_digit())
}

fn valid_console(c: &str) -> bool {
    c != "downloads" && CONSOLE_FOLDERS.contains(&c)
}

/// A file name that is safe on Windows: no folders, no odd characters, no reserved names.
pub fn safe_name(raw: &str, id: &str) -> String {
    let base = raw.rsplit(['/', '\\']).next().unwrap_or("");
    let mut s: String = base
        .chars()
        .map(|c| if c.is_control() || "<>:\"|?*".contains(c) { '_' } else { c })
        .collect();
    s = s.trim().trim_end_matches(['.', ' ']).to_string();
    while s.starts_with('.') {
        s.remove(0);
    }
    if s.chars().count() > 120 {
        // Keep the ending (the file type) when shortening.
        let ext: String = Path::new(&s).extension().map(|e| e.to_string_lossy().to_string()).unwrap_or_default();
        let keep: String = s.chars().take(100).collect();
        s = if ext.is_empty() || ext.len() > 8 { keep } else { format!("{keep}.{ext}") };
    }
    let stem = s.split('.').next().unwrap_or("").to_ascii_uppercase();
    let reserved = ["CON", "PRN", "AUX", "NUL"].contains(&stem.as_str())
        || ((stem.starts_with("COM") || stem.starts_with("LPT")) && stem.len() == 4);
    if s.is_empty() || reserved {
        format!("game-{id}.bin")
    } else {
        s
    }
}

fn index_path(root: &Path) -> PathBuf {
    root.join("library.json")
}

pub(crate) fn read_index(root: &Path) -> HashMap<String, Entry> {
    fs::read_to_string(index_path(root)).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or_default()
}

fn write_index(root: &Path, idx: &HashMap<String, Entry>) -> Result<(), String> {
    let text = serde_json::to_string_pretty(idx).map_err(|_| "Couldn't save the game list.")?;
    let tmp = root.join("library.json.part");
    fs::write(&tmp, text).and_then(|_| fs::rename(&tmp, index_path(root))).map_err(|_| "Couldn't save the game list.".to_string())
}

/// Path of a game's file, only if it is really there, inside its console folder, at the right size.
pub(crate) fn game_file(root: &Path, e: &Entry) -> Option<PathBuf> {
    if !valid_console(&e.console) || safe_name(&e.file, "0") != e.file {
        return None;
    }
    let p = root.join(&e.console).join(&e.file);
    let m = p.symlink_metadata().ok()?;
    (m.is_file() && m.len() == e.size).then_some(p)
}

/// Which games are on this PC: game id -> file details.
#[tauri::command]
pub fn installed_games(root: String) -> HashMap<String, Entry> {
    let Ok(root) = root_of(&root) else { return HashMap::new() };
    read_index(&root).into_iter().filter(|(_, e)| game_file(&root, e).is_some()).collect()
}

/// Downloads one game into its console folder, reporting progress as "download-progress".
#[tauri::command]
pub async fn download_game<R: Runtime>(app: AppHandle<R>, root: String, game: WantGame) -> Result<Entry, String> {
    let root = root_of(&root)?;
    if !valid_id(&game.id) || !valid_console(&game.console) {
        return Err("That game can't be downloaded.".into());
    }
    let stop = Arc::new(AtomicBool::new(false));
    {
        let state = app.state::<Games>();
        let mut active = state.active.lock().unwrap_or_else(|e| e.into_inner());
        if active.contains_key(&game.id) {
            return Err("That game is already downloading.".into());
        }
        active.insert(game.id.clone(), stop.clone());
    }
    let result = fetch(&app, &root, &game, &stop).await;
    app.state::<Games>().active.lock().unwrap_or_else(|e| e.into_inner()).remove(&game.id);
    result
}

async fn fetch<R: Runtime>(app: &AppHandle<R>, root: &Path, game: &WantGame, stop: &AtomicBool) -> Result<Entry, String> {
    let downloads = root.join("downloads");
    fs::create_dir_all(&downloads).map_err(|_| "Couldn't make the games folder. Check it in Settings.")?;
    let part = downloads.join(format!("{}.part", game.id));
    let have = part.symlink_metadata().map(|m| if m.is_file() { m.len() } else { 0 }).unwrap_or(0);

    let path = format!("/api/games/{}/download", game.id);
    let mut resp = app.state::<Account>().download(app, &path, have).await.map_err(|e| match e.as_str() {
        "signed-out" => e,
        "offline" => "Couldn't reach the Game Night server.".into(),
        _ => "The game library couldn't send that game. Try again later.".into(),
    })?;
    // 206 = carrying on from where we stopped. 200 = the whole file from the start.
    let resumed = resp.status() == reqwest::StatusCode::PARTIAL_CONTENT && have > 0;
    let name = resp
        .headers()
        .get("x-game-file")
        .and_then(|v| v.to_str().ok())
        .map(|n| safe_name(n, &game.id))
        .unwrap_or_else(|| safe_name("", &game.id));
    let mut done = if resumed { have } else { 0 };
    let total = resp.content_length().map(|n| n + done).filter(|n| *n > 0).unwrap_or(game.size_bytes);

    // Room check: the game plus a little spare.
    if let Ok(free) = free_space(root) {
        if free < total.saturating_sub(done) + 50 * 1024 * 1024 {
            return Err("There isn't enough free space on that drive. Clear some games or pick another folder in Settings.".into());
        }
    }

    let mut out = fs::OpenOptions::new()
        .create(true)
        .write(true)
        .append(resumed)
        .truncate(!resumed)
        .open(&part)
        .map_err(|_| "Couldn't write to the games folder.")?;
    let mut last = Instant::now();
    let _ = app.emit("download-progress", Progress { id: game.id.clone(), done, total });
    loop {
        if stop.load(Ordering::Relaxed) {
            return Err("stopped".into());
        }
        let chunk = match resp.chunk().await {
            Ok(Some(c)) => c,
            Ok(None) => break,
            Err(_) => return Err("The download stopped. Press Download again to carry on.".into()),
        };
        out.write_all(&chunk).map_err(|_| "Couldn't write to the games folder. Is the drive full?")?;
        done += chunk.len() as u64;
        if total > 0 && done > total {
            drop(out);
            let _ = fs::remove_file(&part);
            return Err("The game arrived bigger than expected, so it was thrown away. Try again.".into());
        }
        if last.elapsed().as_millis() >= 150 {
            last = Instant::now();
            let _ = app.emit("download-progress", Progress { id: game.id.clone(), done, total });
        }
    }
    out.flush().map_err(|_| "Couldn't write to the games folder.")?;
    drop(out);
    if total > 0 && done != total {
        return Err("The download stopped early. Press Download again to carry on.".into());
    }

    let folder = root.join(&game.console);
    fs::create_dir_all(&folder).map_err(|_| "Couldn't make the console folder.")?;
    let dest = folder.join(&name);
    let _ = fs::remove_file(&dest);
    fs::rename(&part, &dest).map_err(|_| "Couldn't move the game into place.")?;
    let entry = Entry { console: game.console.clone(), file: name, size: done };
    let mut idx = read_index(root);
    idx.insert(game.id.clone(), entry.clone());
    write_index(root, &idx)?;
    let _ = app.emit("download-progress", Progress { id: game.id.clone(), done, total: done });
    Ok(entry)
}

fn free_space(root: &Path) -> Result<u64, ()> {
    let disks = sysinfo::Disks::new_with_refreshed_list();
    disks
        .list()
        .iter()
        .filter(|d| root.starts_with(d.mount_point()))
        .max_by_key(|d| d.mount_point().as_os_str().len())
        .map(|d| d.available_space())
        .ok_or(())
}

/// Stops a download. What arrived so far is kept so it can carry on later.
#[tauri::command]
pub fn cancel_download<R: Runtime>(app: AppHandle<R>, id: String) {
    if let Some(s) = app.state::<Games>().active.lock().unwrap_or_else(|e| e.into_inner()).get(&id) {
        s.store(true, Ordering::Relaxed);
    }
}

/// Deletes one downloaded game. Its saves stay.
#[tauri::command]
pub fn remove_game(root: String, id: String) -> Result<(), String> {
    let root = root_of(&root)?;
    let mut idx = read_index(&root);
    if let Some(e) = idx.remove(&id) {
        if let Some(p) = game_file(&root, &e) {
            fs::remove_file(p).map_err(|_| "Couldn't delete that game. Is it still running?")?;
        }
        write_index(&root, &idx)?;
    }
    let _ = fs::remove_file(root.join("downloads").join(format!("{id}.part")));
    Ok(())
}

/// Where the bundled RetroArch lives.
fn player_dir<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    #[cfg(debug_assertions)]
    if let Ok(p) = std::env::var("GAMENIGHT_PLAYER_DIR") {
        return Some(PathBuf::from(p));
    }
    app.path().resource_dir().ok().map(|d| d.join("player"))
}

pub struct ConfigPaths {
    pub player: PathBuf,
    pub logs: PathBuf,
    pub saves: PathBuf,
    pub states: PathBuf,
    pub system: PathBuf,
    pub cache: PathBuf,
}

/// Ways RetroArch can play sound on Windows, best first. If one doesn't start on a PC
/// (RetroArch says so in its log), the next game uses the next one.
pub const SOUND_WAYS: [&str; 3] = ["xaudio", "wasapi", "dsound"];

/// RetroArch writes this to its log when it couldn't start the sound.
pub fn sound_failed(log: &str) -> bool {
    log.contains("Failed to initialize audio driver")
}

/// CI's Windows tests only (the "e2e" build, never shipped): which test is running. Always None otherwise.
fn e2e_mode() -> Option<&'static str> {
    #[cfg(feature = "e2e")]
    {
        match std::env::var("GAMENIGHT_E2E").as_deref() {
            Ok("play") => return Some("play"),
            Ok("padgame") => return Some("padgame"),
            _ => {}
        }
    }
    None
}

/// RetroArch's settings for one game. Menus, online features and anything that could take a player
/// out of the game are switched off. Quitting: Esc, or L1 + R1 + Start + Select on a controller.
/// `net`: Couch Play's online settings on top (see `netplay_lines`).
pub fn retroarch_config(p: &ConfigPaths, s: &PlaySettings, sound: usize, pads: &crate::controllers::Plan, net: Option<&Netplay>) -> String {
    let path = |p: &Path| p.to_string_lossy().replace('"', "");
    let yes = |b: bool| if b { "true" } else { "false" };
    let (aspect, integer) = match s.screen.as_str() {
        "pixel" => (22, true),   // the console's own shape, sharp whole-pixel scaling
        "stretch" => (24, false), // fill the screen
        _ => (0, false),          // 4:3, like an old TV
    };
    let base: Vec<(&str, String)> = vec![
        // Never write these settings back, never show menus or online extras.
        ("config_save_on_exit", "false".into()),
        ("menu_driver", "rgui".into()),
        ("input_menu_toggle", "nul".into()),
        ("input_menu_toggle_gamepad_combo", "0".into()),
        ("input_desktop_menu_toggle", "nul".into()),
        ("ui_companion_enable", "false".into()),
        ("ui_companion_start_on_boot", "false".into()),
        ("desktop_menu_enable", "false".into()),
        // No File / Command / Window bar on the game's window (it showed in the lobby's game box; measured).
        ("ui_menubar_enable", "false".into()),
        ("menu_show_online_updater", "false".into()),
        ("menu_show_core_updater", "false".into()),
        // Off, except in CI's controller-in-a-game test (the "e2e" build), which asks the game what it sees.
        ("network_cmd_enable", yes(e2e_mode() == Some("padgame")).into()),
        ("stdin_cmd_enable", "false".into()),
        ("netplay_nat_traversal", "false".into()),
        ("cheevos_enable", "false".into()),
        ("discord_allow", "false".into()),
        ("history_list_enable", "false".into()),
        ("game_specific_options", "false".into()),
        ("auto_overrides_enable", "false".into()),
        ("auto_remaps_enable", "false".into()),
        ("auto_shaders_enable", "false".into()),
        // A short log on this PC only, so problems like "no sound" can be spotted.
        ("log_to_file", "true".into()),
        ("log_to_file_timestamp", "false".into()),
        ("log_verbosity", "true".into()),
        ("frontend_log_level", "1".into()),
        ("libretro_log_level", "2".into()),
        ("log_dir", path(&p.logs)),
        // Quitting goes straight back to Game Night.
        ("input_exit_emulator", "escape".into()),
        ("quit_press_twice", "false".into()),
        // Both sticks pressed in (L3 + R3). Never Start/Select: Windows and Steam use those for their own shortcuts.
        ("input_quit_gamepad_combo", "2".into()),
        // Screen
        ("video_driver", "d3d11".into()),
        ("video_fullscreen", "true".into()),
        ("video_windowed_fullscreen", "true".into()),
        ("aspect_ratio_index", aspect.to_string()),
        ("video_scale_integer", yes(integer).into()),
        ("video_smooth", yes(s.picture == "smooth").into()),
        ("video_shader_enable", yes(s.picture == "scanlines").into()),
        ("fps_show", yes(s.show_fps).into()),
        // Sound, and normal speed. RetroArch keeps games at their real speed by pacing them with
        // the sound, so without sound they race at the screen's refresh rate (e.g. 144 Hz).
        ("audio_enable", "true".into()),
        ("audio_mute_enable", "false".into()),
        ("audio_driver", SOUND_WAYS[sound.min(SOUND_WAYS.len() - 1)].into()),
        ("audio_device", "".into()),
        ("audio_wasapi_exclusive_mode", "false".into()),
        ("audio_sync", "true".into()),
        ("video_vsync", "true".into()),
        // Last resort when no sound way works: a plain speed limit instead.
        ("vrr_runloop_enable", yes(sound >= SOUND_WAYS.len()).into()),
        // Rewind and fast forward (keyboard: R and Space; controllers come with controller setup)
        ("rewind_enable", yes(s.rewind).into()),
        ("input_rewind", if s.rewind { "r" } else { "nul" }.into()),
        ("input_hold_fast_forward", if s.fast_forward { "space" } else { "nul" }.into()),
        ("input_toggle_fast_forward", "nul".into()),
        // Controllers
        // "xinput" normally; "dinput" when an extra hidden Xbox-style slot would make "xinput" read
        // the wrong one (see retroports.rs).
        ("input_joypad_driver", if pads.joypad_driver == "dinput" { "dinput" } else { "xinput" }.into()),
        ("input_autodetect_enable", "true".into()),
        ("joypad_autoconfig_dir", path(&p.player.join("autoconfig"))),
        ("input_max_users", crate::controllers::PLAYERS.to_string()),
        // Folders: RetroArch's own bits, and saves in the Game Night folder.
        ("libretro_directory", path(&p.player.join("cores"))),
        ("savefile_directory", path(&p.saves)),
        ("savestate_directory", path(&p.states)),
        ("system_directory", path(&p.system)),
        ("cache_directory", path(&p.cache)),
        ("sort_savefiles_enable", "false".into()),
        ("sort_savestates_enable", "false".into()),
    ]
    .into_iter()
    .chain(quiet_lines(s.show_fps))
    .collect();
    let mut lines: Vec<(String, String)> = base.into_iter().map(|(k, v)| (k.to_string(), v)).collect();
    if let Some(n) = net {
        for (k, v) in netplay_lines(n) {
            match lines.iter_mut().find(|(have, _)| *have == k) {
                Some(line) => line.1 = v,
                None => lines.push((k, v)),
            }
        }
    }
    let mut out = String::from("# Written by Game Night for each game. Changes here are replaced.\n");
    for (k, v) in lines {
        out.push_str(&format!("{k} = \"{v}\"\n"));
    }
    // Player 1 is the chosen controller, or the one last pressed in Game Night. Controllers turned off
    // in Settings are parked on players 5, 6, ... which no game uses, so they can't take a player's place.
    let mut pad = |n: usize, kind: &str, id: &str| {
        out.push_str(&format!("input_player{n}_device_reservation_type = \"{kind}\"\ninput_player{n}_reserved_device = \"{id}\"\n"));
    };
    match &pads.player1 {
        Some(id) => pad(1, "1", id),
        None => pad(1, "0", ""),
    }
    for (i, id) in pads.parked.iter().enumerate() {
        pad(crate::controllers::PLAYERS + 1 + i, "2", id);
    }
    out
}

/// RetroArch's own pop-up messages, all off (quiet_retroarch.cfg says which and why). Show FPS needs
/// RetroArch's message drawing, so with it on only the FPS counter's switch comes back on.
const QUIET: &str = include_str!("quiet_retroarch.cfg");

fn quiet_lines(show_fps: bool) -> impl Iterator<Item = (&'static str, String)> {
    QUIET.lines().filter_map(move |l| {
        let (k, v) = l.split_once('=')?;
        let (k, v) = (k.trim(), v.trim().trim_matches('"'));
        if k.is_empty() || k.starts_with('#') {
            return None;
        }
        Some((k, if k == "video_font_enable" && show_fps { "true".to_string() } else { v.to_string() }))
    })
}

/// What Couch Play changes or adds: private netplay only (no public list, no libretro relay lookup by
/// RetroArch, no router hole-punching), the game in a borderless window Game Night places itself, and
/// RetroArch's own full screen switch off (it throws its window away and makes a new one; measured).
fn netplay_lines(n: &Netplay) -> Vec<(String, String)> {
    let path = |p: &Path| p.to_string_lossy().replace('"', "");
    let yes = |b: bool| if b { "true" } else { "false" }.to_string();
    let name: String = n.nickname.chars().filter(|c| c.is_ascii_alphanumeric() || " _-.".contains(*c)).take(32).collect();
    let name = if name.trim().is_empty() { "Player".to_string() } else { name.trim().to_string() };
    let mut v: Vec<(String, String)> = [
        ("netplay_public_announce", "false".to_string()),
        ("netplay_use_mitm_server", "false".into()),
        ("netplay_nat_traversal", "false".into()),
        ("netplay_max_connections", "8".into()),
        ("netplay_max_ping", "0".into()),
        ("netplay_check_frames", "0".into()),
        ("netplay_ping_show", "false".into()),
        ("netplay_allow_pausing", "false".into()),
        ("netplay_password", "".into()),
        ("netplay_spectate_password", "".into()),
        ("netplay_nickname", name),
        ("netplay_start_as_spectator", yes(!n.host && n.seat.is_none())),
        // Local commands for the play/watch switch, sent by Game Night on this PC.
        ("network_cmd_enable", "true".into()),
        ("network_cmd_port", n.cmd_port.to_string()),
        // A plain borderless window that Game Night keeps over the game box (or over the whole screen).
        ("video_fullscreen", "false".into()),
        ("video_windowed_fullscreen", "false".into()),
        ("video_window_show_decorations", "false".into()),
        ("input_toggle_fullscreen", "nul".into()),
        // In a lobby, L3 + R3 opens lobby controls, so it mustn't also close the game.
        ("input_quit_gamepad_combo", "0".into()),
        ("pause_nonactive", "false".into()),
        // Netplay can't rewind or speed up.
        ("rewind_enable", "false".into()),
        ("input_rewind", "nul".into()),
        ("input_hold_fast_forward", "nul".into()),
        ("savestate_auto_load", "false".into()),
        ("savestate_auto_save", "false".into()),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_string(), v))
    .collect();
    for p in 1..=16u8 {
        v.push((format!("netplay_request_device_p{p}"), yes(n.seat == Some(p))));
    }
    if let Some(dir) = &n.remaps {
        v.push(("auto_remaps_enable".into(), "true".into()));
        v.push(("input_remapping_directory".into(), path(dir)));
    }
    if let Some((x, y, w, h)) = n.window {
        v.push(("video_window_save_positions".into(), "true".into()));
        v.push(("video_windowed_position_x".into(), x.to_string()));
        v.push(("video_windowed_position_y".into(), y.to_string()));
        v.push(("video_windowed_position_width".into(), w.max(64).to_string()));
        v.push(("video_windowed_position_height".into(), h.max(64).to_string()));
    }
    v
}

/// SNES 3-4 players: the multitap on port 2. RetroArch only reads this from a remap file (measured).
pub(crate) const SNES_MULTITAP_REMAP: &str = "input_libretro_device_p1 = \"1\"\ninput_libretro_device_p2 = \"257\"\n";

/// Writes Game Night's own Snes9x remap file under `dir` (in Game Night's settings folder).
pub(crate) fn write_snes_remap(dir: &Path) -> Result<(), String> {
    let core = dir.join("Snes9x");
    fs::create_dir_all(&core).map_err(|_| "Couldn't write the controller settings.")?;
    fs::write(core.join("Snes9x.rmp"), SNES_MULTITAP_REMAP).map_err(|_| "Couldn't write the controller settings.".to_string())
}

/// A short note of the controllers seen and who got what, kept next to RetroArch's log.
fn describe(plugged: &[crate::retroports::Device], pads: &crate::controllers::Plan) -> String {
    let mut t = String::new();
    for d in plugged {
        t.push_str(&format!("{} ({} / usb {})\n", d.name, crate::controllers::id(d.ra), crate::controllers::id(d.usb)));
    }
    t.push_str(&format!(
        "player 1: {}\nturned off: {}\nreader: {}\n",
        pads.player1.as_deref().unwrap_or("not set (RetroArch's own order)"),
        pads.parked.join(", "),
        pads.joypad_driver
    ));
    t
}

/// One RetroArch start, ready to go (and to go again, for Couch Play's one retry).
pub(crate) struct Launch {
    exe: PathBuf,
    cwd: PathBuf,
    args: Vec<std::ffi::OsString>,
    pub log_file: PathBuf,
    sound_file: PathBuf,
    sound: usize,
}

impl Launch {
    pub(crate) fn spawn(&self) -> Result<std::process::Child, String> {
        let _ = fs::remove_file(&self.log_file);
        std::process::Command::new(&self.exe)
            .current_dir(&self.cwd)
            .args(&self.args)
            .spawn()
            .map_err(|_| "Couldn't start the game.".to_string())
    }

    /// After RetroArch closes: no sound this time? Try the next way next time. Returns "no sound".
    pub(crate) fn after_exit(&self) -> bool {
        let log = fs::read_to_string(&self.log_file).ok();
        let silent = log.as_deref().map(sound_failed).unwrap_or(false);
        if silent && self.sound < SOUND_WAYS.len() {
            let _ = fs::write(&self.sound_file, (self.sound + 1).to_string());
        } else if !silent && log.is_some() && self.sound == SOUND_WAYS.len() {
            // The last resort had sound after all (e.g. speakers plugged back in): back to normal pacing.
            let _ = fs::write(&self.sound_file, (SOUND_WAYS.len() - 1).to_string());
        }
        silent
    }
}

/// The game's console, if that game is on this PC and can be played.
pub(crate) fn console_of(root: &Path, id: &str) -> Option<String> {
    let e = read_index(root).remove(id)?;
    game_file(root, &e)?;
    CORES.iter().any(|(c, _)| *c == e.console).then_some(e.console)
}

/// Writes RetroArch's settings for one game and works out how to start it. `net`: Couch Play.
pub(crate) fn prepare<R: Runtime>(app: &AppHandle<R>, root: &Path, id: &str, settings: &PlaySettings, net: Option<&Netplay>) -> Result<Launch, String> {
    let entry = read_index(root).remove(id).ok_or("That game isn't on this PC yet.")?;
    let rom = game_file(root, &entry).ok_or("That game's file is missing. Download it again.")?;
    let core = CORES.iter().find(|(c, _)| *c == entry.console).map(|(_, f)| *f).ok_or("That console can't be played yet.")?;
    let player = player_dir(app).ok_or("Game Night's player is missing. Reinstall Game Night.")?;
    let exe = player.join(if cfg!(windows) { "retroarch.exe" } else { "retroarch" });
    let core_path = player.join("cores").join(core);
    if !exe.is_file() || !core_path.is_file() {
        return Err("Game Night's player is missing. Reinstall Game Night.".into());
    }
    let cfg_dir = app.path().app_config_dir().map_err(|_| "No settings folder.")?.join("player");
    let cache = app.path().app_cache_dir().map_err(|_| "No cache folder.")?.join("player");
    let sound_file = cfg_dir.join("sound.txt");
    // Player 1: the controller chosen in Settings, else the one last pressed in the menus, else the
    // one remembered from last time. Turned-off controllers are parked.
    let pad_file = cfg_dir.join("controller.txt");
    let last_used = *crate::pads::LAST_USED.lock().unwrap_or_else(|e| e.into_inner());
    let scan = crate::retroports::scan();
    let plugged = &scan.devices;
    let mut pads = crate::controllers::plan(
        &crate::controllers::prefs(app),
        plugged,
        last_used,
        fs::read_to_string(&pad_file).ok().as_deref(),
    );
    pads.joypad_driver = crate::retroports::joypad_driver(&scan);
    // CI's controller test only (the "e2e" build): try RetroArch's "dinput" reader, the one Jayden's PC
    // gets (CI's pretend pads never trigger the switch by themselves).
    #[cfg(feature = "e2e")]
    if std::env::var("GAMENIGHT_E2E_READER").as_deref() == Ok("dinput") {
        pads.joypad_driver = "dinput";
    }
    let sound: usize = fs::read_to_string(&sound_file).ok().and_then(|t| t.trim().parse().ok()).unwrap_or(0).min(SOUND_WAYS.len());
    // Someone else's game (Couch Play as a friend): its battery saves go to a folder of their own, so
    // they never overwrite your own saves for that game.
    let guest = net.is_some_and(|n| !n.host);
    let saves = if guest { root.join("saves").join("couch") } else { root.join("saves") };
    let states = if guest { root.join("states").join("couch") } else { root.join("states") };
    let paths = ConfigPaths {
        player: player.clone(),
        logs: cache.join("logs"),
        saves: saves.join(&entry.console),
        states: states.join(&entry.console),
        system: root.join("bios"),
        cache,
    };
    let log_file = paths.logs.join("retroarch.log");
    for d in [&cfg_dir, &paths.saves, &paths.states, &paths.system, &paths.cache, &paths.logs] {
        fs::create_dir_all(d).map_err(|_| "Couldn't make the saves folder.")?;
    }
    let cfg = cfg_dir.join("retroarch.cfg");
    if let Some(id) = &pads.player1 {
        let _ = fs::write(&pad_file, id);
    }
    let _ = fs::write(paths.logs.join("controllers.txt"), describe(plugged, &pads));
    fs::write(&cfg, retroarch_config(&paths, settings, sound, &pads, net)).map_err(|_| "Couldn't write the player settings.")?;
    let mut args: Vec<std::ffi::OsString> = vec!["--config".into(), cfg.into_os_string(), "-L".into(), core_path.into_os_string()];
    match net {
        None => args.push("--fullscreen".into()),
        Some(n) => args.extend(n.args.iter().map(Into::into)),
    }
    if settings.picture == "scanlines" {
        args.push("--set-shader".into());
        args.push(player.join("shaders").join("scanlines.slangp").into_os_string());
    }
    // CI's Windows tests only (the "e2e" build): the game test plays 600 frames (10 seconds at real
    // speed), the controller-in-a-game test up to a minute (it closes the game once it has its answers).
    match e2e_mode() {
        Some("play") => args.push("--max-frames=600".into()),
        Some("padgame") => args.push("--max-frames=3600".into()),
        _ => {}
    }
    args.push(rom.into_os_string());
    Ok(Launch { exe, cwd: player, args, log_file, sound_file, sound })
}

/// Marks a game as running (only one at a time, alone or online). False = one already is.
pub(crate) fn claim<R: Runtime>(app: &AppHandle<R>, what: &str) -> bool {
    let state = app.state::<Games>();
    let mut playing = state.playing.lock().unwrap_or_else(|e| e.into_inner());
    if playing.is_some() {
        return false;
    }
    *playing = Some(what.to_string());
    true
}

pub(crate) fn release<R: Runtime>(app: &AppHandle<R>) {
    *app.state::<Games>().playing.lock().unwrap_or_else(|e| e.into_inner()) = None;
}

/// Starts a downloaded game fullscreen. "game-closed" fires when the player quits.
#[tauri::command]
pub fn play_game<R: Runtime>(app: AppHandle<R>, root: String, id: String, settings: PlaySettings) -> Result<(), String> {
    let root = root_of(&root)?;
    if !claim(&app, &id) {
        return Err("A game is already running.".into());
    }
    let started = prepare(&app, &root, &id, &settings, None).and_then(|l| l.spawn().map(|c| (l, c)));
    let (launch, mut child) = match started {
        Ok(x) => x,
        Err(e) => {
            release(&app);
            return Err(e);
        }
    };
    // Game Night steps aside (minimizes) once the game's window is up, and comes back when it closes.
    // (Couch Play games don't do this: the lobby stays on screen with the game in its box.)
    crate::gamewindow::reset();
    let window_log = std::sync::Arc::new(crate::gamewindow::Log::new(launch.log_file.parent().unwrap_or(Path::new("."))));
    {
        let app = app.clone();
        let log = window_log.clone();
        let (pid, id) = (child.id(), id.clone());
        std::thread::spawn(move || {
            crate::gamewindow::game_started(&app, &log, pid, || {
                app.state::<Games>().playing.lock().unwrap_or_else(|e| e.into_inner()).as_deref() == Some(id.as_str())
            });
        });
    }
    let handle = app.clone();
    std::thread::spawn(move || {
        let ok = child.wait().map(|s| s.success()).unwrap_or(false);
        release(&handle);
        let silent = launch.after_exit();
        let _ = handle.emit("game-closed", serde_json::json!({ "id": id, "ok": ok, "silent": silent }));
        crate::gamewindow::game_closed(&handle, &window_log);
        #[cfg(feature = "e2e")]
        if e2e_mode().is_some() {
            let window = crate::gamewindow::LAST.lock().unwrap_or_else(|e| e.into_inner()).clone();
            let result = serde_json::json!({ "ok": ok, "silent": silent, "sound_way": SOUND_WAYS[launch.sound.min(SOUND_WAYS.len() - 1)], "log": launch.log_file, "window": window });
            let _ = fs::write(root.join("e2e-result.json"), result.to_string());
            handle.exit(0);
        }
    });
    Ok(())
}

/// CI's Windows game test only (the "e2e" build, never shipped): with GAMENIGHT_E2E=play the app starts
/// game "1" from the Game Night folder in GAMENIGHT_E2E_ROOT exactly as the Play button would.
#[cfg(feature = "e2e")]
/// With GAMENIGHT_E2E=padgame it first waits (up to 90 s) for a button press in the menus, the way a
/// player would pick their controller, then starts the game.
pub fn e2e_play<R: Runtime>(app: AppHandle<R>) {
    match e2e_mode() {
        Some("play") => e2e_start(app),
        Some("padgame") => {
            std::thread::spawn(move || {
                for _ in 0..900 {
                    if crate::pads::LAST_USED.lock().unwrap_or_else(|e| e.into_inner()).is_some() {
                        break;
                    }
                    std::thread::sleep(std::time::Duration::from_millis(100));
                }
                e2e_start(app);
            });
        }
        _ => {}
    }
}

#[cfg(feature = "e2e")]
fn e2e_start<R: Runtime>(app: AppHandle<R>) {
    let root = std::env::var("GAMENIGHT_E2E_ROOT").unwrap_or_default();
    let settings: PlaySettings = serde_json::from_value(serde_json::json!({
        "screen": "4:3", "picture": "scanlines", "rewind": false, "fastForward": false, "showFps": true
    }))
    .expect("settings");
    if let Err(e) = play_game(app.clone(), root.clone(), "1".into(), settings) {
        let _ = fs::write(PathBuf::from(&root).join("e2e-result.json"), serde_json::json!({ "error": e }).to_string());
        app.exit(4);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn safe_file_names() {
        assert_eq!(safe_name("Super Mario Bros. (World).nes", "1"), "Super Mario Bros. (World).nes");
        assert_eq!(safe_name("../../evil.nes", "1"), "evil.nes");
        assert_eq!(safe_name("C:\\Windows\\x.sfc", "1"), "x.sfc");
        assert_eq!(safe_name("a:b*c?.nes", "1"), "a_b_c_.nes");
        assert_eq!(safe_name("CON.nes", "7"), "game-7.bin");
        assert_eq!(safe_name("", "7"), "game-7.bin");
        assert_eq!(safe_name("...", "7"), "game-7.bin");
        assert_eq!(safe_name(".hidden.nes", "7"), "hidden.nes");
        let long = format!("{}.sfc", "x".repeat(300));
        assert_eq!(safe_name(&long, "1"), format!("{}.sfc", "x".repeat(100)));
    }

    #[test]
    fn only_listed_files_inside_the_folder_count() {
        let root = std::env::temp_dir().join(format!("gn-games-{}", std::process::id())).join("Game Night");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join("nes")).unwrap();
        fs::write(root.join("nes").join("a.nes"), b"12345").unwrap();
        let mut idx = HashMap::new();
        idx.insert("1".to_string(), Entry { console: "nes".into(), file: "a.nes".into(), size: 5 });
        idx.insert("2".to_string(), Entry { console: "nes".into(), file: "missing.nes".into(), size: 5 });
        idx.insert("3".to_string(), Entry { console: "nes".into(), file: "a.nes".into(), size: 9 });
        idx.insert("4".to_string(), Entry { console: "nes".into(), file: "../a.nes".into(), size: 5 });
        idx.insert("5".to_string(), Entry { console: "downloads".into(), file: "a.nes".into(), size: 5 });
        write_index(&root, &idx).unwrap();
        let got = installed_games(root.to_string_lossy().to_string());
        assert_eq!(got.keys().collect::<Vec<_>>(), vec!["1"]);
        remove_game(root.to_string_lossy().to_string(), "1".into()).unwrap();
        assert!(!root.join("nes").join("a.nes").exists());
        assert!(installed_games(root.to_string_lossy().to_string()).is_empty());
        assert!(installed_games("/tmp/not-ours".into()).is_empty());
        let _ = fs::remove_dir_all(root.parent().unwrap());
    }

    #[test]
    fn player_settings_lock_the_menus() {
        let p = ConfigPaths {
            player: PathBuf::from("/p"),
            logs: PathBuf::from("/c/logs"),
            saves: PathBuf::from("/g/saves/nes"),
            states: PathBuf::from("/g/states/nes"),
            system: PathBuf::from("/g/bios"),
            cache: PathBuf::from("/c"),
        };
        let s = PlaySettings { screen: "4:3".into(), picture: "scanlines".into(), rewind: true, fast_forward: false, show_fps: false };
        let pads = crate::controllers::Plan { player1: Some("045e:02ff".into()), parked: vec!["1532:02a7".into()], joypad_driver: "dinput" };
        let cfg = retroarch_config(&p, &s, 0, &pads, None);
        for want in [
            "audio_driver = \"xaudio\"",
            "input_max_users = \"4\"",
            "input_player1_device_reservation_type = \"1\"",
            "input_player1_reserved_device = \"045e:02ff\"",
            "input_player5_device_reservation_type = \"2\"",
            "input_player5_reserved_device = \"1532:02a7\"",
            "input_joypad_driver = \"dinput\"",
            "audio_sync = \"true\"",
            "audio_mute_enable = \"false\"",
            "vrr_runloop_enable = \"false\"",
            "log_dir = \"/c/logs\"",
            "input_menu_toggle = \"nul\"",
            "input_menu_toggle_gamepad_combo = \"0\"",
            "input_desktop_menu_toggle = \"nul\"",
            "config_save_on_exit = \"false\"",
            "input_exit_emulator = \"escape\"",
            "aspect_ratio_index = \"0\"",
            "video_shader_enable = \"true\"",
            "input_hold_fast_forward = \"nul\"",
            "savefile_directory = \"/g/saves/nes\"",
        ] {
            assert!(cfg.contains(want), "missing {want}");
        }
        // No RetroArch pop-ups (quiet_retroarch.cfg), each setting written once.
        for want in [
            "video_font_enable = \"false\"",
            "menu_show_load_content_animation = \"false\"",
            "notification_show_autoconfig = \"false\"",
            "notification_show_netplay_extra = \"false\"",
            "notification_show_save_state = \"false\"",
            "notification_show_fast_forward = \"false\"",
        ] {
            assert!(cfg.contains(want), "missing {want}");
        }
        assert_eq!(cfg.matches("video_font_enable").count(), 1);
        assert_eq!(quiet_lines(false).count(), 15);
        let fps = PlaySettings { show_fps: true, ..s.clone() };
        let cfg_fps = retroarch_config(&p, &fps, 0, &pads, None);
        assert!(cfg_fps.contains("video_font_enable = \"true\""));
        assert!(cfg_fps.contains("notification_show_autoconfig = \"false\""));
        let pixel = PlaySettings { screen: "pixel".into(), picture: "sharp".into(), ..s };
        let cfg = retroarch_config(&p, &pixel, 1, &Default::default(), None);
        assert!(cfg.contains("input_player1_device_reservation_type = \"0\""));
        assert!(cfg.contains("input_joypad_driver = \"xinput\""));
        assert!(cfg.contains("audio_driver = \"wasapi\"") && cfg.contains("audio_wasapi_exclusive_mode = \"false\""));
        let last = retroarch_config(&p, &pixel, 9, &Default::default(), None);
        assert!(last.contains("audio_driver = \"dsound\"") && last.contains("vrr_runloop_enable = \"true\""));
        assert!(sound_failed("[ERROR] Failed to initialize audio driver. Will continue without audio.\n"));
        assert!(!sound_failed("[INFO] [Audio]: Started synchronous audio driver.\n"));
        assert!(cfg.contains("aspect_ratio_index = \"22\"") && cfg.contains("video_scale_integer = \"true\""));
        assert!(cfg.contains("video_shader_enable = \"false\""));
        assert!(cfg.contains("video_fullscreen = \"true\"") && cfg.contains("network_cmd_enable = \"false\""));
        assert!(!cfg.contains("netplay_request_device"));
    }

    fn paths() -> ConfigPaths {
        ConfigPaths {
            player: PathBuf::from("/p"),
            logs: PathBuf::from("/c/logs"),
            saves: PathBuf::from("/g/saves/snes"),
            states: PathBuf::from("/g/states/snes"),
            system: PathBuf::from("/g/bios"),
            cache: PathBuf::from("/c"),
        }
    }

    fn line(cfg: &str, key: &str) -> Vec<String> {
        cfg.lines().filter(|l| l.starts_with(&format!("{key} = "))).map(String::from).collect()
    }

    #[test]
    fn couch_play_settings() {
        let s = PlaySettings { screen: "4:3".into(), picture: "sharp".into(), rewind: true, fast_forward: true, show_fps: false };
        let host = Netplay {
            host: true,
            seat: Some(1),
            cmd_port: 55123,
            remaps: Some(PathBuf::from("/cfg/couch-remaps")),
            nickname: "Jay\"den = <x>".into(),
            window: Some((10, 20, 640, 480)),
            args: vec!["--host".into(), "--port".into(), "55555".into()],
        };
        let cfg = retroarch_config(&paths(), &s, 0, &Default::default(), Some(&host));
        for want in [
            "netplay_public_announce = \"false\"",
            "netplay_use_mitm_server = \"false\"",
            "netplay_nat_traversal = \"false\"",
            "netplay_max_connections = \"8\"",
            "netplay_start_as_spectator = \"false\"",
            "netplay_request_device_p1 = \"true\"",
            "netplay_request_device_p2 = \"false\"",
            "netplay_request_device_p16 = \"false\"",
            "network_cmd_enable = \"true\"",
            "network_cmd_port = \"55123\"",
            "video_fullscreen = \"false\"",
            "video_window_show_decorations = \"false\"",
            "input_toggle_fullscreen = \"nul\"",
            "pause_nonactive = \"false\"",
            "auto_remaps_enable = \"true\"",
            "input_remapping_directory = \"/cfg/couch-remaps\"",
            "rewind_enable = \"false\"",
            "input_hold_fast_forward = \"nul\"",
            "video_windowed_position_x = \"10\"",
            "video_windowed_position_width = \"640\"",
            "netplay_nickname = \"Jayden  x\"",
        ] {
            assert!(cfg.contains(want), "missing {want}");
        }
        // Each setting once: Couch Play's values replace the normal ones instead of adding a second line.
        for key in ["video_fullscreen", "network_cmd_enable", "auto_remaps_enable", "rewind_enable", "netplay_nat_traversal"] {
            assert_eq!(line(&cfg, key).len(), 1, "{key}");
        }

        let watcher = Netplay { host: false, seat: None, cmd_port: 1, nickname: "".into(), ..Default::default() };
        let cfg = retroarch_config(&paths(), &s, 0, &Default::default(), Some(&watcher));
        assert!(cfg.contains("netplay_start_as_spectator = \"true\""));
        assert!(cfg.contains("netplay_nickname = \"Player\""));
        assert!(cfg.contains("auto_remaps_enable = \"false\"")); // NES: no remap file
        assert!(!cfg.contains("netplay_request_device_p1 = \"true\""));

        let p3 = Netplay { seat: Some(3), ..watcher };
        let cfg = retroarch_config(&paths(), &s, 0, &Default::default(), Some(&p3));
        assert!(cfg.contains("netplay_start_as_spectator = \"false\""));
        assert!(cfg.contains("netplay_request_device_p3 = \"true\""));
        assert_eq!(line(&cfg, "netplay_request_device_p1"), vec!["netplay_request_device_p1 = \"false\""]);
    }

    #[test]
    fn snes_multitap_remap_file() {
        let dir = std::env::temp_dir().join(format!("gn-remap-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        write_snes_remap(&dir).unwrap();
        let text = fs::read_to_string(dir.join("Snes9x").join("Snes9x.rmp")).unwrap();
        assert_eq!(text, "input_libretro_device_p1 = \"1\"\ninput_libretro_device_p2 = \"257\"\n");
        let _ = fs::remove_dir_all(&dir);
    }
}
