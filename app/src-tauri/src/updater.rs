//! Updates, the same way Roof Rage does them (RoofRageRE re/UPDATER_SPEC.md, "Signed updates").
//!
//! The NAS publishes https://updates.jjsnas.xyz/gamenight/latest.json. It holds a file list signed with
//! Jayden's key, which never leaves the NAS. The app has the public half built in and ignores any list
//! whose signature doesn't check out, so nobody who gets into the web server or the proxy can push
//! something to friends' PCs. The signed list names the app ("gamenight"), so a Roof Rage list (same
//! key) can never be taken for a Game Night update, and the installer's SHA-256 is inside the signed
//! part, so one signature covers the download too. Only newer versions are offered.

use p256::ecdsa::{signature::Verifier, Signature, VerifyingKey};
use p256::pkcs8::DecodePublicKey;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::sync::Mutex;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager, Runtime};

use base64::{engine::general_purpose::STANDARD, Engine};

pub const UPDATES: &str = "https://updates.jjsnas.xyz/gamenight/";

/// Test builds only (debug, or the "e2e" build CI uses for its Windows update test, never shipped):
/// GAMENIGHT_UPDATE_URL points at a test server. Release builds always use UPDATES.
fn base() -> String {
    #[cfg(any(debug_assertions, feature = "e2e"))]
    if let Ok(u) = std::env::var("GAMENIGHT_UPDATE_URL") {
        return u;
    }
    UPDATES.to_string()
}

/// Test builds only (as above): GAMENIGHT_UPDATE_KEY swaps in a throwaway key. Release builds always use PUBLIC_KEY.
fn key() -> String {
    #[cfg(any(debug_assertions, feature = "e2e"))]
    if let Ok(k) = std::env::var("GAMENIGHT_UPDATE_KEY") {
        return k;
    }
    PUBLIC_KEY.to_string()
}

/// Jayden's public key: the same one Roof Rage has built in (made on his NAS 2026-10-28).
pub const PUBLIC_KEY: &str = "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE4zX4sOgPfXg0T4Ok42sTYgDvmX5F\
3w9ultC1kbHtnGWHRSkWXte+B+8jZxpppMBKcb6VQW0G7xHdqItygt83xw==";

const APP_NAME: &str = "gamenight";
const MAX_INSTALLER: u64 = 200 * 1024 * 1024;

#[derive(Clone, Deserialize)]
pub struct FileEntry {
    pub path: String,
    pub size: u64,
    pub sha256: String,
}

#[derive(Clone, Deserialize)]
pub struct Manifest {
    pub app: String,
    pub version: String,
    #[serde(default)]
    pub notes: Vec<String>,
    pub file: FileEntry,
}

#[derive(Clone, Serialize)]
pub struct UpdateInfo {
    version: String,
    notes: Vec<String>,
    size: u64,
}

#[derive(Default)]
pub struct Updates {
    found: Mutex<Option<Manifest>>,
    /// The checked download, waiting for start_install.
    ready: Mutex<Option<(Manifest, std::path::PathBuf)>>,
    /// Set at start-up when this start is the end of an update: the version now running.
    pub came_back: Mutex<Option<String>>,
}

#[derive(Clone, Serialize)]
struct Progress {
    done: u64,
    total: u64,
}

/// "0.2.0" -> (0, 2, 0). Unreadable parts count as 0.
pub fn number(v: &str) -> (u64, u64, u64) {
    let mut p = v.trim().trim_start_matches(['v', 'V']).split('.').map(|x| x.parse::<u64>().unwrap_or(0));
    (p.next().unwrap_or(0), p.next().unwrap_or(0), p.next().unwrap_or(0))
}

pub fn newer(candidate: &str, current: &str) -> bool {
    number(candidate) > number(current)
}

