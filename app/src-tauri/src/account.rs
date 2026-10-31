//! Signing in, and every conversation with the Game Night server.
//!
//! The window never talks to the internet itself (its content security policy forbids it).
//! It asks this file, which talks only to the one server address saved in Settings.
//!
//! Sign-in: we make a secret, open the browser at the server's Discord sign-in page with
//! only a fingerprint of that secret, and wait for the browser to hand back a short-lived
//! code through a gamenight:// link. We trade the code plus the secret for a sign-in pass.
//! The pass is kept in Windows Credential Manager, never in a plain file and never in the window.

use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager, Runtime};
use url::Url;

/// Jayden's server, online through his own domain (Nginx Proxy Manager forwards /gamenight/ to it).
pub const DEFAULT_SERVER: &str = "https://play.jjsnas.xyz/gamenight";
/// The home-network address used before 0.3.5. A PC that never signed in there moves to the online one.
const OLD_HOME_SERVER: &str = "http://192.168.1.33:8094";
const SIGN_IN_MINUTES: u64 = 10;

#[derive(Clone, Serialize, Deserialize, Default)]
pub struct UserInfo {
    pub id: String,
    pub name: String,
    pub avatar: String,
}

/// What's saved on this PC (not secret): the server address and who signed in last.
#[derive(Serialize, Deserialize, Default)]
struct Saved {
    server: String,
    user: Option<UserInfo>,
}

#[derive(Default)]
pub struct Account {
    inner: Mutex<Inner>,
}

#[derive(Default)]
struct Inner {
    loaded: bool,
    saved: Saved,
    token: Option<String>,
    pending: Option<(String, Instant)>, // (secret, when sign-in started)
}

/// Why a JSON call to the server didn't work.
#[derive(Debug, Clone, PartialEq)]
pub enum SendError {
    SignedOut,
    Offline,
    /// The server said no: its status code, and its own short message if it gave one.
    Refused(u16, Option<String>),
    Odd,
}

#[derive(Serialize)]
pub struct Status {
    server: String,
    user: Option<UserInfo>,
}

fn http() -> reqwest::Client {
    reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(8))
        .timeout(Duration::from_secs(30))
        .redirect(reqwest::redirect::Policy::none())
        .user_agent(concat!("GameNight/", env!("CARGO_PKG_VERSION")))
        .build()
        .expect("http client")
}

/// Only https, or plain http to this PC or the home network (192.168.x.x, 10.x.x.x and so on).
/// A plain folder-style path is allowed (e.g. https://play.jjsnas.xyz/gamenight), nothing else after it.
pub fn check_server(raw: &str) -> Result<String, String> {
    let bad = || "That doesn't look like a Game Night server address.".to_string();
    let u = Url::parse(raw.trim()).map_err(|_| bad())?;
    if !u.username().is_empty() || u.password().is_some() || u.query().is_some() || u.fragment().is_some() {
        return Err(bad());
    }
    let path = u.path().trim_end_matches('/');
    let plain = |seg: &str| {
        !seg.is_empty() && seg != "." && seg != ".." && seg.len() <= 64 && seg.chars().all(|c| c.is_ascii_alphanumeric() || "-_.~".contains(c))
    };
    if !path.is_empty() && (path.len() > 200 || !path.starts_with('/') || !path[1..].split('/').all(plain)) {
        return Err(bad());
    }
    let host = u.host().ok_or_else(bad)?;
    match u.scheme() {
        "https" => {}
        "http" => {
            let local = match host {
                url::Host::Ipv4(ip) => ip.is_private() || ip.is_loopback(),
                url::Host::Ipv6(ip) => ip.is_loopback(),
                url::Host::Domain(d) => d == "localhost",
            };
            if !local {
                return Err("Use an https:// address for a server outside your home.".into());
            }
        }
        _ => return Err(bad()),
    }
    Ok(u.as_str().trim_end_matches('/').to_string())
}

