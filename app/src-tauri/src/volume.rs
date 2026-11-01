//! Game sound volume, set from the in-game menu's GAME tab (board IG4). This PC only: in Couch Play it
//! changes your own speakers, never your friends'.
//!
//! - Saved in Game Night's settings folder (player/volume.txt) as a percentage, 10 to 100 in steps of 10.
//! - A game starts at that volume (RetroArch's `audio_volume`, in dB).
//! - While a game runs, Game Night moves it with RetroArch's VOLUME_UP / VOLUME_DOWN commands on its local
//!   command port. Each one is 0.5 dB (RetroArch 1.22.2, command.c). RetroArch writes the new volume to its
//!   log ("Audio volume: -6.0 dB"), so Game Night reads the log to know where it really is and corrects
//!   any step that got lost.

use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Duration;
use tauri::{AppHandle, Manager, Runtime};

pub const LOWEST: u8 = 10;
pub const LOUDEST: u8 = 100;
pub const STEP: u8 = 10;

/// The volume each RetroArch started with (command port, half-dB units), until its log says otherwise.
static STARTED: Mutex<Option<(u16, i32)>> = Mutex::new(None);
/// One change at a time.
static APPLY: Mutex<()> = Mutex::new(());
/// The newest wish (command port, percentage); older ones still waiting are skipped.
static WANT: Mutex<Option<(u16, u8)>> = Mutex::new(None);

fn lock<T>(m: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

/// Rounds to a step we offer.
pub fn tidy(pct: i32) -> u8 {
    let p = pct.clamp(LOWEST as i32, LOUDEST as i32);
    (((p + STEP as i32 / 2) / STEP as i32) * STEP as i32) as u8
}

fn file<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    Some(app.path().app_config_dir().ok()?.join("player").join("volume.txt"))
}

/// The saved volume (100% when nothing is saved yet).
pub fn saved<R: Runtime>(app: &AppHandle<R>) -> u8 {
    file(app).and_then(|f| std::fs::read_to_string(f).ok()).and_then(|t| t.trim().parse::<i32>().ok()).map(tidy).unwrap_or(LOUDEST)
}

pub fn save<R: Runtime>(app: &AppHandle<R>, pct: u8) {
    if let Some(f) = file(app) {
        if let Some(dir) = f.parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        let _ = std::fs::write(f, tidy(pct as i32).to_string());
    }
}

/// A percentage as RetroArch's volume, in half-dB units (RetroArch's own step): 100% = 0 dB, 50% = -6 dB, 10% = -20 dB.
pub fn halves(pct: u8) -> i32 {
    let p = tidy(pct as i32) as f64 / 100.0;
    (20.0 * p.log10() * 2.0).round() as i32
}

/// RetroArch's `audio_volume` setting for a game that starts at this percentage.
pub fn config_value(pct: u8) -> String {
    format!("{:.1}", halves(pct) as f64 / 2.0)
}

/// A game started on this command port at this volume.
pub fn started(port: u16, pct: u8) {
    *lock(&STARTED) = Some((port, halves(pct)));
}

/// The last volume RetroArch wrote to its log ("[INFO] [Audio] Audio volume: -6.0 dB."), in half-dB units.
pub fn last_logged(log: &str) -> Option<i32> {
    log.lines().rev().find_map(|l| {
        let i = l.find("volume: ")?;
        let rest = &l[i + "volume: ".len()..];
        let n = rest.split(" dB").next()?.trim();
        n.parse::<f64>().ok().map(|db| (db * 2.0).round() as i32)
    })
}

fn log_file<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    Some(app.path().app_cache_dir().ok()?.join("player").join("logs").join("retroarch.log"))
}

/// Where RetroArch's volume is now (its log, else what it started with).
fn now<R: Runtime>(app: &AppHandle<R>, port: u16) -> Option<i32> {
    let logged = log_file(app).and_then(|f| std::fs::read_to_string(f).ok()).and_then(|t| last_logged(&t));
    logged.or_else(|| lock(&STARTED).filter(|(p, _)| *p == port).map(|(_, h)| h))
}

/// Moves the running game's volume to `pct` (in the background). RetroArch only takes these commands while the
/// game runs (not while its hidden menu is open on your own), so the in-game menu calls this when it closes, and
/// at once in Couch Play (the game keeps running there).
pub fn apply<R: Runtime>(app: &AppHandle<R>, port: u16, pct: u8) {
    if port == 0 {
        return;
    }
    *lock(&WANT) = Some((port, tidy(pct as i32)));
    let app = app.clone();
    std::thread::spawn(move || {
        let _one = lock(&APPLY);
        let Some((port, pct)) = lock(&WANT).take() else { return };
        let target = halves(pct);
        for round in 1..=3 {
            let Some(at) = now(&app, port) else { return };
            let diff = target - at;
            if diff == 0 {
                if round > 1 {
                    crate::ingame::note(&app, &format!("volume {pct}% ({:.1} dB) reached", target as f64 / 2.0));
                }
                return;
            }
            crate::ingame::note(&app, &format!("volume {pct}%: {:.1} dB -> {:.1} dB ({} steps, try {round})", at as f64 / 2.0, target as f64 / 2.0, diff.abs()));
            let cmd = if diff > 0 { "VOLUME_UP" } else { "VOLUME_DOWN" };
            for _ in 0..diff.abs().min(200) {
                crate::ingame::send_cmd(port, cmd);
                // One step a press: RetroArch needs to see the press end before the next one counts.
                std::thread::sleep(Duration::from_millis(60));
            }
            std::thread::sleep(Duration::from_millis(250));
            if lock(&WANT).is_some() {
                return; // a newer wish is waiting: it carries on from here
            }
            // With no log line yet (an old RetroArch log, or none), trust the steps.
            if log_file(&app).and_then(|f| std::fs::read_to_string(f).ok()).and_then(|t| last_logged(&t)).is_none() {
                *lock(&STARTED) = Some((port, target));
            }
        }
        crate::ingame::note(&app, &format!("volume {pct}%: not reached after 3 tries"));
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn percentages_become_half_db_steps() {
        assert_eq!(halves(100), 0);
        assert_eq!(halves(50), -12); // -6 dB
        assert_eq!(halves(10), -40); // -20 dB
        assert_eq!(config_value(80), "-2.0");
        assert_eq!(tidy(0), 10);
        assert_eq!(tidy(140), 100);
        assert_eq!(tidy(64), 60);
        assert_eq!(tidy(65), 70);
    }

    #[test]
    fn reads_the_newest_volume_from_retroarchs_log() {
        let log = "[INFO] [Core] Loaded.\n[INFO] [Audio] Audio volume: -0.5 dB.\n[INFO] x\n[INFO] [Audio] Audio volume: -6.0 dB.\n";
        assert_eq!(last_logged(log), Some(-12));
        assert_eq!(last_logged("[INFO] nothing\n"), None);
        assert_eq!(last_logged("[INFO] [Audio] Audio volume: 2.5 dB.\n"), Some(5));
    }
}
