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
const CORES: &[(&str, &str)] = &[("nes", "fceumm_libretro.dll"), ("snes", "snes9x_libretro.dll")];

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

#[derive(Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct PlaySettings {
    screen: String,
    picture: String,
    rewind: bool,
    fast_forward: bool,
    show_fps: bool,
}

#[derive(Serialize, Clone)]
struct Progress {
    id: String,
    done: u64,
    total: u64,
}

fn root_of(path: &str) -> Result<PathBuf, String> {
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

fn read_index(root: &Path) -> HashMap<String, Entry> {
    fs::read_to_string(index_path(root)).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or_default()
}

fn write_index(root: &Path, idx: &HashMap<String, Entry>) -> Result<(), String> {
    let text = serde_json::to_string_pretty(idx).map_err(|_| "Couldn't save the game list.")?;
    let tmp = root.join("library.json.part");
    fs::write(&tmp, text).and_then(|_| fs::rename(&tmp, index_path(root))).map_err(|_| "Couldn't save the game list.".to_string())
}

/// Path of a game's file, only if it is really there, inside its console folder, at the right size.
fn game_file(root: &Path, e: &Entry) -> Option<PathBuf> {
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
    pub saves: PathBuf,
    pub states: PathBuf,
    pub system: PathBuf,
    pub cache: PathBuf,
}

/// RetroArch's settings for one game. Menus, online features and anything that could take a player
/// out of the game are switched off. Quitting: Esc, or L1 + R1 + Start + Select on a controller.
pub fn retroarch_config(p: &ConfigPaths, s: &PlaySettings) -> String {
    let path = |p: &Path| p.to_string_lossy().replace('"', "");
    let yes = |b: bool| if b { "true" } else { "false" };
    let (aspect, integer) = match s.screen.as_str() {
        "pixel" => (22, true),   // the console's own shape, sharp whole-pixel scaling
        "stretch" => (24, false), // fill the screen
        _ => (0, false),          // 4:3, like an old TV
    };
    let lines: Vec<(&str, String)> = vec![
        // Never write these settings back, never show menus or online extras.
        ("config_save_on_exit", "false".into()),
        ("menu_driver", "rgui".into()),
        ("input_menu_toggle", "nul".into()),
        ("input_menu_toggle_gamepad_combo", "0".into()),
        ("input_desktop_menu_toggle", "nul".into()),
        ("ui_companion_enable", "false".into()),
        ("ui_companion_start_on_boot", "false".into()),
        ("desktop_menu_enable", "false".into()),
        ("menu_show_online_updater", "false".into()),
        ("menu_show_core_updater", "false".into()),
        ("network_cmd_enable", "false".into()),
        ("stdin_cmd_enable", "false".into()),
        ("netplay_nat_traversal", "false".into()),
        ("cheevos_enable", "false".into()),
        ("discord_allow", "false".into()),
        ("history_list_enable", "false".into()),
        ("game_specific_options", "false".into()),
        ("auto_overrides_enable", "false".into()),
        ("auto_remaps_enable", "false".into()),
        ("auto_shaders_enable", "false".into()),
        ("log_to_file", "false".into()),
        // Quitting goes straight back to Game Night.
        ("input_exit_emulator", "escape".into()),
        ("quit_press_twice", "false".into()),
        ("input_quit_gamepad_combo", "3".into()),
        // Screen
        ("video_driver", "d3d11".into()),
        ("video_fullscreen", "true".into()),
        ("video_windowed_fullscreen", "true".into()),
        ("aspect_ratio_index", aspect.to_string()),
        ("video_scale_integer", yes(integer).into()),
        ("video_smooth", yes(s.picture == "smooth").into()),
        ("video_shader_enable", yes(s.picture == "scanlines").into()),
        ("fps_show", yes(s.show_fps).into()),
        ("video_font_enable", "true".into()),
        // Rewind and fast forward (keyboard: R and Space; controllers come with controller setup)
        ("rewind_enable", yes(s.rewind).into()),
        ("input_rewind", if s.rewind { "r" } else { "nul" }.into()),
        ("input_hold_fast_forward", if s.fast_forward { "space" } else { "nul" }.into()),
        ("input_toggle_fast_forward", "nul".into()),
        // Controllers
        ("input_joypad_driver", "xinput".into()),
        ("input_autodetect_enable", "true".into()),
        ("joypad_autoconfig_dir", path(&p.player.join("autoconfig"))),
        // Folders: RetroArch's own bits, and saves in the Game Night folder.
        ("libretro_directory", path(&p.player.join("cores"))),
        ("savefile_directory", path(&p.saves)),
        ("savestate_directory", path(&p.states)),
        ("system_directory", path(&p.system)),
        ("cache_directory", path(&p.cache)),
        ("sort_savefiles_enable", "false".into()),
        ("sort_savestates_enable", "false".into()),
    ];
    let mut out = String::from("# Written by Game Night for each game. Changes here are replaced.\n");
    for (k, v) in lines {
        out.push_str(&format!("{k} = \"{v}\"\n"));
    }
    out
}

/// Starts a downloaded game fullscreen. "game-closed" fires when the player quits.
#[tauri::command]
pub fn play_game<R: Runtime>(app: AppHandle<R>, root: String, id: String, settings: PlaySettings) -> Result<(), String> {
    let root = root_of(&root)?;
    let entry = read_index(&root).remove(&id).ok_or("That game isn't on this PC yet.")?;
    let rom = game_file(&root, &entry).ok_or("That game's file is missing. Download it again.")?;
    let core = CORES.iter().find(|(c, _)| *c == entry.console).map(|(_, f)| *f).ok_or("That console can't be played yet.")?;
    let player = player_dir(&app).ok_or("Game Night's player is missing. Reinstall Game Night.")?;
    let exe = player.join(if cfg!(windows) { "retroarch.exe" } else { "retroarch" });
    let core_path = player.join("cores").join(core);
    if !exe.is_file() || !core_path.is_file() {
        return Err("Game Night's player is missing. Reinstall Game Night.".into());
    }
    {
        let state = app.state::<Games>();
        let mut playing = state.playing.lock().unwrap_or_else(|e| e.into_inner());
        if playing.is_some() {
            return Err("A game is already running.".into());
        }
        *playing = Some(id.clone());
    }

    let cfg_dir = app.path().app_config_dir().map_err(|_| "No settings folder.")?.join("player");
    let paths = ConfigPaths {
        player: player.clone(),
        saves: root.join("saves").join(&entry.console),
        states: root.join("states").join(&entry.console),
        system: root.join("bios"),
        cache: app.path().app_cache_dir().map_err(|_| "No cache folder.")?.join("player"),
    };
    let started = (|| -> Result<std::process::Child, String> {
        for d in [&cfg_dir, &paths.saves, &paths.states, &paths.system, &paths.cache] {
            fs::create_dir_all(d).map_err(|_| "Couldn't make the saves folder.")?;
        }
        let cfg = cfg_dir.join("retroarch.cfg");
        fs::write(&cfg, retroarch_config(&paths, &settings)).map_err(|_| "Couldn't write the player settings.")?;
        let mut cmd = std::process::Command::new(&exe);
        cmd.current_dir(&player).arg("--config").arg(&cfg).arg("-L").arg(&core_path).arg("--fullscreen");
        if settings.picture == "scanlines" {
            cmd.arg("--set-shader").arg(player.join("shaders").join("scanlines.slangp"));
        }
        cmd.arg(&rom);
        cmd.spawn().map_err(|_| "Couldn't start the game.".to_string())
    })();
    let mut child = match started {
        Ok(c) => c,
        Err(e) => {
            *app.state::<Games>().playing.lock().unwrap_or_else(|e| e.into_inner()) = None;
            return Err(e);
        }
    };
    let handle = app.clone();
    std::thread::spawn(move || {
        let ok = child.wait().map(|s| s.success()).unwrap_or(false);
        *handle.state::<Games>().playing.lock().unwrap_or_else(|e| e.into_inner()) = None;
        let _ = handle.emit("game-closed", serde_json::json!({ "id": id, "ok": ok }));
        if let Some(w) = handle.get_webview_window("main") {
            let _ = w.unminimize();
            let _ = w.set_focus();
        }
    });
    Ok(())
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
            saves: PathBuf::from("/g/saves/nes"),
            states: PathBuf::from("/g/states/nes"),
            system: PathBuf::from("/g/bios"),
            cache: PathBuf::from("/c"),
        };
        let s = PlaySettings { screen: "4:3".into(), picture: "scanlines".into(), rewind: true, fast_forward: false, show_fps: false };
        let cfg = retroarch_config(&p, &s);
        for want in [
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
        let pixel = PlaySettings { screen: "pixel".into(), picture: "sharp".into(), ..s };
        let cfg = retroarch_config(&p, &pixel);
        assert!(cfg.contains("aspect_ratio_index = \"22\"") && cfg.contains("video_scale_integer = \"true\""));
        assert!(cfg.contains("video_shader_enable = \"false\""));
    }
}
