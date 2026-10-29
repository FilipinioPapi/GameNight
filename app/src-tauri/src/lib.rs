//! Game Night's Windows side: the window, plus a few small jobs the screens can't do
//! themselves (finding drives, measuring and clearing the games folder, and signing in:
//! see account.rs).
//!
//! Safety rules for files:
//! - Game Night only ever works inside its own folder, named "Game Night".
//! - "Clear my games" deletes only the console folders Game Night made in there
//!   (nes, snes, ...), never anything else, and never follows shortcuts/links out of it.

mod account;
mod controllers;
mod covers;
mod games;
mod pads;
mod retroports;
mod updater;

use serde::Serialize;
use std::fs;
use std::path::{Component, Path, PathBuf};
use sysinfo::Disks;

/// The name of the folder Game Night keeps games in.
const FOLDER_NAME: &str = "Game Night";

/// The only folders "Clear my games" may delete: one per console, plus unfinished downloads.
pub(crate) const CONSOLE_FOLDERS: &[&str] = &[
    "nes",
    "snes",
    "gen",
    "gb",
    "gba",
    "arc",
    "ps1",
    "n64",
    "gc",
    "wii",
    "ps2",
    "downloads",
];

#[derive(Serialize)]
pub struct FolderChoice {
    path: String,
    drive: String,
    label: String,
    free: u64,
    total: u64,
    recommended: bool,
}

/// Suggests a games folder on each fixed drive, best one first.
#[tauri::command]
fn suggest_folders() -> Vec<FolderChoice> {
    let home = dirs::home_dir().unwrap_or_default();
    let disks = Disks::new_with_refreshed_list();
    let mut out: Vec<FolderChoice> = disks
        .list()
        .iter()
        .filter(|d| !d.is_removable() && d.total_space() >= 16 * 1024 * 1024 * 1024)
        .map(|d| {
            let mount = d.mount_point().to_path_buf();
            let is_system = home.starts_with(&mount) && mount.components().count() <= 2;
            let path = if is_system {
                home.join(FOLDER_NAME)
            } else {
                mount.join("Games").join(FOLDER_NAME)
            };
            let drive = mount
                .to_string_lossy()
                .trim_end_matches(['\\', '/'])
                .to_string();
            let name = d.name().to_string_lossy().to_string();
            let label = if is_system {
                "Windows drive".to_string()
            } else if name.is_empty() {
                "Drive".to_string()
            } else {
                name
            };
            FolderChoice {
                path: path.to_string_lossy().to_string(),
                drive,
                label,
                free: d.available_space(),
                total: d.total_space(),
                recommended: false,
            }
        })
        .collect();
    // Prefer the drive with the most free space, but only move off the Windows drive
    // when another drive has a decent amount of room.
    out.sort_by_key(|c| std::cmp::Reverse(c.free));
    if let Some(best) = out
        .iter()
        .position(|c| c.free >= 50 * 1024 * 1024 * 1024)
        .or(if out.is_empty() { None } else { Some(0) })
    {
        out[best].recommended = true;
        let c = out.remove(best);
        out.insert(0, c);
    }
    out
}

/// The folder actually used: always a "Game Night" folder inside the one picked.
#[tauri::command]
fn games_folder(picked: String) -> Result<String, String> {
    let p = PathBuf::from(&picked);
    if !p.is_absolute() {
        return Err("Pick a full folder path.".into());
    }
    if is_ours(&p) {
        return Ok(picked);
    }
    Ok(p.join(FOLDER_NAME).to_string_lossy().to_string())
}

/// Total size of everything in the games folder, in bytes. Missing folder = 0.
#[tauri::command]
fn folder_size(path: String) -> u64 {
    fn walk(p: &Path) -> u64 {
        let Ok(entries) = fs::read_dir(p) else {
            return 0;
        };
        entries
            .flatten()
            .map(|e| match e.path().symlink_metadata() {
                Ok(m) if m.is_dir() => walk(&e.path()),
                Ok(m) if m.is_file() => m.len(),
                _ => 0, // links and anything odd are skipped
            })
            .sum()
    }
    let p = PathBuf::from(path);
    if is_ours(&p) {
        walk(&p)
    } else {
        0
    }
}

