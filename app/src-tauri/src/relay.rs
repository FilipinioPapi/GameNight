//! Couch Play's private relay bridge: holds a session on libretro's relay ("tunnel") server for the host,
//! without listing anything publicly. A Rust port of `TunnelBridge` in tools/e2e/netplay_test.py, which was
//! measured working with stock RetroArch 1.22.2 (docs/HANDOFF_NETPLAY_TEST.md).
//!
//! How it works: we ask the relay for a session (RATS) and give its id to friends through Game Night's own
//! server only. When a friend arrives the relay says so (RATL + link id); like RetroArch's own host we ask for
//! their address (RATA), open a new connection to the relay carrying the link id, and pass it to the host's
//! RetroArch on this PC (127.0.0.1). The relay checks we're still there now and then (RATP); we answer.
//!
//! Every link task is kept in a `JoinSet` (the Python version lost links when unreferenced tasks were thrown
//! away). A link whose friend side goes silent while the host is waiting is closed after 3 s, so the host
//! drops that player at once instead of everyone's game freezing for RetroArch's 5 s.

use base64::{engine::general_purpose::STANDARD, Engine};
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio::sync::{mpsc, oneshot, watch};
use tokio::task::JoinSet;
use tokio::time::timeout;

/// Relay messages (RetroArch 1.22.2 network/netplay/netplay_frontend.c). Each id is a 4-byte magic plus
/// 12 bytes; an address is 16 bytes.
pub const RATS: u32 = 0x5241_5453; // session: ask for one (12 zero bytes) / the id the relay gives back
pub const RATL: u32 = 0x5241_544C; // link: a friend arrived; open a new connection and send this id on it
pub const RATA: u32 = 0x5241_5441; // address: ask for / receive the arriving friend's address
pub const RATP: u32 = 0x5241_5450; // ping: the relay checks the host is still there; answer the same 4 bytes

/// libretro's relay places, in RetroArch's own order (netplay_mitm_server_list).
pub const PLACES: [&str; 4] = ["nyc", "madrid", "saopaulo", "singapore"];
/// What RetroArch 1.22.2 itself asks where a relay is (file_path_special.h).
const LOBBY: &str = "http://lobby.libretro.com/";
/// Most friends' links open at once (8 places plus a few rejoins in flight). More is ignored.
const MOST_LINKS: usize = 24;

/// Writes one line to the relay log (relay.log). Never given secrets.
pub type Log = Arc<dyn Fn(String) + Send + Sync>;

/// When a link counts as dead. RetroArch players send their buttons every frame; everyone else connected
/// (watchers too) sends a ping every 3 s (NETPLAY_PING_TIME); the host stops sending to everyone while it
/// waits for a missing player.
/// (RetroArch 1.22.2 netplay_frontend.c / netplay_private.h.)
#[derive(Clone, Copy, Debug)]
pub struct Limits {
    /// A player (friend side was sending steadily) silent this long while the host side is quiet too = that
    /// player is the one the host is waiting for: close it, so the host drops them at once.
    pub friend_silent: Duration,
    /// The same for a link that wasn't sending steadily (a watcher: only a ping every 3 s, so 3 s of silence
    /// is normal for it, even while the host waits for someone else).
    pub watcher_silent: Duration,
    /// How long the host side must have been quiet for the rules above (a host that is still sending isn't
    /// waiting for anyone, e.g. a player who just switched to watching).
    pub host_quiet: Duration,
    /// Friend side silent this long = gone, whatever the host does (a live RetroArch pings every 3 s).
    pub friend_gone: Duration,
    /// True while this PC holds a pause for everyone (and a few seconds after): everyone's game is meant to be
    /// silent then, so no link is closed for being quiet (Couch Play app test run 41256780032).
    pub hold: fn() -> bool,
}

impl Default for Limits {
    fn default() -> Self {
        Limits {
            friend_silent: Duration::from_secs(3),
            watcher_silent: Duration::from_secs(7),
            host_quiet: Duration::from_secs(2),
            friend_gone: Duration::from_secs(20),
            hold: || false,
        }
    }
}

/// Pieces of data from the friend less than this far apart count as a steady stream (a player's buttons,
/// sent every frame); this many in a row make the link a player's.
const STEADY_GAP: Duration = Duration::from_millis(250);
const STEADY_RUN: u32 = 10;

