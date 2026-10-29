//! Settings › Controllers: the list of controllers on this PC, which one is Player 1, and which
//! ones are turned off. A turned-off controller is ignored by Game Night's menus and is parked by
//! RetroArch on a player number no game uses, so a keyboard posing as a controller (Jayden's Razer
//! Huntsman) can never take over. Saved in Game Night's settings folder on this PC only.

use crate::retroports::{self, Device};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::{AppHandle, Manager, Runtime};

/// One controller, as both RetroArch and Game Night's menus know it.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Pad {
    pub name: String,
    /// RetroArch's id, "vvvv:pppp".
    pub ra: String,
    /// The USB id the menus see, "vvvv:pppp".
    pub usb: String,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Prefs {
    /// None: Automatic (Player 1 is whichever controller you last pressed in Game Night).
    pub player1: Option<Pad>,
    pub disabled: Vec<Pad>,
}

#[derive(Serialize)]
pub struct Row {
    #[serde(flatten)]
    pad: Pad,
    connected: bool,
    disabled: bool,
    player1: bool,
}

static PREFS: Mutex<Option<Prefs>> = Mutex::new(None);

/// Most players RetroArch is told about. Turned-off controllers are parked above this.
pub const PLAYERS: usize = 4;
const MOST_DISABLED: usize = 12;

pub fn id((v, p): (u16, u16)) -> String {
    format!("{v:04x}:{p:04x}")
}

/// Reads back an id, only if it's exactly "vvvv:pppp".
pub fn parse_id(s: &str) -> Option<(u16, u16)> {
    let (v, p) = s.trim().split_once(':')?;
    if v.len() != 4 || p.len() != 4 {
        return None;
    }
    Some((u16::from_str_radix(v, 16).ok()?, u16::from_str_radix(p, 16).ok()?))
}

fn pad_of(d: &Device) -> Pad {
    Pad { name: d.name.clone(), ra: id(d.ra), usb: id(d.usb) }
}

fn file<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    Some(app.path().app_config_dir().ok()?.join("player").join("controllers.json"))
}

/// Only well-formed, short entries are kept, so a damaged file can't do anything odd.
fn tidy(mut p: Prefs) -> Prefs {
    let ok = |x: &Pad| parse_id(&x.ra).is_some() && parse_id(&x.usb).is_some();
    let trim = |mut x: Pad| {
        x.name = x.name.chars().filter(|c| !c.is_control()).take(80).collect();
        x
    };
    p.player1 = p.player1.filter(ok).map(trim);
    p.disabled = p.disabled.into_iter().filter(ok).map(trim).take(MOST_DISABLED).collect();
    p.disabled.dedup();
    if let Some(p1) = &p.player1 {
        if p.disabled.iter().any(|d| d.ra == p1.ra && d.usb == p1.usb) {
            p.player1 = None;
        }
    }
    p
}

/// The saved choices (read from disk the first time).
pub fn prefs<R: Runtime>(app: &AppHandle<R>) -> Prefs {
    let mut g = PREFS.lock().unwrap_or_else(|e| e.into_inner());
    if g.is_none() {
        let saved = file(app)
            .and_then(|f| fs::read_to_string(f).ok())
            .and_then(|t| serde_json::from_str::<Prefs>(&t).ok())
            .map(tidy)
            .unwrap_or_default();
        *g = Some(saved);
    }
    g.clone().unwrap_or_default()
}

/// USB ids of the turned-off controllers, for the menus to skip.
#[cfg_attr(not(windows), allow(dead_code))]
pub fn disabled_usb<R: Runtime>(app: &AppHandle<R>) -> Vec<(u16, u16)> {
    prefs(app).disabled.iter().filter_map(|d| parse_id(&d.usb)).collect()
}

/// Every controller plugged in now, plus saved ones that are unplugged (so they can be turned back on).
#[tauri::command]
pub fn list_controllers<R: Runtime>(app: AppHandle<R>) -> Vec<Row> {
    let p = prefs(&app);
    let is_off = |x: &Pad| p.disabled.iter().any(|d| d.ra == x.ra && d.usb == x.usb);
    let is_p1 = |x: &Pad| p.player1.as_ref().is_some_and(|d| d.ra == x.ra && d.usb == x.usb);
    let mut rows: Vec<Row> = Vec::new();
    for d in retroports::devices() {
        let pad = pad_of(&d);
        if rows.iter().any(|r| r.pad == pad) {
            continue; // two identical controllers show once: the setting applies to both
        }
        rows.push(Row { disabled: is_off(&pad), player1: is_p1(&pad), pad, connected: true });
    }
    for pad in p.disabled.iter().chain(p.player1.iter()) {
        if !rows.iter().any(|r| r.pad.ra == pad.ra && r.pad.usb == pad.usb) {
            rows.push(Row { disabled: is_off(pad), player1: is_p1(pad), pad: pad.clone(), connected: false });
        }
    }
    rows
}

#[tauri::command]
pub fn save_controllers<R: Runtime>(app: AppHandle<R>, prefs: Prefs) -> Result<(), String> {
    let prefs = tidy(prefs);
    let f = file(&app).ok_or("No settings folder.")?;
    if let Some(dir) = f.parent() {
        fs::create_dir_all(dir).map_err(|_| "Couldn't save the controller settings.")?;
    }
    let text = serde_json::to_string_pretty(&prefs).map_err(|_| "Couldn't save the controller settings.")?;
    fs::write(&f, text).map_err(|_| "Couldn't save the controller settings.")?;
    *PREFS.lock().unwrap_or_else(|e| e.into_inner()) = Some(prefs);
    Ok(())
}