/// The file list from latest.json, only if Jayden's key signed it and it is for Game Night.
pub fn parse_signed(json: &str, public_key: &str) -> Result<Manifest, String> {
    #[derive(Deserialize)]
    struct Outer {
        signed: Option<String>,
        signature: Option<String>,
    }
    let outer: Outer = serde_json::from_str(json).map_err(|_| "unreadable update list")?;
    let (Some(signed), Some(signature)) = (outer.signed, outer.signature) else {
        return Err("unsigned update refused".into());
    };
    let data = STANDARD.decode(signed).map_err(|_| "unreadable update signature")?;
    let sig = STANDARD.decode(signature).map_err(|_| "unreadable update signature")?;
    let key_der = STANDARD.decode(public_key).map_err(|_| "bad built-in key")?;
    let key = VerifyingKey::from_public_key_der(&key_der).map_err(|_| "bad built-in key")?;
    let sig = Signature::from_slice(&sig).map_err(|_| "update signature is wrong, refused")?;
    key.verify(&data, &sig).map_err(|_| "update signature is wrong, refused")?;
    let m: Manifest = serde_json::from_slice(&data).map_err(|_| "unreadable update list")?;
    if m.app != APP_NAME {
        return Err("that update isn't for Game Night".into());
    }
    if !safe_path(&m.file.path) || m.file.sha256.len() != 64 || m.file.size == 0 || m.file.size > MAX_INSTALLER {
        return Err("odd update list, refused".into());
    }
    Ok(m)
}

/// "v0.3.0/GameNightSetup.exe": one version folder, one plain .exe name, nothing else.
fn safe_path(p: &str) -> bool {
    let mut parts = p.split('/');
    let (Some(dir), Some(name), None) = (parts.next(), parts.next(), parts.next()) else {
        return false;
    };
    dir.starts_with('v')
        && dir.len() > 1
        && dir[1..].chars().all(|c| c.is_ascii_digit() || c == '.')
        && name.to_ascii_lowercase().ends_with(".exe")
        && name.chars().all(|c| c.is_ascii_alphanumeric() || "._-".contains(c))
}

fn http() -> reqwest::Client {
    reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(10))
        .redirect(reqwest::redirect::Policy::none())
        .user_agent(concat!("GameNight/", env!("CARGO_PKG_VERSION")))
        .build()
        .expect("http client")
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Every update step goes into update\\update.log (the install helper writes to the same file), so a
/// failed or odd update can be explained from the log instead of guessed at. Times are UTC.
fn log_path<R: Runtime>(app: &AppHandle<R>) -> Option<std::path::PathBuf> {
    Some(update_dir(app)?.join("update.log"))
}

fn log<R: Runtime>(app: &AppHandle<R>, msg: &str) {
    use std::io::Write;
    let Some(path) = log_path(app) else { return };
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    // Keep it small: start again once it passes 256 KB.
    if std::fs::metadata(&path).map(|m| m.len() > 256 * 1024).unwrap_or(false) {
        let _ = std::fs::remove_file(&path);
    }
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(&path) {
        let _ = writeln!(f, "{} app: {msg}", stamp());
    }
}

/// "2026-10-31 02:54:40.123" (UTC) without pulling in a date library.
fn stamp() -> String {
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default();
    let secs = now.as_secs();
    let (days, rest) = (secs / 86_400, secs % 86_400);
    // Days since 1970-01-01 to a calendar date (Howard Hinnant's civil_from_days).
    let z = days as i64 + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + if m <= 2 { 1 } else { 0 };
    format!(
        "{y:04}-{m:02}-{d:02} {:02}:{:02}:{:02}.{:03}",
        rest / 3600,
        rest % 3600 / 60,
        rest % 60,
        now.subsec_millis()
    )
}

/// At start-up, if an update was tried before: note which version opened, so the log shows whether
/// Game Night really came back after an install.
pub fn log_start<R: Runtime>(app: &AppHandle<R>) {
    if log_path(app).is_some_and(|p| p.exists()) {
        log(app, &format!("Game Night {} opened (pid {})", current_version(app), std::process::id()));
    }
}