#[derive(Debug, PartialEq)]
pub enum Msg {
    Ping,
    Link([u8; 12]),
    Addr([u8; 12], [u8; 16]),
}

/// Reads one message from the relay's session connection.
pub async fn read_msg<R: AsyncRead + Unpin>(r: &mut R) -> std::io::Result<Msg> {
    let mut magic = [0u8; 4];
    r.read_exact(&mut magic).await?;
    match u32::from_be_bytes(magic) {
        RATP => Ok(Msg::Ping),
        RATL => {
            let mut id = [0u8; 12];
            r.read_exact(&mut id).await?;
            Ok(Msg::Link(id))
        }
        RATA => {
            let mut id = [0u8; 12];
            let mut addr = [0u8; 16];
            r.read_exact(&mut id).await?;
            r.read_exact(&mut addr).await?;
            Ok(Msg::Addr(id, addr))
        }
        other => Err(std::io::Error::new(std::io::ErrorKind::InvalidData, format!("unknown message {other:#x}"))),
    }
}

fn with_id(magic: u32, id: &[u8; 12]) -> Vec<u8> {
    let mut v = magic.to_be_bytes().to_vec();
    v.extend_from_slice(id);
    v
}

/// A relay address from the lobby's answer ("tunnel_addr=..." and "tunnel_port=..." lines), only if sane.
pub fn parse_tunnel(text: &str) -> Option<(String, u16)> {
    let mut host = None;
    let mut port = None;
    for line in text.lines() {
        if let Some((k, v)) = line.trim().split_once('=') {
            match k {
                "tunnel_addr" => host = Some(v.trim().to_string()),
                "tunnel_port" => port = v.trim().parse::<u16>().ok(),
                _ => {}
            }
        }
    }
    let host = host?;
    let ok = !host.is_empty()
        && host.len() <= 253
        && !host.starts_with(['-', '.'])
        && host.chars().all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-');
    match (ok, port) {
        (true, Some(p)) if p > 0 => Some((host, p)),
        _ => None,
    }
}

/// Asks libretro's lobby where one place's relay is, exactly like RetroArch does (tunnel?name=<place>).
pub async fn relay_address(place: &str) -> Result<(String, u16), String> {
    let client = reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(6))
        .timeout(Duration::from_secs(10))
        .redirect(reqwest::redirect::Policy::none())
        .user_agent(concat!("GameNight/", env!("CARGO_PKG_VERSION")))
        .build()
        .map_err(|_| "no web client".to_string())?;
    let text = client
        .get(format!("{LOBBY}tunnel?name={place}"))
        .send()
        .await
        .map_err(|_| format!("couldn't ask where the {place} relay is"))?
        .text()
        .await
        .map_err(|_| format!("odd answer about the {place} relay"))?;
    parse_tunnel(&text).ok_or_else(|| format!("odd answer about the {place} relay"))
}

/// Picks the relay for this host: asks where each place's relay is and times one plain connection to
/// each (like the test's `connect_times`), then takes the quickest. Ties keep RetroArch's own order.
pub async fn choose_relay(log: &Log) -> Result<(String, u16), String> {
    let mut set = JoinSet::new();
    for (i, &place) in PLACES.iter().enumerate() {
        set.spawn(async move {
            let (host, port) = relay_address(place).await?;
            let t = Instant::now();
            timeout(Duration::from_secs(5), TcpStream::connect((host.as_str(), port)))
                .await
                .map_err(|_| format!("{place} relay didn't answer"))?
                .map_err(|_| format!("{place} relay didn't answer"))?;
            Ok::<_, String>((t.elapsed(), i, place, host, port))
        });
    }
    let mut best: Option<(Duration, usize, &str, String, u16)> = None;
    while let Some(r) = set.join_next().await {
        match r {
            Ok(Ok(found)) => {
                log(format!("{} relay {}:{} answered in {} ms", found.2, found.3, found.4, found.0.as_millis()));
                if best.as_ref().is_none_or(|b| (found.0, found.1) < (b.0, b.1)) {
                    best = Some(found);
                }
            }
            Ok(Err(e)) => log(e),
            Err(_) => {}
        }
    }
    let (_, _, place, host, port) = best.ok_or("Couldn't reach any of the online relays.")?;
    log(format!("using the {place} relay {host}:{port}"));
    Ok((host, port))
}