fn random_secret() -> String {
    let mut b = [0u8; 32];
    getrandom::fill(&mut b).expect("random");
    URL_SAFE_NO_PAD.encode(b)
}

fn challenge_of(secret: &str) -> String {
    URL_SAFE_NO_PAD.encode(Sha256::digest(secret.as_bytes()))
}

// ---------- where things are kept ----------

fn saved_path<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    app.path().app_config_dir().ok().map(|d| d.join("account.json"))
}

#[cfg(windows)]
mod vault {
    fn entry() -> Option<keyring::Entry> {
        keyring::Entry::new("Game Night", "sign-in").ok()
    }
    pub fn load(_dir: Option<std::path::PathBuf>) -> Option<String> {
        entry()?.get_password().ok()
    }
    pub fn store(_dir: Option<std::path::PathBuf>, token: &str) {
        if let Some(e) = entry() {
            let _ = e.set_password(token);
        }
    }
    pub fn forget(_dir: Option<std::path::PathBuf>) {
        if let Some(e) = entry() {
            let _ = e.delete_credential();
        }
    }
}

/// Only used when building on Linux/macOS: a file next to the settings.
#[cfg(not(windows))]
mod vault {
    use std::path::PathBuf;
    fn file(dir: Option<PathBuf>) -> Option<PathBuf> {
        dir.map(|d| d.join("sign-in.dev"))
    }
    pub fn load(dir: Option<PathBuf>) -> Option<String> {
        std::fs::read_to_string(file(dir)?).ok().map(|s| s.trim().to_string())
    }
    pub fn store(dir: Option<PathBuf>, token: &str) {
        if let Some(f) = file(dir) {
            let _ = std::fs::write(f, token);
        }
    }
    pub fn forget(dir: Option<PathBuf>) {
        if let Some(f) = file(dir) {
            let _ = std::fs::remove_file(f);
        }
    }
}

impl Account {
    fn with<R: Runtime, T>(&self, app: &AppHandle<R>, f: impl FnOnce(&mut Inner) -> T) -> T {
        let mut g = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        if !g.loaded {
            g.loaded = true;
            if let Some(p) = saved_path(app) {
                if let Ok(text) = fs::read_to_string(p) {
                    g.saved = serde_json::from_str(&text).unwrap_or_default();
                }
            }
            if check_server(&g.saved.server).is_err() {
                g.saved.server = DEFAULT_SERVER.into();
            }
            g.token = vault::load(app.path().app_config_dir().ok());
            if g.token.is_none() {
                g.saved.user = None;
                // Friends outside the house could never sign in at the home address; send them online.
                // A PC already signed in there (Jayden's) keeps it, since its pass only works with that server.
                if g.saved.server == OLD_HOME_SERVER {
                    g.saved.server = DEFAULT_SERVER.into();
                }
            }
        }
        f(&mut g)
    }

    fn persist<R: Runtime>(app: &AppHandle<R>, g: &Inner) {
        if let Some(p) = saved_path(app) {
            if let Some(dir) = p.parent() {
                let _ = fs::create_dir_all(dir);
            }
            if let Ok(text) = serde_json::to_string_pretty(&g.saved) {
                let _ = fs::write(p, text);
            }
        }
    }

    fn signed_out<R: Runtime>(&self, app: &AppHandle<R>) {
        self.with(app, |g| {
            g.token = None;
            g.saved.user = None;
            Self::persist(app, g);
        });
        vault::forget(app.path().app_config_dir().ok());
        let _ = app.emit("signed-out", ());
    }

    /// The server address and sign-in pass, for a request. None = not signed in.
    fn creds<R: Runtime>(&self, app: &AppHandle<R>) -> (String, Option<String>) {
        self.with(app, |g| (g.saved.server.clone(), g.token.clone()))
    }