/// The update box reports what it is showing (step and percent), so the log shows what Jayden saw on
/// screen next to what the download really did. Only a known step name and a number are accepted.
#[tauri::command]
pub fn update_seen<R: Runtime>(app: AppHandle<R>, step: String, percent: u8) {
    const STEPS: [&str; 6] = ["asking", "downloading", "checking", "installing", "updated", "failed"];
    if STEPS.contains(&step.as_str()) {
        log(&app, &format!("screen shows {step} {}%", percent.min(100)));
    }
}

/// True only in CI's Windows update test (the "e2e" build with GAMENIGHT_E2E=update-ui): the update box
/// then presses Update by itself, so the test goes through the same screen Jayden uses.
#[tauri::command]
pub fn update_test_mode() -> bool {
    #[cfg(feature = "e2e")]
    if std::env::var("GAMENIGHT_E2E").as_deref() == Ok("update-ui") {
        return true;
    }
    false
}

fn current_version<R: Runtime>(app: &AppHandle<R>) -> String {
    app.package_info().version.to_string()
}

/// The newest signed update, if it's newer than this app. None = up to date, offline, or nothing trustworthy.
async fn find_update<R: Runtime>(app: &AppHandle<R>) -> Option<Manifest> {
    let resp = match http().get(format!("{}latest.json", base())).timeout(Duration::from_secs(20)).send().await {
        Ok(r) if r.status().is_success() => r,
        _ => return None, // no internet or no server: just no update
    };
    let text = resp.text().await.ok()?;
    let m = match parse_signed(&text, &key()) {
        Ok(m) => m,
        Err(e) => {
            eprintln!("update ignored: {e}");
            return None;
        }
    };
    newer(&m.version, &current_version(app)).then_some(m)
}

/// Asks the update server. None = up to date, offline, or nothing trustworthy there.
#[tauri::command]
pub async fn check_update<R: Runtime>(app: AppHandle<R>, updates: tauri::State<'_, Updates>) -> Result<Option<UpdateInfo>, String> {
    let Some(m) = find_update(&app).await else {
        return Ok(None);
    };
    let info = UpdateInfo { version: m.version.clone(), notes: m.notes.iter().take(3).cloned().collect(), size: m.file.size };
    *updates.found.lock().unwrap_or_else(|e| e.into_inner()) = Some(m);
    Ok(Some(info))
}

/// Step 1 of an update: downloads the installer and checks it against the signed SHA-256, showing
/// progress in the update box. Game Night stays open; nothing is installed yet.
#[tauri::command]
pub async fn download_update<R: Runtime>(app: AppHandle<R>, updates: tauri::State<'_, Updates>) -> Result<(), String> {
    let m = updates.found.lock().unwrap_or_else(|e| e.into_inner()).clone().ok_or("No update to install.")?;
    let file = download(&app, &m).await?;
    *updates.ready.lock().unwrap_or_else(|e| e.into_inner()) = Some((m, file));
    Ok(())
}

/// Step 2: hands the checked installer to the install helper and closes Game Night. The installer shows
/// its own progress bar, then opens Game Night again.
#[tauri::command]
pub async fn start_install<R: Runtime>(app: AppHandle<R>, updates: tauri::State<'_, Updates>) -> Result<(), String> {
    let (m, file) = updates.ready.lock().unwrap_or_else(|e| e.into_inner()).clone().ok_or("No update to install.")?;
    // Re-check the saved file, in case anything touched it since the download.
    let bytes = std::fs::read(&file).map_err(|_| "The update file went missing. Try again.")?;
    if bytes.len() as u64 != m.file.size || hex(&Sha256::digest(&bytes)) != m.file.sha256.to_ascii_lowercase() {
        log(&app, "the saved installer changed after the download, refused");
        return Err("The update file changed after the download, so nothing was installed. Try again.".into());
    }
    drop(bytes);
    run_installer(&app, &file, &m.version).await
}