/// Opens a session connection and gets a session id from the relay.
async fn open_session(relay: &(String, u16)) -> Result<(TcpStream, [u8; 12]), String> {
    let mut s = timeout(Duration::from_secs(15), TcpStream::connect((relay.0.as_str(), relay.1)))
        .await
        .map_err(|_| "the relay didn't answer".to_string())?
        .map_err(|e| format!("couldn't connect to the relay: {e}"))?;
    let _ = s.set_nodelay(true);
    let mut ask = RATS.to_be_bytes().to_vec();
    ask.extend_from_slice(&[0u8; 12]);
    s.write_all(&ask).await.map_err(|e| format!("couldn't ask the relay for a session: {e}"))?;
    let mut answer = [0u8; 16];
    timeout(Duration::from_secs(15), s.read_exact(&mut answer))
        .await
        .map_err(|_| "the relay gave no session in time".to_string())?
        .map_err(|e| format!("the relay gave no session: {e}"))?;
    let mut id = [0u8; 12];
    id.copy_from_slice(&answer[4..]);
    if u32::from_be_bytes([answer[0], answer[1], answer[2], answer[3]]) != RATS || id == [0u8; 12] {
        return Err("the relay gave no session".into());
    }
    Ok((s, id))
}

/// The bridge, running. Dropping it (or `stop`) closes the session and every link.
pub struct Bridge {
    pub server: String,
    pub port: u16,
    session: Arc<Mutex<String>>,
    stop_tx: watch::Sender<bool>,
    task: Option<tokio::task::JoinHandle<()>>,
}

impl Bridge {
    /// Gets a session from the relay at `relay` and starts passing friends to 127.0.0.1:`target_port`.
    /// `new_session` is told the new id if the relay closes the session and the bridge opens a new one
    /// (once). `ended` is told why if the bridge stops by itself.
    pub async fn start(
        relay: (String, u16),
        target_port: u16,
        limits: Limits,
        log: Log,
        new_session: Box<dyn Fn(String) + Send + Sync>,
        ended: Box<dyn FnOnce(String) + Send>,
    ) -> Result<Bridge, String> {
        let t = Instant::now();
        let (stream, id) = open_session(&relay).await?;
        log(format!("the relay gave a session in {} ms", t.elapsed().as_millis()));
        let session = Arc::new(Mutex::new(STANDARD.encode(id)));
        let (stop_tx, stop_rx) = watch::channel(false);
        let ctx = Ctx { relay: relay.clone(), target_port, limits, log };
        let shared = session.clone();
        let task = tokio::spawn(run(ctx, stream, stop_rx, shared, new_session, ended));
        Ok(Bridge { server: relay.0, port: relay.1, session, stop_tx, task: Some(task) })
    }

    /// The current session id (base64), for friends' `--mitm-session=`.
    pub fn session(&self) -> String {
        self.session.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }

    /// Closes the session and every link, and waits (briefly) until they are closed.
    pub async fn stop(mut self) {
        let _ = self.stop_tx.send(true);
        if let Some(task) = self.task.take() {
            let abort = task.abort_handle();
            if timeout(Duration::from_secs(3), task).await.is_err() {
                abort.abort();
            }
        }
    }
}

impl Drop for Bridge {
    fn drop(&mut self) {
        let _ = self.stop_tx.send(true);
        if let Some(task) = self.task.take() {
            task.abort(); // aborting it drops its JoinSet, which aborts every link
        }
    }
}

#[derive(Clone)]
struct Ctx {
    relay: (String, u16),
    target_port: u16,
    limits: Limits,
    log: Log,
}

enum End {
    Stopped,
    Closed(String),
}

async fn run(
    ctx: Ctx,
    first: TcpStream,
    mut stop_rx: watch::Receiver<bool>,
    session: Arc<Mutex<String>>,
    new_session: Box<dyn Fn(String) + Send + Sync>,
    ended: Box<dyn FnOnce(String) + Send>,
) {
    let mut links: JoinSet<()> = JoinSet::new();
    let mut count = 0u64;
    let mut stream = first;
    let mut reopened = false;
    let why = loop {
        match session_loop(&ctx, stream, &mut links, &mut stop_rx, &mut count).await {
            End::Stopped => {
                (ctx.log)("Game Night closed the relay session (lobby over)".into());
                break None;
            }
            End::Closed(why) => {
                (ctx.log)(format!("the relay closed the session connection ({why})"));
                if reopened {
                    break Some(format!("the relay closed the session twice ({why})"));
                }
                reopened = true;
                match open_session(&ctx.relay).await {
                    Ok((s, id)) => {
                        let b64 = STANDARD.encode(id);
                        *session.lock().unwrap_or_else(|e| e.into_inner()) = b64.clone();
                        (ctx.log)("opened a new relay session (links already open carry on)".into());
                        new_session(b64);
                        stream = s;
                    }
                    Err(e) => break Some(format!("couldn't open a new relay session: {e}")),
                }
            }
        }
    };
    if let Some(why) = why {
        ended(why);
        // Friends already connected carry on until the lobby ends.
        while links.join_next().await.is_some() {}
    }
    links.shutdown().await;
}