    /// GET something from the server with the sign-in pass. A rejected pass signs you out.
    pub async fn get<R: Runtime>(&self, app: &AppHandle<R>, path: &str) -> Result<reqwest::Response, String> {
        let (server, token) = self.creds(app);
        let token = token.ok_or("signed-out")?;
        let resp = http()
            .get(format!("{server}{path}"))
            .bearer_auth(token)
            .send()
            .await
            .map_err(|_| "offline".to_string())?;
        if resp.status() == reqwest::StatusCode::UNAUTHORIZED {
            self.signed_out(app);
            return Err("signed-out".into());
        }
        if !resp.status().is_success() {
            return Err(format!("server-{}", resp.status().as_u16()));
        }
        Ok(resp)
    }

    /// Sends a JSON call (GET / POST / PATCH) with the sign-in pass and returns the JSON answer.
    /// A rejected pass signs you out. The server's own plain-English refusal is kept when it gives one.
    pub async fn send_json<R: Runtime>(
        &self,
        app: &AppHandle<R>,
        method: reqwest::Method,
        path: &str,
        body: Option<&serde_json::Value>,
    ) -> Result<serde_json::Value, SendError> {
        let (server, token) = self.creds(app);
        let token = token.ok_or(SendError::SignedOut)?;
        let client = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(8))
            .timeout(Duration::from_secs(15))
            .redirect(reqwest::redirect::Policy::none())
            .user_agent(concat!("GameNight/", env!("CARGO_PKG_VERSION")))
            .build()
            .map_err(|_| SendError::Offline)?;
        let mut req = client.request(method, format!("{server}{path}")).bearer_auth(token);
        if let Some(b) = body {
            req = req.json(b);
        }
        let resp = req.send().await.map_err(|_| SendError::Offline)?;
        let status = resp.status();
        if status == reqwest::StatusCode::UNAUTHORIZED {
            self.signed_out(app);
            return Err(SendError::SignedOut);
        }
        if !status.is_success() {
            let text = resp.text().await.unwrap_or_default();
            let text = text.trim();
            // Only short plain sentences are shown (never a web page).
            let said = (!text.is_empty() && text.len() <= 200 && !text.contains('<') && !text.contains('{')).then(|| text.to_string());
            return Err(SendError::Refused(status.as_u16(), said));
        }
        resp.json().await.map_err(|_| SendError::Odd)
    }

    /// The signed-in person's name, if any.
    pub fn user_name<R: Runtime>(&self, app: &AppHandle<R>) -> Option<String> {
        self.with(app, |g| g.saved.user.as_ref().map(|u| u.name.clone()))
    }

    /// CI's Couch Play test only (the "e2e" build, never shipped): a test server and pass, kept in memory only.
    #[cfg(feature = "e2e")]
    pub fn e2e_use(&self, server: String, token: String) {
        let mut g = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        g.loaded = true;
        g.saved.server = server;
        g.saved.user = Some(UserInfo { id: "e2e".into(), name: "Host".into(), avatar: String::new() });
        g.token = Some(token);
    }

    /// Starts a game download from the server, from byte `from` onward (to finish a stopped download).
    /// No overall time limit, since a big game can take a while; it gives up if nothing arrives for 2 minutes.
    pub async fn download<R: Runtime>(&self, app: &AppHandle<R>, path: &str, from: u64) -> Result<reqwest::Response, String> {
        let (server, token) = self.creds(app);
        let token = token.ok_or("signed-out")?;
        let client = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(8))
            .read_timeout(Duration::from_secs(120))
            .redirect(reqwest::redirect::Policy::none())
            .user_agent(concat!("GameNight/", env!("CARGO_PKG_VERSION")))
            .build()
            .map_err(|_| "offline".to_string())?;
        let mut req = client.get(format!("{server}{path}")).bearer_auth(token);
        if from > 0 {
            req = req.header("Range", format!("bytes={from}-"));
        }
        let resp = req.send().await.map_err(|_| "offline".to_string())?;
        if resp.status() == reqwest::StatusCode::UNAUTHORIZED {
            self.signed_out(app);
            return Err("signed-out".into());
        }
        if !resp.status().is_success() {
            return Err(format!("server-{}", resp.status().as_u16()));
        }
        Ok(resp)
    }

    /// Called when Windows hands us a gamenight:// link.
    pub fn handle_link<R: Runtime>(&self, app: &AppHandle<R>, link: &Url) {
        if link.scheme() != "gamenight" || link.host_str() != Some("signed-in") {
            return;
        }
        let code = link
            .query_pairs()
            .find(|(k, _)| k == "code")
            .map(|(_, v)| v.to_string())
            .unwrap_or_default();
        if code.is_empty() || code.len() > 100 || !code.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
            return;
        }
        // Only if this PC actually started a sign-in in the last few minutes. One use only.
        let Some(secret) = self.with(app, |g| match g.pending.take() {
            Some((s, at)) if at.elapsed() < Duration::from_secs(SIGN_IN_MINUTES * 60) => Some(s),
            _ => None,
        }) else {
            return;
        };
        let server = self.creds(app).0;
        let app = app.clone();
        tauri::async_runtime::spawn(async move {
            let device = std::env::var("COMPUTERNAME").unwrap_or_default();
            let result = async {
                let resp = http()
                    .post(format!("{server}/api/session"))
                    .json(&serde_json::json!({ "code": code, "verifier": secret, "device": device }))
                    .send()
                    .await
                    .map_err(|_| "Couldn't reach the Game Night server.".to_string())?;
                if !resp.status().is_success() {
                    return Err("That sign-in expired. Press Log in with Discord again.".to_string());
                }
                #[derive(Deserialize)]
                struct Got {
                    token: String,
                    user: UserInfo,
                }
                let got: Got = resp.json().await.map_err(|_| "The server sent something odd.".to_string())?;
                if !got.token.starts_with("gn_") {
                    return Err("The server sent something odd.".to_string());
                }
                Ok(got)
            }
            .await;
            let account = app.state::<Account>();
            match result {
                Ok(got) => {
                    vault::store(app.path().app_config_dir().ok(), &got.token);
                    let user = got.user.clone();
                    account.with(&app, |g| {
                        g.token = Some(got.token);
                        g.saved.user = Some(got.user);
                        Self::persist(&app, g);
                    });
                    if let Some(w) = app.get_webview_window("main") {
                        let _ = w.unminimize();
                        let _ = w.set_focus();
                    }
                    let _ = app.emit("signed-in", user);
                }
                Err(msg) => {
                    let _ = app.emit("sign-in-failed", msg);
                }
            }
        });
    }
}

