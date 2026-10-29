//! Reads the plugged-in controller straight from Windows and tells the menus about it.
//! (The web page's own controller support doesn't reach the app on Windows, so we do it here.)
//! Xbox-style pads are read from their XInput slot; other pads through gilrs.
//! Sends a "pad" event whenever something changes: buttons in the standard web order
//! (0 A, 1 B, 2 X, 3 Y, 4 LB, 5 RB, 6 LT, 7 RT, 8 View/Share, 9 Menu/Options, 10/11 sticks,
//! 12-15 D-pad up/down/left/right, 16 Xbox/PS) and sticks (left x/y, right x/y, down is +).
//! Only reads input; nothing is ever sent to the controller.

use serde::Serialize;
use std::sync::Mutex;

/// The controller someone last pressed a button on in Game Night (vendor and product id). The game
/// gives Player 1 to it, so a keyboard or other device posing as a controller can't take Player 1
/// (Jayden's Razer Huntsman does exactly that).
pub static LAST_USED: Mutex<Option<(u16, u16)>> = Mutex::new(None);

#[cfg_attr(not(windows), allow(dead_code))]
#[derive(Clone, Debug, Default, PartialEq, Serialize)]
pub struct PadState {
    pub connected: bool,
    pub name: String,
    /// USB id, "vvvv:pppp", so Settings can show which controller is in use.
    pub id: String,
    pub buttons: Vec<bool>,
    pub axes: Vec<f32>,
}

#[cfg_attr(not(windows), allow(dead_code))]
/// Small stick wobbles are ignored, and values are rounded so a resting stick doesn't spam events.
pub fn tidy_axis(v: f32) -> f32 {
    if !v.is_finite() || v.abs() < 0.15 {
        return 0.0;
    }
    (v.clamp(-1.0, 1.0) * 20.0).round() / 20.0
}

/// The 17 buttons from an XInput reading, in the web order above.
#[cfg_attr(not(windows), allow(dead_code))]
pub fn xinput_buttons(w: u16, left_trigger: u8, right_trigger: u8) -> Vec<bool> {
    const ORDER: [u16; 17] = [
        0x1000, 0x2000, 0x4000, 0x8000, // A B X Y
        0x0100, 0x0200, // LB RB
        0, 0, // LT RT (from the triggers below)
        0x0020, 0x0010, // View, Menu
        0x0040, 0x0080, // stick clicks
        0x0001, 0x0002, 0x0004, 0x0008, // D-pad up down left right
        0x0400, // Xbox button
    ];
    ORDER
        .iter()
        .enumerate()
        .map(|(i, bit)| match i {
            6 => left_trigger > 64,
            7 => right_trigger > 64,
            _ => w & bit != 0,
        })
        .collect()
}

/// A stick value from XInput (-32768..32767) as -1..1.
#[cfg_attr(not(windows), allow(dead_code))]
pub fn xinput_axis(v: i16) -> f32 {
    (v as f32 / 32767.0).clamp(-1.0, 1.0)
}