/// Aborts a task when dropped.
struct AbortOnDrop(tokio::task::JoinHandle<()>);
impl Drop for AbortOnDrop {
    fn drop(&mut self) {
        self.0.abort();
    }
}

async fn session_loop(ctx: &Ctx, stream: TcpStream, links: &mut JoinSet<()>, stop_rx: &mut watch::Receiver<bool>, count: &mut u64) -> End {
    let (mut rd, mut wr) = stream.into_split();
    // Messages are read in their own task, so nothing is lost half-read while the loop does something else.
    let (msg_tx, mut msg_rx) = mpsc::channel::<std::io::Result<Msg>>(64);
    let _reader = AbortOnDrop(tokio::spawn(async move {
        loop {
            let m = read_msg(&mut rd).await;
            let end = m.is_err();
            if msg_tx.send(m).await.is_err() || end {
                break;
            }
        }
    }));
    let (ctl_tx, mut ctl_rx) = mpsc::channel::<Vec<u8>>(64);
    let mut waiting: HashMap<[u8; 12], oneshot::Sender<[u8; 16]>> = HashMap::new();
    if *stop_rx.borrow() {
        return End::Stopped;
    }
    loop {
        tokio::select! {
            _ = stop_rx.changed() => return End::Stopped,
            Some(done) = links.join_next(), if !links.is_empty() => {
                if let Err(e) = done {
                    if e.is_panic() {
                        (ctx.log)("a link stopped unexpectedly".into());
                    }
                }
            }
            Some(bytes) = ctl_rx.recv() => {
                if let Err(e) = wr.write_all(&bytes).await {
                    return End::Closed(format!("couldn't write: {e}"));
                }
            }
            m = msg_rx.recv() => match m {
                None => return End::Closed("reader stopped".into()),
                Some(Err(e)) => return End::Closed(e.to_string()),
                Some(Ok(Msg::Ping)) => {
                    if let Err(e) = wr.write_all(&RATP.to_be_bytes()).await {
                        return End::Closed(format!("couldn't answer a ping: {e}"));
                    }
                }
                Some(Ok(Msg::Link(id))) => {
                    waiting.retain(|_, tx| !tx.is_closed());
                    if links.len() >= MOST_LINKS {
                        (ctx.log)("a friend arrived but too many links are open; ignored".into());
                        continue;
                    }
                    let (tx, rx) = oneshot::channel();
                    waiting.insert(id, tx);
                    *count += 1;
                    links.spawn(link(ctx.clone(), *count, id, rx, ctl_tx.clone()));
                }
                Some(Ok(Msg::Addr(id, _addr))) => {
                    if let Some(tx) = waiting.remove(&id) {
                        let _ = tx.send(_addr);
                    }
                }
            }
        }
    }
}

/// One friend: open the link to the relay, pass it to the host's RetroArch, copy both ways until one ends.
async fn link(ctx: Ctx, n: u64, id: [u8; 12], addr: oneshot::Receiver<[u8; 16]>, ctl: mpsc::Sender<Vec<u8>>) {
    let opened = async {
        let mut up = timeout(Duration::from_secs(15), TcpStream::connect((ctx.relay.0.as_str(), ctx.relay.1)))
            .await
            .map_err(|_| "the relay didn't answer".to_string())?
            .map_err(|e| e.to_string())?;
        // Same order as RetroArch: ask for the address on the session connection, then send the link id.
        ctl.send(with_id(RATA, &id)).await.map_err(|_| "session closed".to_string())?;
        timeout(Duration::from_secs(15), addr)
            .await
            .map_err(|_| "no address from the relay in time".to_string())?
            .map_err(|_| "session closed".to_string())?;
        up.write_all(&with_id(RATL, &id)).await.map_err(|e| e.to_string())?;
        let host = timeout(Duration::from_secs(5), TcpStream::connect(("127.0.0.1", ctx.target_port)))
            .await
            .map_err(|_| "the host's game didn't answer".to_string())?
            .map_err(|e| format!("the host's game didn't answer: {e}"))?;
        Ok::<_, String>((up, host))
    }
    .await;
    let (up, host) = match opened {
        Ok(x) => x,
        Err(e) => {
            (ctx.log)(format!("link {n}: a friend's link failed: {e}"));
            return;
        }
    };
    (ctx.log)(format!("link {n}: a friend arrived through the relay and is passed to the host"));
    let t = Instant::now();
    let why = splice(up, host, ctx.limits).await;
    (ctx.log)(format!("link {n}: closed after {} s: {why}", t.elapsed().as_secs()));
}