async fn download<R: Runtime>(app: &AppHandle<R>, m: &Manifest) -> Result<std::path::PathBuf, String> {
    let app = app.clone();
    let dir = update_dir(&app).ok_or("No folder for the download.")?;
    std::fs::create_dir_all(&dir).map_err(|_| "Couldn't make the download folder.")?;
    // Clear an older download, but keep update.log so earlier attempts can still be read.
    let file = dir.join("GameNightSetup.exe");
    let _ = std::fs::remove_file(&file);
    let _ = std::fs::remove_file(dir.join("apply.ps1"));
    log(&app, &format!("update {} -> {}: download starts ({} bytes)", current_version(&app), m.version, m.file.size));
    let started = std::time::Instant::now();

    let mut resp = http()
        .get(format!("{}{}", base(), m.file.path))
        .send()
        .await
        .map_err(|_| "Couldn't reach the update server.")?;
    if !resp.status().is_success() {
        log(&app, &format!("download refused by the server: {}", resp.status()));
        return Err("The update server couldn't send the update.".into());
    }
    let mut hasher = Sha256::new();
    let mut body: Vec<u8> = Vec::with_capacity(m.file.size as usize);
    let mut last = 0u64;
    let mut logged = 0u64; // last tenth written to the log
    while let Some(chunk) = resp.chunk().await.map_err(|_| {
        log(&app, "download stopped part-way");
        "The download stopped. Try again."
    })? {
        if body.len() as u64 + chunk.len() as u64 > m.file.size {
            return Err("The download was bigger than expected, so it was thrown away.".into());
        }
        hasher.update(&chunk);
        body.extend_from_slice(&chunk);
        let done = body.len() as u64;
        if done - last > 256 * 1024 || done == m.file.size {
            last = done;
            let _ = app.emit("update-progress", Progress { done, total: m.file.size });
            let tenth = done * 10 / m.file.size;
            if tenth > logged {
                logged = tenth;
                log(&app, &format!("sent progress {}% ({done} bytes, {:.1} s)", tenth * 10, started.elapsed().as_secs_f32()));
            }
        }
    }
    if body.len() as u64 != m.file.size || hex(&hasher.finalize()) != m.file.sha256.to_ascii_lowercase() {
        log(&app, &format!("download broken: got {} of {} bytes, or the SHA-256 didn't match", body.len(), m.file.size));
        return Err("The download arrived broken, so nothing was installed. Try again.".into());
    }
    log(&app, &format!("download complete and matches the signed SHA-256 ({:.1} s)", started.elapsed().as_secs_f32()));
    std::fs::write(&file, &body).map_err(|_| "Couldn't save the update.")?;
    Ok(file)
}

fn update_dir<R: Runtime>(app: &AppHandle<R>) -> Option<std::path::PathBuf> {
    Some(app.path().app_cache_dir().ok()?.join("update"))
}

/// Left by the old version just before it closes for an install: the version it is updating to.
/// The new version finds it on start-up, comes to the front and says it updated.
const MARKER: &str = "just-updated.txt";

/// At start-up: if this start is the end of an update (the marker names this version and is less than
/// 10 minutes old), note it in the log, bring the window to the front and return the version, so the
/// update box can say "Updated". The marker is removed either way.
pub fn after_update<R: Runtime>(app: &AppHandle<R>) -> Option<String> {
    let marker = update_dir(app)?.join(MARKER);
    let text = std::fs::read_to_string(&marker).ok();
    let fresh = std::fs::metadata(&marker)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.elapsed().ok())
        .is_some_and(|age| age < Duration::from_secs(600));
    let _ = std::fs::remove_file(&marker);
    let wanted = text?.trim().to_string();
    let now = current_version(app);
    if !fresh || number(&wanted) != number(&now) {
        log(app, &format!("start-up after an update to {wanted}, but this is {now}"));
        return None;
    }
    log(app, &format!("back after the update: {now} is running, bringing the window to the front"));
    if let Some(w) = app.get_webview_window("main") {
        // Windows doesn't let a program that was started in the background jump in front of the window
        // you're using, so it would open behind it. Pinning it on top for a moment brings it forward.
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_always_on_top(true);
        let _ = w.set_focus();
        let w2 = w.clone();
        tauri::async_runtime::spawn(async move {
            tokio_sleep(Duration::from_millis(1500)).await;
            let _ = w2.set_always_on_top(false);
            let _ = w2.set_focus();
        });
    }
    Some(now)
}