#[cfg(windows)]
pub fn start<R: tauri::Runtime>(app: tauri::AppHandle<R>) {
    use gilrs::{Axis, Button, EventType, GamepadId, Gilrs};
    use std::io::Write;
    use std::time::Duration;
    use tauri::{Emitter, Manager};
    use windows::Win32::UI::Input::XboxController::XINPUT_STATE;

    const BUTTONS: [Button; 17] = [
        Button::South,
        Button::East,
        Button::West,
        Button::North,
        Button::LeftTrigger,
        Button::RightTrigger,
        Button::LeftTrigger2,
        Button::RightTrigger2,
        Button::Select,
        Button::Start,
        Button::LeftThumb,
        Button::RightThumb,
        Button::DPadUp,
        Button::DPadDown,
        Button::DPadLeft,
        Button::DPadRight,
        Button::Mode,
    ];

    /// Where a controller is read from. Xbox-style pads are read straight from their XInput slot,
    /// which works on every PC (on Jayden's, gilrs never saw his pad's presses). gilrs covers the rest,
    /// such as PlayStation pads.
    #[derive(Clone, Copy, PartialEq, Debug)]
    enum Source {
        Slot(usize),
        Gilrs(GamepadId),
    }

    // XInputGetStateEx (xinput1_4.dll ordinal 100) also reads the Xbox button; plain XInputGetState if not.
    type GetState = unsafe extern "system" fn(u32, *mut XINPUT_STATE) -> u32;
    let get_state: GetState = unsafe {
        use windows::Win32::System::LibraryLoader::{GetProcAddress, LoadLibraryW};
        LoadLibraryW(windows::core::w!("xinput1_4.dll"))
            .ok()
            .and_then(|dll| GetProcAddress(dll, windows::core::PCSTR(100usize as *const u8)))
            .map(|f| std::mem::transmute::<_, GetState>(f))
            .unwrap_or(windows::Win32::UI::Input::XboxController::XInputGetState as GetState)
    };
    let read_slot = move |slot: usize| -> Option<XINPUT_STATE> {
        let mut st = XINPUT_STATE::default();
        (unsafe { get_state(slot as u32, &mut st) } == 0).then_some(st)
    };

    // A short note of what the menus can see, next to RetroArch's log, so problems can be spotted.
    let log_path = app.path().app_cache_dir().ok().map(|d| d.join("player").join("logs").join("pads.txt"));
    let mut log_lines = 0usize;
    let mut note = move |line: String| {
        let Some(path) = &log_path else { return };
        if log_lines >= 400 {
            return;
        }
        if log_lines == 0 {
            if let Some(dir) = path.parent() {
                let _ = std::fs::create_dir_all(dir);
            }
            let _ = std::fs::write(path, "");
        }
        log_lines += 1;
        if let Ok(mut f) = std::fs::OpenOptions::new().append(true).open(path) {
            let _ = writeln!(f, "{line}");
        }
    };

    std::thread::spawn(move || {
        let mut gilrs = match Gilrs::new() {
            Ok(g) => Some(g),
            Err(gilrs::Error::NotImplemented(g)) => Some(g),
            Err(e) => {
                note(format!("gilrs didn't start: {e}"));
                None
            }
        };
        note(format!("Game Night {} reading controllers", env!("CARGO_PKG_VERSION")));
        let mut last = PadState::default();
        // The menus follow whichever controller was pressed last.
        let mut active: Option<Source> = None;
        // Controllers turned off in Settings are ignored completely. Re-read about once a second.
        let mut off: Vec<(u16, u16)> = Vec::new();
        let mut slot_ids: [Option<(u16, u16)>; 4] = [None; 4];
        let mut prev_slot: [Vec<bool>; 4] = Default::default();
        // Asking Windows about an empty slot is slow, so empty slots are only checked about once a second.
        let mut present = [true; 4];
        let mut seen = String::new();
        let mut was_focused = None;
        let mut presses_noted = 0;
        let mut tick = 0u32;
        let usb = |p: &gilrs::Gamepad| p.vendor_id().zip(p.product_id());
        loop {
            let focused = window_in_front();
            if was_focused != Some(focused) {
                note(format!("Game Night window in front: {focused}"));
                was_focused = Some(focused);
            }
            if tick % 125 == 0 {
                off = crate::controllers::disabled_ids(&app);
                for (i, id) in slot_ids.iter_mut().enumerate() {
                    present[i] = read_slot(i).is_some();
                    *id = if present[i] { crate::retroports::slot_id(i as u32) } else { None };
                }
                let mut now_seen: Vec<String> = slot_ids
                    .iter()
                    .enumerate()
                    .filter_map(|(i, id)| id.map(|id| format!("xinput slot {}: {}", i + 1, crate::controllers::id(id))))
                    .collect();
                if let Some(g) = &gilrs {
                    for (gid, p) in g.gamepads() {
                        now_seen.push(format!(
                            "gilrs {gid}: {} ({}) connected {}",
                            p.name(),
                            usb(&p).map(crate::controllers::id).unwrap_or_else(|| "no id".into()),
                            p.is_connected()
                        ));
                    }
                }
                now_seen.push(format!(
                    "turned off: {}",
                    off.iter().map(|&i| crate::controllers::id(i)).collect::<Vec<_>>().join(", ")
                ));
                let now_seen = now_seen.join("\n");
                if now_seen != seen {
                    note(format!("--- controllers\n{now_seen}"));
                    seen = now_seen;
                }
            }
            tick = tick.wrapping_add(1);
            let slot_allowed = |i: usize, ids: &[Option<(u16, u16)>; 4]| !ids[i].is_some_and(|u| off.contains(&u));
            let gilrs_allowed = |p: &gilrs::Gamepad| !usb(p).is_some_and(|u| off.contains(&u));

            // gilrs presses (PlayStation pads and anything else).
            if let Some(g) = &mut gilrs {
                while let Some(ev) = g.next_event() {
                    match ev.event {
                        EventType::ButtonPressed(b, _) if focused && gilrs_allowed(&g.gamepad(ev.id)) => {
                            active = Some(Source::Gilrs(ev.id));
                            let id = usb(&g.gamepad(ev.id));
                            if let Some(u) = id {
                                *LAST_USED.lock().unwrap_or_else(|e| e.into_inner()) = Some(u);
                            }
                            if presses_noted < 40 {
                                presses_noted += 1;
                                note(format!("press {b:?} on gilrs {} ({})", ev.id, id.map(crate::controllers::id).unwrap_or_default()));
                            }
                        }
                        EventType::Disconnected if active == Some(Source::Gilrs(ev.id)) => active = None,
                        _ => {}
                    }
                }
            }

            // Xbox-style pads, straight from their XInput slots. A slot's presses are checked last, so an
            // Xbox pad that gilrs also sees ends up read from its slot.
            let mut slots: [Option<XINPUT_STATE>; 4] = [None; 4];
            for (i, st) in slots.iter_mut().enumerate() {
                *st = if present[i] { read_slot(i) } else { None };
                if st.is_none() {
                    present[i] = false;
                }
                let Some(s) = st else {
                    prev_slot[i].clear();
                    if active == Some(Source::Slot(i)) {
                        active = None;
                    }
                    continue;
                };
                let g = s.Gamepad;
                let now = xinput_buttons(g.wButtons.0, g.bLeftTrigger, g.bRightTrigger);
                let pressed = now.iter().enumerate().find(|(b, d)| **d && !prev_slot[i].get(*b).copied().unwrap_or(false));
                if let Some((b, _)) = pressed {
                    if focused && slot_allowed(i, &slot_ids) {
                        active = Some(Source::Slot(i));
                        if let Some(u) = slot_ids[i] {
                            *LAST_USED.lock().unwrap_or_else(|e| e.into_inner()) = Some(u);
                        }
                        if presses_noted < 40 {
                            presses_noted += 1;
                            note(format!(
                                "press button {b} on xinput slot {} ({})",
                                i + 1,
                                slot_ids[i].map(crate::controllers::id).unwrap_or_default()
                            ));
                        }
                    }
                }
                prev_slot[i] = now;
            }
            if active.is_some_and(|a| match a {
                Source::Slot(i) => !slot_allowed(i, &slot_ids),
                Source::Gilrs(id) => gilrs.as_ref().is_none_or(|g| !g.gamepad(id).is_connected() || !gilrs_allowed(&g.gamepad(id))),
            }) {
                active = None;
            }

            // Nothing pressed yet: an Xbox-style slot first, then anything gilrs sees.
            let source = active
                .or_else(|| (0..4).find(|&i| slots[i].is_some() && slot_allowed(i, &slot_ids)).map(Source::Slot))
                .or_else(|| {
                    gilrs.as_ref().and_then(|g| g.gamepads().find(|(_, p)| p.is_connected() && gilrs_allowed(p)).map(|(id, _)| Source::Gilrs(id)))
                });
            let now = match source {
                Some(Source::Slot(i)) => match slots[i] {
                    Some(s) => {
                        let g = s.Gamepad;
                        PadState {
                            connected: true,
                            name: "Xbox controller".into(),
                            id: slot_ids[i].map(crate::controllers::id).unwrap_or_default(),
                            buttons: if focused {
                                xinput_buttons(g.wButtons.0, g.bLeftTrigger, g.bRightTrigger)
                            } else {
                                vec![false; 17]
                            },
                            axes: [g.sThumbLX, g.sThumbLY, g.sThumbRX, g.sThumbRY]
                                .iter()
                                .enumerate()
                                .map(|(n, v)| {
                                    let v = if focused { xinput_axis(*v) } else { 0.0 };
                                    // Windows says up is +, the web says down is +.
                                    tidy_axis(if n % 2 == 1 { -v } else { v })
                                })
                                .collect(),
                        }
                    }
                    None => PadState::default(),
                },
                Some(Source::Gilrs(id)) => match gilrs.as_ref().and_then(|g| g.connected_gamepad(id)) {
                    Some(p) => PadState {
                        connected: true,
                        name: p.name().chars().take(80).collect(),
                        id: usb(&p).map(crate::controllers::id).unwrap_or_default(),
                        buttons: BUTTONS.iter().map(|b| focused && p.is_pressed(*b)).collect(),
                        axes: [Axis::LeftStickX, Axis::LeftStickY, Axis::RightStickX, Axis::RightStickY]
                            .iter()
                            .enumerate()
                            .map(|(n, a)| {
                                let v = if focused { p.value(*a) } else { 0.0 };
                                tidy_axis(if n % 2 == 1 { -v } else { v })
                            })
                            .collect(),
                    },
                    None => PadState::default(),
                },
                None => PadState::default(),
            };
            if now != last {
                let _ = app.emit("pad", &now);
                last = now;
            }
            std::thread::sleep(Duration::from_millis(8));
        }
    });
}