// ---------- commands the window can call ----------

#[tauri::command]
pub fn account_status<R: Runtime>(app: AppHandle<R>, account: tauri::State<'_, Account>) -> Status {
    // CI's Windows controller test only (the "e2e" build, never shipped): with GAMENIGHT_E2E=menus (or padgame)
    // the app opens on the main menu as a test player, so the pretend controller can drive the menus.
    #[cfg(feature = "e2e")]
    if matches!(std::env::var("GAMENIGHT_E2E").as_deref(), Ok("menus" | "padgame")) {
        let user = UserInfo { id: "e2e".into(), name: "Test player".into(), avatar: String::new() };
        return Status { server: DEFAULT_SERVER.into(), user: Some(user) };
    }
    account.with(&app, |g| Status { server: g.saved.server.clone(), user: g.saved.user.clone() })
}

#[tauri::command]
pub fn set_server<R: Runtime>(app: AppHandle<R>, account: tauri::State<'_, Account>, address: String) -> Result<String, String> {
    let address = check_server(&address)?;
    let changed = account.with(&app, |g| {
        let changed = g.saved.server != address;
        g.saved.server = address.clone();
        Account::persist(&app, g);
        changed
    });
    if changed {
        // A pass only works with the server that gave it.
        account.signed_out(&app);
    }
    Ok(address)
}