async fn tokio_sleep(d: Duration) {
    let _ = tauri::async_runtime::spawn_blocking(move || std::thread::sleep(d)).await;
}

/// The update box asks once on start-up whether Game Night just came back from an update.
#[tauri::command]
pub fn just_updated(updates: tauri::State<'_, Updates>) -> Option<String> {
    updates.came_back.lock().unwrap_or_else(|e| e.into_inner()).take()
}

/// The helper that installs an update after Game Night has closed. It runs the installer in its
/// "passive" mode, which shows the installer's own progress bar and needs no clicks, and with /R, so the
/// installer opens the new Game Night itself when it is done. Every step goes into update\update.log.
/// If the install fails twice, it opens the old Game Night again so nobody is left with nothing.
#[cfg(windows)]
const HELPER: &str = r#"param([int]$AppPid, [string]$Setup, [string]$Exe, [string]$Log)
function Log($m) { Add-Content -Path $Log -Value ("{0:yyyy-MM-dd HH:mm:ss.fff} helper: {1}" -f (Get-Date).ToUniversalTime(), $m) }
$ok = $false
try {
  Log "waiting for Game Night ($AppPid) to close"
  $t = 0
  while ((Get-Process -Id $AppPid -ErrorAction SilentlyContinue) -and $t -lt 120) { Start-Sleep -Milliseconds 250; $t++ }
  Log ("Game Night closed; old version: " + (Get-Item $Exe).VersionInfo.ProductVersion)
  for ($try = 1; $try -le 2; $try++) {
    # Wait for the installer itself only. (Start-Process -Wait would also wait for the Game Night it opens.)
    $p = Start-Process -FilePath $Setup -ArgumentList '/P', '/UPDATE', '/R' -WindowStyle Normal -PassThru -ErrorAction Stop
    $null = $p.Handle
    $p.WaitForExit()
    Log "installer finished with code $($p.ExitCode) (try $try)"
    if ($p.ExitCode -eq 0) { $ok = $true; break }
    Start-Sleep -Seconds 2
  }
  Log ("now installed: " + (Get-Item $Exe).VersionInfo.ProductVersion)
} catch {
  Log ("install failed: " + $_)
}
if ($ok) {
  Log "the installer opens Game Night again"
} else {
  Start-Process -FilePath $Exe -WindowStyle Normal
  Log "install didn't work: reopened the old Game Night"
}
"#;

#[cfg(windows)]
async fn run_installer<R: Runtime>(app: &AppHandle<R>, setup: &std::path::Path, version: &str) -> Result<(), String> {
    use std::os::windows::process::CommandExt;
    const NO_WINDOW: u32 = 0x0800_0000; // CREATE_NO_WINDOW
    const BREAKAWAY: u32 = 0x0100_0000; // CREATE_BREAKAWAY_FROM_JOB: keep running after Game Night closes
    let exe = std::env::current_exe().map_err(|_| "Couldn't find Game Night's own file.")?;
    let dir = setup.parent().ok_or("No folder for the update.")?;
    let script = dir.join("apply.ps1");
    std::fs::write(&script, HELPER).map_err(|_| "Couldn't prepare the installer.")?;
    std::fs::write(dir.join(MARKER), version).map_err(|_| "Couldn't prepare the installer.")?;
    let pid = std::process::id().to_string();
    let log_file = dir.join("update.log");
    let args: [&std::ffi::OsStr; 16] = [
        "-NoProfile".as_ref(), "-NonInteractive".as_ref(), "-ExecutionPolicy".as_ref(), "Bypass".as_ref(),
        "-WindowStyle".as_ref(), "Hidden".as_ref(), "-File".as_ref(), script.as_os_str(),
        "-AppPid".as_ref(), pid.as_ref(), "-Setup".as_ref(), setup.as_os_str(),
        "-Exe".as_ref(), exe.as_os_str(), "-Log".as_ref(), log_file.as_os_str(),
    ];
    let start = |flags: u32| std::process::Command::new("powershell.exe").args(args).creation_flags(flags).spawn();
    let helper = match start(NO_WINDOW | BREAKAWAY) {
        Ok(c) => {
            log(app, &format!("install helper started (pid {}, kept apart from Game Night)", c.id()));
            c
        }
        Err(e) => {
            log(app, &format!("install helper couldn't start apart from Game Night ({e}), trying plainly"));
            start(NO_WINDOW).map_err(|e| {
                let _ = std::fs::remove_file(dir.join(MARKER));
                log(app, &format!("install helper didn't start: {e}"));
                "Couldn't start the installer."
            })?
        }
    };
    drop(helper);
    // Stay on screen until the helper is really running (it writes its first line when it is), so the
    // gap with nothing on screen is as short as possible. Give up waiting after 15 seconds.
    let before = std::fs::read_to_string(&log_file).map(|s| s.matches("helper: waiting").count()).unwrap_or(0);
    for _ in 0..60 {
        tokio_sleep(Duration::from_millis(250)).await;
        let now = std::fs::read_to_string(&log_file).map(|s| s.matches("helper: waiting").count()).unwrap_or(0);
        if now > before {
            break;
        }
    }
    log(app, "Game Night closes now for the install");
    app.exit(0);
    Ok(())
}