/// Presses only count while Game Night is the window in front (not while a game or another app is).
/// Asks Windows directly rather than relying on window focus events.
#[cfg(windows)]
fn window_in_front() -> bool {
    use windows::Win32::UI::WindowsAndMessaging::{GetForegroundWindow, GetWindowThreadProcessId};
    unsafe {
        let w = GetForegroundWindow();
        if w.is_invalid() {
            return false;
        }
        let mut pid = 0u32;
        GetWindowThreadProcessId(w, Some(&mut pid));
        pid == std::process::id()
    }
}

#[cfg(not(windows))]
pub fn start<R: tauri::Runtime>(_app: tauri::AppHandle<R>) {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn xinput_buttons_come_out_in_web_order() {
        let b = xinput_buttons(0x1000 | 0x0001 | 0x0400, 0, 200);
        let on: Vec<usize> = b.iter().enumerate().filter(|(_, d)| **d).map(|(i, _)| i).collect();
        assert_eq!(on, vec![0, 7, 12, 16]); // A, RT, D-pad up, Xbox button
        assert_eq!(xinput_buttons(0, 0, 0).len(), 17);
        assert_eq!(xinput_axis(i16::MIN), -1.0);
        assert_eq!(xinput_axis(32767), 1.0);
    }

    #[test]
    fn resting_sticks_read_as_zero() {
        assert_eq!(tidy_axis(0.08), 0.0);
        assert_eq!(tidy_axis(-0.1), 0.0);
        assert_eq!(tidy_axis(f32::NAN), 0.0);
        assert_eq!(tidy_axis(0.93), 0.95);
        assert_eq!(tidy_axis(-2.0), -1.0);
    }
}