/// Opens Discord sign-in in the web browser.
#[tauri::command]
pub fn sign_in<R: Runtime>(app: AppHandle<R>, account: tauri::State<'_, Account>) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    let secret = random_secret();
    let challenge = challenge_of(&secret);
    let server = account.with(&app, |g| {
        g.pending = Some((secret, Instant::now()));
        g.saved.server.clone()
    });
    app.opener()
        .open_url(format!("{server}/app/login?challenge={challenge}"), None::<&str>)
        .map_err(|_| "Couldn't open your web browser.".to_string())
}

#[tauri::command]
pub async fn sign_out<R: Runtime>(app: AppHandle<R>, account: tauri::State<'_, Account>) -> Result<(), String> {
    let (server, token) = account.creds(&app);
    if let Some(t) = token {
        // Tell the server too, but sign out here even if it can't be reached.
        let _ = http().delete(format!("{server}/api/session")).bearer_auth(t).send().await;
    }
    account.signed_out(&app);
    Ok(())
}

/// The game list, straight from the server, as JSON text. Kept on this PC for offline use.
#[tauri::command]
pub async fn fetch_games<R: Runtime>(app: AppHandle<R>, account: tauri::State<'_, Account>) -> Result<serde_json::Value, String> {
    let cache = app.path().app_cache_dir().ok().map(|d| d.join("games.json"));
    match account.get(&app, "/api/games").await {
        Ok(resp) => {
            let v: serde_json::Value = resp.json().await.map_err(|_| "server-odd".to_string())?;
            if let Some(c) = &cache {
                if let Some(dir) = c.parent() {
                    let _ = fs::create_dir_all(dir);
                }
                let _ = fs::write(c, v.to_string());
            }
            Ok(serde_json::json!({ "games": v["games"], "offline": false }))
        }
        Err(e) if e == "signed-out" => Err(e),
        Err(e) => {
            let saved = cache.and_then(|c| fs::read_to_string(c).ok()).and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok());
            match saved {
                Some(v) => Ok(serde_json::json!({ "games": v["games"], "offline": true })),
                None => Err(e),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn server_addresses() {
        assert_eq!(check_server("http://192.168.1.33:8094/").unwrap(), "http://192.168.1.33:8094");
        assert_eq!(check_server("https://gamenight.jjsnas.xyz").unwrap(), "https://gamenight.jjsnas.xyz");
        assert!(check_server("http://gamenight.jjsnas.xyz").is_err()); // plain http outside the home
        assert!(check_server("http://8.8.8.8").is_err());
        assert!(check_server("https://user:pw@example.com").is_err());
        assert_eq!(check_server("https://play.jjsnas.xyz/gamenight").unwrap(), "https://play.jjsnas.xyz/gamenight");
        assert_eq!(check_server("https://play.jjsnas.xyz/gamenight/").unwrap(), "https://play.jjsnas.xyz/gamenight");
        assert_eq!(check_server("https://example.com/a/b-c").unwrap(), "https://example.com/a/b-c");
        assert!(check_server("https://example.com/somewhere?x=1").is_err());
        assert!(check_server("https://example.com/somewhere#x").is_err());
        assert!(check_server("https://example.com/a//b").is_err());
        assert!(check_server("https://example.com/a%20b").is_err());
        assert!(check_server("https://example.com/a/../b").unwrap() == "https://example.com/b"); // tidied by the URL reader
        assert!(check_server("http://gamenight.jjsnas.xyz/gamenight").is_err());
        assert!(check_server("file:///C:/").is_err());
        assert!(check_server("").is_err());
    }

    #[test]
    fn challenge_matches_server() {
        // Same answer as the server's challenge_of() for the PKCE example in RFC 7636.
        assert_eq!(challenge_of("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"), "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
        assert_ne!(random_secret(), random_secret());
        assert_eq!(random_secret().len(), 43);
    }
}