/// Deletes downloaded games: only Game Night's own console folders inside its own folder.
#[tauri::command]
fn clear_games(path: String) -> Result<(), String> {
    let root = PathBuf::from(&path);
    if !is_ours(&root) {
        return Err("That isn't a Game Night folder, so nothing was deleted.".into());
    }
    for name in CONSOLE_FOLDERS {
        let dir = root.join(name);
        match dir.symlink_metadata() {
            // Only real folders. A link pointing elsewhere is left alone.
            Ok(m) if m.is_dir() && !m.file_type().is_symlink() => {
                fs::remove_dir_all(&dir).map_err(|e| format!("Couldn't delete {name}: {e}"))?;
            }
            _ => {}
        }
    }
    Ok(())
}

/// True only for a full path whose last part is "Game Night" and that isn't a drive root.
pub(crate) fn is_ours(p: &Path) -> bool {
    p.is_absolute()
        && !p.components().any(|c| matches!(c, Component::ParentDir))
        && p.file_name()
            .map(|n| n.to_string_lossy().eq_ignore_ascii_case(FOLDER_NAME))
            .unwrap_or(false)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    use tauri::Manager;
    tauri::Builder::default()
        // Only one Game Night window at a time: opening it again (or a gamenight:// link)
        // goes to the first one.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .manage(account::Account::default())
        .manage(updater::Updates::default())
        .manage(games::Games::default())
        // Box art: the window may only show pictures from here, which only fetches from our server.
        .register_asynchronous_uri_scheme_protocol("gncover", |ctx, request, responder| {
            let app = ctx.app_handle().clone();
            let path = request.uri().path().to_string();
            tauri::async_runtime::spawn(async move {
                let resp = match covers::cover(&app, &path).await {
                    Some((ctype, body)) => tauri::http::Response::builder()
                        .header("Content-Type", ctype)
                        .header("Cache-Control", "max-age=86400")
                        .body(body),
                    None => tauri::http::Response::builder().status(404).body(Vec::new()),
                };
                responder.respond(resp.expect("response"));
            });
        })
        .setup(|app| {
            use tauri_plugin_deep_link::DeepLinkExt;
            // The installer registers gamenight:// links; this covers test builds.
            #[cfg(all(debug_assertions, any(windows, target_os = "linux")))]
            let _ = app.deep_link().register_all();
            pads::start(app.handle().clone());
            #[cfg(feature = "e2e")]
            updater::e2e_autoupdate(app.handle().clone());
            #[cfg(feature = "e2e")]
            games::e2e_play(app.handle().clone());
            let handle = app.handle().clone();
            app.deep_link().on_open_url(move |event| {
                for link in event.urls() {
                    handle.state::<account::Account>().handle_link(&handle, &link);
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            covers::cover_cache_size,
            games::installed_games,
            games::download_game,
            games::cancel_download,
            games::remove_game,
            games::play_game,
            controllers::list_controllers,
            controllers::save_controllers,
            controllers::steam_running,
            pads::pad_state,
            pads::pad_note,
            covers::clear_cover_cache,
            suggest_folders,
            games_folder,
            folder_size,
            clear_games,
            account::account_status,
            account::set_server,
            account::sign_in,
            account::sign_out,
            account::fetch_games,
            updater::check_update,
            updater::install_update
        ])
        .run(tauri::generate_context!())
        .expect("Game Night couldn't start");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_game_night_folders_count_as_ours() {
        let base = std::env::temp_dir();
        assert!(is_ours(&base.join("Game Night")));
        assert!(is_ours(&base.join("game night")));
        assert!(!is_ours(&base));
        assert!(!is_ours(&base.join("Games")));
        assert!(!is_ours(Path::new("Game Night")));
        assert!(!is_ours(&base.join("x").join("..").join("Game Night")));
    }

    #[test]
    fn clear_games_only_removes_console_folders() {
        let root = std::env::temp_dir()
            .join(format!("gn-test-{}", std::process::id()))
            .join("Game Night");
        fs::create_dir_all(root.join("snes")).unwrap();
        fs::write(root.join("snes").join("game.sfc"), b"x").unwrap();
        fs::create_dir_all(root.join("my stuff")).unwrap();
        fs::write(root.join("notes.txt"), b"keep").unwrap();
        clear_games(root.to_string_lossy().to_string()).unwrap();
        assert!(!root.join("snes").exists());
        assert!(root.join("my stuff").exists());
        assert!(root.join("notes.txt").exists());
        fs::remove_dir_all(root.parent().unwrap()).unwrap();
    }

    #[test]
    fn clear_games_refuses_other_folders() {
        let other = std::env::temp_dir();
        assert!(clear_games(other.to_string_lossy().to_string()).is_err());
    }
}