#[cfg(not(windows))]
async fn run_installer<R: Runtime>(_app: &AppHandle<R>, setup: &std::path::Path, _version: &str) -> Result<(), String> {
    Err(format!("Updates install on Windows only. The checked installer is at {}", setup.display()))
}

#[cfg(test)]
mod tests {
    use super::*;

    // A throwaway test key (not Jayden's) and a list signed with it by gamenight_publish.py.
    const TEST_KEY: &str = include_str!("../tests/update_test_key.txt");
    const TEST_LIST: &str = include_str!("../tests/update_test_latest.json");

    #[test]
    fn accepts_a_correctly_signed_list() {
        let m = parse_signed(TEST_LIST, TEST_KEY.trim()).unwrap();
        assert_eq!(m.app, "gamenight");
        assert_eq!(m.version, "9.9.9");
        assert_eq!(m.file.path, "v9.9.9/GameNightSetup.exe");
    }

    #[test]
    fn refuses_jaydens_key_for_a_list_signed_by_someone_else() {
        assert!(parse_signed(TEST_LIST, PUBLIC_KEY).is_err());
    }

    #[test]
    fn refuses_unsigned_and_edited_lists() {
        assert!(parse_signed(r#"{"version":"9.9.9"}"#, TEST_KEY.trim()).is_err());
        // Change one character of the signed copy.
        let v: serde_json::Value = serde_json::from_str(TEST_LIST).unwrap();
        let mut signed = STANDARD.decode(v["signed"].as_str().unwrap()).unwrap();
        let i = signed.iter().position(|&b| b == b'9').unwrap();
        signed[i] = b'8';
        let tampered = serde_json::json!({ "signed": STANDARD.encode(signed), "signature": v["signature"] }).to_string();
        assert!(parse_signed(&tampered, TEST_KEY.trim()).is_err());
    }

    #[test]
    fn jaydens_key_loads() {
        let der = STANDARD.decode(PUBLIC_KEY).unwrap();
        assert!(VerifyingKey::from_public_key_der(&der).is_ok());
    }

    #[test]
    fn versions_and_paths() {
        assert!(newer("0.3.0", "0.2.0"));
        assert!(newer("0.10.0", "0.9.9"));
        assert!(!newer("0.2.0", "0.2.0"));
        assert!(!newer("0.1.9", "0.2.0"));
        assert!(safe_path("v0.3.0/GameNightSetup.exe"));
        assert!(!safe_path("../GameNightSetup.exe"));
        assert!(!safe_path("v0.3.0/../../x.exe"));
        assert!(!safe_path("v0.3.0/setup.ps1"));
        assert!(!safe_path("https://evil.example/x.exe"));
    }
}
