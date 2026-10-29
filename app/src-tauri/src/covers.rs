//! Box art, through the "gncover" address the window is allowed to show images from.
//!
//! Each cover comes from our server once, then lives in Game Night's own cache folder on this PC,
//! so the library shows instantly next time, even offline. The address carries a short stamp
//! that changes when the cover changes in RomM, so a new cover replaces the old one.

use crate::account::Account;
use std::fs;
use std::path::PathBuf;
use tauri::{AppHandle, Manager, Runtime};

const MAX_BYTES: usize = 8 * 1024 * 1024;

fn folder<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    app.path().app_cache_dir().ok().map(|d| d.join("covers"))
}

/// "/123-abc0" -> ("123", "abc0"). Anything else is refused, so a request can never name another file.
fn parse(path: &str) -> Option<(&str, &str)> {
    let (id, stamp) = path.trim_start_matches('/').split_once('-')?;
    let ok_id = !id.is_empty() && id.len() <= 12 && id.chars().all(|c| c.is_ascii_digit());
    let ok_stamp = !stamp.is_empty() && stamp.len() <= 16 && stamp.chars().all(|c| c.is_ascii_hexdigit());
    (ok_id && ok_stamp).then_some((id, stamp))
}

/// What kind of picture the bytes are. Only these four are shown; anything else is ignored.
fn kind(b: &[u8]) -> Option<&'static str> {
    if b.starts_with(b"\x89PNG\r\n\x1a\n") {
        Some("image/png")
    } else if b.starts_with(&[0xFF, 0xD8, 0xFF]) {
        Some("image/jpeg")
    } else if b.len() > 12 && &b[0..4] == b"RIFF" && &b[8..12] == b"WEBP" {
        Some("image/webp")
    } else if b.starts_with(b"GIF87a") || b.starts_with(b"GIF89a") {
        Some("image/gif")
    } else {
        None
    }
}

fn save(dir: &PathBuf, id: &str, name: &str, bytes: &[u8]) {
    if fs::create_dir_all(dir).is_err() {
        return;
    }
    // Write to a temporary name first so a half-written file is never shown.
    let mut r = [0u8; 6];
    let _ = getrandom::fill(&mut r);
    let tmp = dir.join(format!("{name}.{}.part", r.iter().map(|b| format!("{b:02x}")).collect::<String>()));
    if fs::write(&tmp, bytes).is_ok() && fs::rename(&tmp, dir.join(name)).is_ok() {
        // Drop older versions of this game's cover.
        if let Ok(list) = fs::read_dir(dir) {
            for e in list.flatten() {
                let n = e.file_name().to_string_lossy().to_string();
                if n != name && n.split_once('-').map(|(i, _)| i == id).unwrap_or(false) {
                    let _ = fs::remove_file(e.path());
                }
            }
        }
    } else {
        let _ = fs::remove_file(&tmp);
    }
}

pub async fn cover<R: Runtime>(app: &AppHandle<R>, path: &str) -> Option<(&'static str, Vec<u8>)> {
    let (id, stamp) = parse(path)?;
    let name = format!("{id}-{stamp}");
    let dir = folder(app);
    if let Some(d) = &dir {
        if let Ok(bytes) = fs::read(d.join(&name)) {
            if let Some(k) = kind(&bytes) {
                return Some((k, bytes));
            }
        }
    }
    let resp = app.state::<Account>().get(app, &format!("/api/games/{id}/cover")).await.ok()?;
    let bytes = resp.bytes().await.ok()?;
    if bytes.len() > MAX_BYTES {
        return None;
    }
    let k = kind(&bytes)?;
    if let Some(d) = &dir {
        save(d, id, &name, &bytes);
    }
    Some((k, bytes.to_vec()))
}

fn size_of(dir: &PathBuf) -> u64 {
    fs::read_dir(dir)
        .map(|l| l.flatten().filter_map(|e| e.metadata().ok()).filter(|m| m.is_file()).map(|m| m.len()).sum())
        .unwrap_or(0)
}

/// How much space saved box art uses, in bytes.
#[tauri::command]
pub fn cover_cache_size<R: Runtime>(app: AppHandle<R>) -> u64 {
    folder(&app).map(|d| size_of(&d)).unwrap_or(0)
}

/// Deletes saved box art. It downloads again as you browse.
#[tauri::command]
pub fn clear_cover_cache<R: Runtime>(app: AppHandle<R>) -> Result<(), String> {
    let Some(dir) = folder(&app) else { return Ok(()) };
    match fs::remove_dir_all(&dir) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err("Couldn't clear the saved box art. Try again in a moment.".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_plain_cover_names() {
        assert_eq!(parse("/12-ab09"), Some(("12", "ab09")));
        assert_eq!(parse("/12-0"), Some(("12", "0")));
        assert!(parse("/12").is_none());
        assert!(parse("/12-").is_none());
        assert!(parse("/../x-1").is_none());
        assert!(parse("/12-ab/../..").is_none());
        assert!(parse("/12-xyz").is_none());
        assert!(parse("/1234567890123-1").is_none());
    }

    #[test]
    fn knows_picture_kinds() {
        assert_eq!(kind(b"\x89PNG\r\n\x1a\nrest"), Some("image/png"));
        assert_eq!(kind(&[0xFF, 0xD8, 0xFF, 0xE0]), Some("image/jpeg"));
        assert_eq!(kind(b"RIFF\0\0\0\0WEBPVP8 "), Some("image/webp"));
        assert_eq!(kind(b"<svg xmlns="), None);
        assert_eq!(kind(b""), None);
    }

    #[test]
    fn saving_replaces_the_old_version_only() {
        let dir = std::env::temp_dir().join(format!("gn-covers-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        save(&dir, "7", "7-aa", b"one");
        save(&dir, "70", "70-aa", b"other game");
        save(&dir, "7", "7-bb", b"two");
        let mut names: Vec<String> = fs::read_dir(&dir).unwrap().flatten().map(|e| e.file_name().to_string_lossy().to_string()).collect();
        names.sort();
        assert_eq!(names, vec!["7-bb", "70-aa"]);
        let _ = fs::remove_dir_all(&dir);
    }
}