/// Copies friend <-> host until one side ends. Says who ended it.
pub async fn splice(friend: TcpStream, host: TcpStream, limits: Limits) -> String {
    let _ = friend.set_nodelay(true);
    let _ = host.set_nodelay(true);
    let (mut fr, mut fw) = friend.into_split();
    let (mut hr, mut hw) = host.into_split();
    let t0 = Instant::now();
    let ms = |at: Instant| at.duration_since(t0).as_millis() as u64;
    let last_friend = AtomicU64::new(0);
    let last_host = AtomicU64::new(0);
    let tick = Duration::from_millis(100);

    let friend_to_host = async {
        let mut buf = vec![0u8; 65536];
        let mut run = 0u32; // pieces in a row that came close together
        loop {
            match timeout(tick, fr.read(&mut buf)).await {
                Ok(Ok(0)) => return "the friend's side (relay) closed it".to_string(),
                Ok(Ok(k)) => {
                    let now = ms(Instant::now());
                    let gap = now.saturating_sub(last_friend.load(Ordering::Relaxed));
                    run = if gap < STEADY_GAP.as_millis() as u64 { run.saturating_add(1) } else { 0 };
                    last_friend.store(now, Ordering::Relaxed);
                    if let Err(e) = hw.write_all(&buf[..k]).await {
                        return format!("the host's side broke: {e}");
                    }
                }
                Ok(Err(e)) => return format!("the friend's side broke: {e}"),
                Err(_) => {
                    let now = ms(Instant::now());
                    if (limits.hold)() {
                        // Paused for everyone: silence is expected, so it starts counting again afterwards.
                        last_friend.store(now, Ordering::Relaxed);
                        continue;
                    }
                    let friend_quiet = now.saturating_sub(last_friend.load(Ordering::Relaxed));
                    let host_quiet = now.saturating_sub(last_host.load(Ordering::Relaxed));
                    if friend_quiet >= limits.friend_gone.as_millis() as u64 {
                        return format!("Game Night closed it: the friend's side was silent for {} s", friend_quiet / 1000);
                    }
                    let (limit, who) = if run >= STEADY_RUN { (limits.friend_silent, "player") } else { (limits.watcher_silent, "watcher") };
                    if friend_quiet >= limit.as_millis() as u64 && host_quiet >= limits.host_quiet.as_millis() as u64 {
                        return format!(
                            "Game Night closed it: the friend's side ({who}) was silent for {:.1} s while the host waited",
                            friend_quiet as f64 / 1000.0
                        );
                    }
                }
            }
        }
    };
    let host_to_friend = async {
        let mut buf = vec![0u8; 65536];
        loop {
            match hr.read(&mut buf).await {
                Ok(0) => return "the host (RetroArch) closed it".to_string(),
                Ok(k) => {
                    last_host.store(ms(Instant::now()), Ordering::Relaxed);
                    if let Err(e) = fw.write_all(&buf[..k]).await {
                        return format!("the friend's side broke: {e}");
                    }
                }
                Err(e) => return format!("the host's side broke: {e}"),
            }
        }
    };
    tokio::select! {
        a = friend_to_host => a,
        b = host_to_friend => b,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::net::TcpListener;

    #[tokio::test]
    async fn reads_relay_messages() {
        let mut bytes = RATP.to_be_bytes().to_vec();
        bytes.extend(with_id(RATL, &[7; 12]));
        bytes.extend(with_id(RATA, &[7; 12]));
        bytes.extend([9u8; 16]);
        bytes.extend(0xDEADBEEFu32.to_be_bytes());
        let mut r = &bytes[..];
        assert_eq!(read_msg(&mut r).await.unwrap(), Msg::Ping);
        assert_eq!(read_msg(&mut r).await.unwrap(), Msg::Link([7; 12]));
        assert_eq!(read_msg(&mut r).await.unwrap(), Msg::Addr([7; 12], [9; 16]));
        assert!(read_msg(&mut r).await.is_err()); // unknown
        let short = with_id(RATL, &[1; 12]);
        assert!(read_msg(&mut &short[..8]).await.is_err()); // cut short
    }

    #[test]
    fn lobby_answers() {
        assert_eq!(parse_tunnel("tunnel_addr=1.2.3.4\ntunnel_port=55435\n"), Some(("1.2.3.4".into(), 55435)));
        assert_eq!(parse_tunnel("tunnel_port=55435\r\ntunnel_addr=relay.example.com\r\n"), Some(("relay.example.com".into(), 55435)));
        assert_eq!(parse_tunnel("tunnel_addr=1.2.3.4\n"), None);
        assert_eq!(parse_tunnel("tunnel_addr=-x\ntunnel_port=1\n"), None);
        assert_eq!(parse_tunnel("tunnel_addr=a b\ntunnel_port=1\n"), None);
        assert_eq!(parse_tunnel("tunnel_addr=1.2.3.4\ntunnel_port=0\n"), None);
        assert_eq!(parse_tunnel("tunnel_addr=1.2.3.4\ntunnel_port=99999\n"), None);
        assert_eq!(parse_tunnel("<html>"), None);
    }

    fn logger() -> (Log, Arc<Mutex<Vec<String>>>) {
        let lines = Arc::new(Mutex::new(Vec::new()));
        let l = lines.clone();
        (Arc::new(move |s| l.lock().unwrap().push(s)), lines)
    }

    /// A pretend relay: answers RATS with a session id, and can announce a friend.
    struct FakeRelay {
        listener: TcpListener,
    }

    impl FakeRelay {
        async fn new() -> Self {
            FakeRelay { listener: TcpListener::bind("127.0.0.1:0").await.unwrap() }
        }
        fn addr(&self) -> (String, u16) {
            ("127.0.0.1".into(), self.listener.local_addr().unwrap().port())
        }
        /// Accepts a session connection and hands out session id `n`.
        async fn session(&self, n: u8) -> TcpStream {
            let (mut s, _) = self.listener.accept().await.unwrap();
            let mut ask = [0u8; 16];
            s.read_exact(&mut ask).await.unwrap();
            assert_eq!(&ask[..4], &RATS.to_be_bytes());
            assert_eq!(&ask[4..], &[0u8; 12]);
            s.write_all(&with_id(RATS, &[n; 12])).await.unwrap();
            s
        }
        /// Announces a friend on `ctl` and returns the bridge's link connection, checked.
        async fn friend(&self, ctl: &mut TcpStream, id: [u8; 12]) -> TcpStream {
            ctl.write_all(&with_id(RATL, &id)).await.unwrap();
            let (mut up, _) = self.listener.accept().await.unwrap();
            let mut q = [0u8; 16];
            ctl.read_exact(&mut q).await.unwrap();
            assert_eq!(q.to_vec(), with_id(RATA, &id), "bridge asks for the friend's address");
            let mut a = with_id(RATA, &id);
            a.extend([1u8; 16]);
            ctl.write_all(&a).await.unwrap();
            let mut l = [0u8; 16];
            up.read_exact(&mut l).await.unwrap();
            assert_eq!(l.to_vec(), with_id(RATL, &id), "bridge sends the link id on the new connection");
            up
        }
    }

    async fn start(relay: &FakeRelay, target: u16, limits: Limits) -> (Bridge, Log, Arc<Mutex<Vec<String>>>, mpsc::UnboundedReceiver<String>, mpsc::UnboundedReceiver<String>) {
        let (log, lines) = logger();
        let (news_tx, news) = mpsc::unbounded_channel();
        let (end_tx, end) = mpsc::unbounded_channel();
        let b = Bridge::start(
            relay.addr(),
            target,
            limits,
            log.clone(),
            Box::new(move |s| {
                let _ = news_tx.send(s);
            }),
            Box::new(move |why| {
                let _ = end_tx.send(why);
            }),
        );
        let (b, _) = tokio::join!(b, async {});
        (b.unwrap(), log, lines, news, end)
    }

    #[tokio::test]
    async fn bridge_passes_a_friend_to_the_host_and_answers_pings() {
        let relay = FakeRelay::new().await;
        let host = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let target = host.local_addr().unwrap().port();
        let (started, mut ctl) = tokio::join!(start(&relay, target, Limits::default()), relay.session(5));
        let (bridge, _log, lines, _news, _end) = started;
        assert_eq!(bridge.session(), STANDARD.encode([5u8; 12]));

        ctl.write_all(&RATP.to_be_bytes()).await.unwrap();
        let mut pong = [0u8; 4];
        ctl.read_exact(&mut pong).await.unwrap();
        assert_eq!(u32::from_be_bytes(pong), RATP);

        let mut up = relay.friend(&mut ctl, [3; 12]).await;
        let (mut at_host, _) = host.accept().await.unwrap();
        up.write_all(b"hello").await.unwrap();
        let mut got = [0u8; 5];
        at_host.read_exact(&mut got).await.unwrap();
        assert_eq!(&got, b"hello");
        at_host.write_all(b"world").await.unwrap();
        up.read_exact(&mut got).await.unwrap();
        assert_eq!(&got, b"world");

        bridge.stop().await;
        let mut rest = Vec::new();
        let n = timeout(Duration::from_secs(3), up.read_to_end(&mut rest)).await.expect("link closed on stop");
        assert!(n.is_err() || rest.is_empty());
        let lines = lines.lock().unwrap().join("\n");
        assert!(lines.contains("link 1: a friend arrived"), "{lines}");
        assert!(lines.contains("Game Night closed the relay session"), "{lines}");
    }

    #[tokio::test]
    async fn silent_player_is_closed_but_a_watcher_is_not() {
        let limits = Limits {
            friend_silent: Duration::from_millis(600),
            watcher_silent: Duration::from_millis(1500),
            host_quiet: Duration::from_millis(400),
            friend_gone: Duration::from_secs(5),
            hold: || false,
        };
        let relay = FakeRelay::new().await;
        let host = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let target = host.local_addr().unwrap().port();
        let (started, mut ctl) = tokio::join!(start(&relay, target, limits), relay.session(1));
        let (bridge, _log, lines, _news, _end) = started;

        // A watcher: only a ping every 0.5 s (RetroArch: every 3 s). The host sends to it for a while, then
        // stops (as if waiting for a missing player). The watcher's link stays open throughout.
        let (mut watcher_r, mut watcher_w) = relay.friend(&mut ctl, [1; 12]).await.into_split();
        let (mut host_w, _) = host.accept().await.unwrap();
        let pinger = tokio::spawn(async move {
            loop {
                tokio::time::sleep(Duration::from_millis(500)).await;
                if watcher_w.write_all(b"p").await.is_err() {
                    break;
                }
            }
        });
        for _ in 0..10 {
            host_w.write_all(b"frame").await.unwrap();
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        let mut buf = [0u8; 50];
        watcher_r.read_exact(&mut buf).await.unwrap();

        // A player: buttons every 30 ms, then their internet dies while the host waits (both sides quiet).
        let mut player = relay.friend(&mut ctl, [2; 12]).await;
        let (mut host_p, _) = host.accept().await.unwrap();
        for _ in 0..15 {
            player.write_all(b"in").await.unwrap();
            tokio::time::sleep(Duration::from_millis(30)).await;
        }
        let t = Instant::now();
        let mut rest = Vec::new();
        timeout(Duration::from_secs(3), host_p.read_to_end(&mut rest)).await.expect("closed").unwrap();
        assert!(t.elapsed() >= Duration::from_millis(500), "{:?}", t.elapsed());
        assert!(t.elapsed() < Duration::from_millis(1400), "{:?}", t.elapsed());
        tokio::time::sleep(Duration::from_millis(1200)).await; // the watcher is still fine after a long host pause
        let lines = lines.lock().unwrap().join("\n");
        assert!(lines.contains("link 2: closed") && lines.contains("(player) was silent"), "{lines}");
        assert!(!lines.contains("link 1: closed"), "{lines}");
        pinger.abort();
        drop(bridge);
    }

    #[tokio::test]
    async fn silent_watcher_is_closed_after_its_longer_limit() {
        let limits = Limits {
            friend_silent: Duration::from_millis(300),
            watcher_silent: Duration::from_millis(900),
            host_quiet: Duration::from_millis(200),
            friend_gone: Duration::from_secs(5),
            hold: || false,
        };
        let relay = FakeRelay::new().await;
        let host = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let target = host.local_addr().unwrap().port();
        let (started, mut ctl) = tokio::join!(start(&relay, target, limits), relay.session(1));
        let (bridge, _log, lines, _news, _end) = started;
        let _watcher = relay.friend(&mut ctl, [1; 12]).await;
        let (mut host_w, _) = host.accept().await.unwrap();
        let t = Instant::now();
        let mut rest = Vec::new();
        timeout(Duration::from_secs(3), host_w.read_to_end(&mut rest)).await.expect("closed").unwrap();
        assert!(t.elapsed() >= Duration::from_millis(800), "{:?}", t.elapsed());
        assert!(lines.lock().unwrap().join("\n").contains("(watcher) was silent"));
        drop(bridge);
    }


    #[tokio::test]
    async fn relay_closing_the_session_opens_one_new_session_then_gives_up() {
        let relay = FakeRelay::new().await;
        let (started, ctl) = tokio::join!(start(&relay, 9, Limits::default()), relay.session(1));
        let (bridge, _log, _lines, mut news, mut end) = started;
        drop(ctl);
        let ctl2 = relay.session(2).await;
        let new = timeout(Duration::from_secs(3), news.recv()).await.unwrap().unwrap();
        assert_eq!(new, STANDARD.encode([2u8; 12]));
        assert_eq!(bridge.session(), new);
        drop(ctl2);
        let why = timeout(Duration::from_secs(3), end.recv()).await.unwrap().unwrap();
        assert!(why.contains("twice"), "{why}");
        bridge.stop().await;
    }

    #[tokio::test]
    async fn no_session_from_the_relay_is_an_error() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        tokio::spawn(async move {
            let (mut s, _) = listener.accept().await.unwrap();
            let mut ask = [0u8; 16];
            s.read_exact(&mut ask).await.unwrap();
            s.write_all(&with_id(RATS, &[0; 12])).await.unwrap(); // all zeros = no session
        });
        let (log, _) = logger();
        let r = Bridge::start(("127.0.0.1".into(), port), 9, Limits::default(), log, Box::new(|_| {}), Box::new(|_| {})).await;
        assert!(r.is_err());
    }

    static HOLD_TEST: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

    #[tokio::test]
    async fn no_link_is_closed_while_paused_for_everyone() {
        let limits = Limits {
            friend_silent: Duration::from_millis(300),
            watcher_silent: Duration::from_millis(500),
            host_quiet: Duration::from_millis(200),
            friend_gone: Duration::from_millis(900),
            hold: || HOLD_TEST.load(Ordering::SeqCst),
        };
        let relay = FakeRelay::new().await;
        let host = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let target = host.local_addr().unwrap().port();
        let (started, mut ctl) = tokio::join!(start(&relay, target, limits), relay.session(1));
        let (bridge, _log, lines, _news, _end) = started;

        // A player sends buttons, then the game is paused for everyone: both sides go silent for 1.5 s,
        // longer than every limit. The link stays open, and still carries data afterwards.
        let mut player = relay.friend(&mut ctl, [3; 12]).await;
        let (mut host_p, _) = host.accept().await.unwrap();
        for _ in 0..15 {
            player.write_all(b"in").await.unwrap();
            tokio::time::sleep(Duration::from_millis(30)).await;
        }
        let mut got = [0u8; 30];
        host_p.read_exact(&mut got).await.unwrap();
        HOLD_TEST.store(true, Ordering::SeqCst);
        tokio::time::sleep(Duration::from_millis(1500)).await;
        HOLD_TEST.store(false, Ordering::SeqCst);
        player.write_all(b"back").await.unwrap();
        let mut back = [0u8; 4];
        timeout(Duration::from_secs(2), host_p.read_exact(&mut back)).await.expect("still open").unwrap();
        assert_eq!(&back, b"back");
        let text = lines.lock().unwrap().join("\n");
        assert!(!text.contains("closed after"), "{text}");

        // Once the pause is over, silence counts again: the link is closed as before.
        let mut rest = Vec::new();
        timeout(Duration::from_secs(3), host_p.read_to_end(&mut rest)).await.expect("closed after the pause").unwrap();
        drop(bridge);
    }
}