/// What RetroArch is told for one game.
#[derive(Debug, Default, PartialEq)]
pub struct Plan {
    /// RetroArch id of the controller that should be Player 1.
    pub player1: Option<String>,
    /// RetroArch ids parked on unused players (5, 6, ...) so no game sees them.
    pub parked: Vec<String>,
}

/// Works out Player 1 and the parked controllers from what's plugged in.
/// `last_used`: USB id of the controller last pressed in Game Night's menus.
pub fn plan(prefs: &Prefs, plugged: &[Device], last_used: Option<(u16, u16)>, remembered: Option<&str>) -> Plan {
    let parked: Vec<String> = prefs
        .disabled
        .iter()
        .map(|d| d.ra.clone())
        .fold(Vec::new(), |mut v, ra| {
            if !v.contains(&ra) {
                v.push(ra);
            }
            v
        });
    let usable = |ra: &str| !parked.iter().any(|p| p == ra);
    let chosen = prefs
        .player1
        .as_ref()
        .filter(|p| plugged.iter().any(|d| id(d.ra) == p.ra))
        .map(|p| p.ra.clone());
    let pressed = last_used.and_then(|u| plugged.iter().find(|d| d.usb == u)).map(|d| id(d.ra));
    let player1 = chosen
        .or(pressed)
        .or(remembered.and_then(parse_id).map(id))
        .filter(|ra| usable(ra));
    Plan { player1, parked }
}

/// True when Steam is running (it writes its process number here while it's open).
#[tauri::command]
pub fn steam_running() -> bool {
    #[cfg(windows)]
    unsafe {
        use windows::Win32::System::Registry::{RegGetValueW, HKEY_CURRENT_USER, RRF_RT_REG_DWORD};
        let mut pid = 0u32;
        let mut size = 4u32;
        let r = RegGetValueW(
            HKEY_CURRENT_USER,
            windows::core::w!("Software\\Valve\\Steam\\ActiveProcess"),
            windows::core::w!("pid"),
            RRF_RT_REG_DWORD,
            None,
            Some(&mut pid as *mut u32 as *mut _),
            Some(&mut size),
        );
        return r.is_ok() && pid != 0;
    }
    #[allow(unreachable_code)]
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pad(name: &str, ra: &str, usb: &str) -> Pad {
        Pad { name: name.into(), ra: ra.into(), usb: usb.into() }
    }

    // Jayden's PC: the Razer keyboard's joystick first, then the Xbox Series pad.
    fn jaydens() -> Vec<Device> {
        vec![
            Device { name: "Razer Huntsman V3 Pro Tenkeyless".into(), ra: (0x1532, 0x02a7), usb: (0x1532, 0x02a7) },
            Device { name: "Controller (Xbox One For Windows)".into(), ra: (0x045e, 0x02ff), usb: (0x045e, 0x0b12) },
        ]
    }

    #[test]
    fn ids_round_trip() {
        assert_eq!(id((0x045e, 0x0b12)), "045e:0b12");
        assert_eq!(parse_id("045e:0b12\n"), Some((0x045e, 0x0b12)));
        assert_eq!(parse_id("45e:b12"), None);
        assert_eq!(parse_id("zzzz:0b12"), None);
        assert_eq!(parse_id("045e:0b12:1"), None);
    }

    #[test]
    fn automatic_gives_player_1_to_the_pad_pressed_in_the_menus() {
        let p = plan(&Prefs::default(), &jaydens(), Some((0x045e, 0x0b12)), None);
        assert_eq!(p.player1.as_deref(), Some("045e:02ff")); // RetroArch's id, not the USB one
        assert!(p.parked.is_empty());
    }

    #[test]
    fn a_turned_off_controller_is_parked_and_never_player_1() {
        let prefs = Prefs { player1: None, disabled: vec![pad("Razer", "1532:02a7", "1532:02a7")] };
        let p = plan(&prefs, &jaydens(), Some((0x1532, 0x02a7)), None);
        assert_eq!(p.player1, None);
        assert_eq!(p.parked, vec!["1532:02a7".to_string()]);
    }

    #[test]
    fn a_chosen_controller_wins_when_plugged_in() {
        let prefs = Prefs { player1: Some(pad("Xbox", "045e:02ff", "045e:0b12")), disabled: vec![] };
        assert_eq!(plan(&prefs, &jaydens(), Some((0x1532, 0x02a7)), None).player1.as_deref(), Some("045e:02ff"));
        // Unplugged: back to the one pressed in the menus.
        assert_eq!(plan(&prefs, &jaydens()[..1], Some((0x1532, 0x02a7)), None).player1.as_deref(), Some("1532:02a7"));
    }

    #[test]
    fn falls_back_to_the_one_remembered_from_last_time() {
        assert_eq!(plan(&Prefs::default(), &jaydens(), None, Some("045e:02ff")).player1.as_deref(), Some("045e:02ff"));
        assert_eq!(plan(&Prefs::default(), &jaydens(), None, Some("junk")).player1, None);
    }

    #[test]
    fn damaged_settings_are_cleaned_up() {
        let p = tidy(Prefs {
            player1: Some(pad("Razer", "1532:02a7", "1532:02a7")),
            disabled: vec![pad("Razer", "1532:02a7", "1532:02a7"), pad("bad\n", "nope", "045e:0b12")],
        });
        assert_eq!(p.player1, None); // can't be Player 1 and turned off
        assert_eq!(p.disabled.len(), 1);
    }
}
