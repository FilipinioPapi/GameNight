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

/// Downloads the installer, checks it against the signed SHA-256, runs it quietly and reopens Game Night.
#[tauri::command]
pub async fn install_update<R: Runtime>(app: AppHandle<R>, updates: tauri::State<'_, Updates>) -> Result<(), String> {
    let m = updates.found.lock().unwrap_or_else(|e| e.into_inner()).clone().ok_or("No update to install.")?;
    install(&app, &m).await
}

/// CI's Windows update test only (the "e2e" build, never shipped): with GAMENIGHT_E2E=update the app
/// finds and installs the update by itself, exactly as if the Update button had been pressed.
#[cfg(feature = "e2e")]
pub fn e2e_autoupdate<R: Runtime>(app: AppHandle<R>) {
    if std::env::var("GAMENIGHT_E2E").as_deref() != Ok("update") {
        return;
    }
    tauri::async_runtime::spawn(async move {
        match find_update(&app).await {
            Some(m) => {
                if let Err(e) = install(&app, &m).await {
                    eprintln!("e2e update failed: {e}");
                    app.exit(3);
                }
            }
            None => {
                eprintln!("e2e: no update found");
                app.exit(2);
            }
        }
    });
}

async fn install<R: Runtime>(app: &AppHandle<R>, m: &Manifest) -> Result<(), String> {
    let app = app.clone();
    let dir = app.path().app_cache_dir().map_err(|_| "No folder for the download.")?.join("update");
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).map_err(|_| "Couldn't make the download folder.")?;
    let file = dir.join("GameNightSetup.exe");

    let mut resp = http()
        .get(format!("{}{}", base(), m.file.path))
        .send()
        .await
        .map_err(|_| "Couldn't reach the update server.")?;
    if !resp.status().is_success() {
        return Err("The update server couldn't send the update.".into());
    }
    let mut hasher = Sha256::new();
    let mut body: Vec<u8> = Vec::with_capacity(m.file.size as usize);
    let mut last = 0u64;
    while let Some(chunk) = resp.chunk().await.map_err(|_| "The download stopped. Try again.")? {
        if body.len() as u64 + chunk.len() as u64 > m.file.size {
            return Err("The download was bigger than expected, so it was thrown away.".into());
        }
        hasher.update(&chunk);
        body.extend_from_slice(&chunk);
        let done = body.len() as u64;
        if done - last > 256 * 1024 || done == m.file.size {
            last = done;
            let _ = app.emit("update-progress", Progress { done, total: m.file.size });
        }
    }
    if body.len() as u64 != m.file.size || hex(&hasher.finalize()) != m.file.sha256.to_ascii_lowercase() {
        return Err("The download arrived broken, so nothing was installed. Try again.".into());
    }
    std::fs::write(&file, &body).map_err(|_| "Couldn't save the update.")?;
    run_installer(&app, &file)
}

/// The helper that installs an update after Game Night has closed. It writes every step to
/// update\\update.log, so a failed update can be explained, and always reopens Game Night.
#[cfg(windows)]
const HELPER: &str = r#"param([int]$AppPid, [string]$Setup, [string]$Exe, [string]$Log)
function Log($m) { Add-Content -Path $Log -Value ("{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $m) }
try {
  Log "waiting for Game Night ($AppPid) to close"
  $t = 0
  while ((Get-Process -Id $AppPid -ErrorAction SilentlyContinue) -and $t -lt 60) { Start-Sleep -Milliseconds 500; $t++ }
  Start-Sleep -Seconds 1
  Log ("old version: " + (Get-Item $Exe).VersionInfo.ProductVersion)
  for ($try = 1; $try -le 2; $try++) {
    $p = Start-Process -FilePath $Setup -ArgumentList '/S' -PassThru -Wait -ErrorAction Stop
    Log "installer finished with code $($p.ExitCode) (try $try)"
    if ($p.ExitCode -eq 0) { break }
    Start-Sleep -Seconds 3
  }
  Log ("now installed: " + (Get-Item $Exe).VersionInfo.ProductVersion)
} catch {
  Log ("install failed: " + $_)
}
Start-Process -FilePath $Exe
Log "reopened Game Night"
"#;

#[cfg(windows)]
fn run_installer<R: Runtime>(app: &AppHandle<R>, setup: &std::path::Path) -> Result<(), String> {
    use std::os::windows::process::CommandExt;
    const NO_WINDOW: u32 = 0x0800_0000; // CREATE_NO_WINDOW
    const BREAKAWAY: u32 = 0x0100_0000; // CREATE_BREAKAWAY_FROM_JOB: keep running after Game Night closes
    let exe = std::env::current_exe().map_err(|_| "Couldn't find Game Night's own file.")?;
    let dir = setup.parent().ok_or("No folder for the update.")?;
    let script = dir.join("apply.ps1");
    std::fs::write(&script, HELPER).map_err(|_| "Couldn't prepare the installer.")?;
    let pid = std::process::id().to_string();
    let log = dir.join("update.log");
    let args: [&std::ffi::OsStr; 16] = [
        "-NoProfile".as_ref(), "-NonInteractive".as_ref(), "-ExecutionPolicy".as_ref(), "Bypass".as_ref(),
        "-WindowStyle".as_ref(), "Hidden".as_ref(), "-File".as_ref(), script.as_os_str(),
        "-AppPid".as_ref(), pid.as_ref(), "-Setup".as_ref(), setup.as_os_str(),
        "-Exe".as_ref(), exe.as_os_str(), "-Log".as_ref(), log.as_os_str(),
    ];
    let start = |flags: u32| std::process::Command::new("powershell.exe").args(args).creation_flags(flags).spawn();
    start(NO_WINDOW | BREAKAWAY).or_else(|_| start(NO_WINDOW)).map_err(|_| "Couldn't start the installer.")?;
    app.exit(0);
    Ok(())
}

#[cfg(not(windows))]
fn run_installer<R: Runtime>(_app: &AppHandle<R>, setup: &std::path::Path) -> Result<(), String> {
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
