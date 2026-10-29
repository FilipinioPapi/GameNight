//! Reads the plugged-in controller straight from Windows and tells the menus about it.
//! (The web page's own controller support doesn't reach the app on Windows, so we do it here.)
//! Sends a "pad" event whenever something changes: buttons in the standard web order
//! (0 A, 1 B, 2 X, 3 Y, 4 LB, 5 RB, 6 LT, 7 RT, 8 View/Share, 9 Menu/Options, 10/11 sticks,
//! 12-15 D-pad up/down/left/right, 16 Xbox/PS) and sticks (left x/y, right x/y, down is +).
//! Only reads input; nothing is ever sent to the controller.

use serde::Serialize;

#[derive(Clone, Debug, Default, PartialEq, Serialize)]
pub struct PadState {
    pub connected: bool,
    pub name: String,
    pub buttons: Vec<bool>,
    pub axes: Vec<f32>,
}

/// Small stick wobbles are ignored, and values are rounded so a resting stick doesn't spam events.
pub fn tidy_axis(v: f32) -> f32 {
    if !v.is_finite() || v.abs() < 0.15 {
        return 0.0;
    }
    (v.clamp(-1.0, 1.0) * 20.0).round() / 20.0
}

#[cfg(windows)]
pub fn start<R: tauri::Runtime>(app: tauri::AppHandle<R>) {
    use gilrs::{Axis, Button, Gilrs};
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;
    use std::time::Duration;
    use tauri::{Emitter, Manager};

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

    // Presses only count while Game Night is the window in front.
    let focused = Arc::new(AtomicBool::new(true));
    if let Some(w) = app.get_webview_window("main") {
        let flag = focused.clone();
        w.on_window_event(move |e| {
            if let tauri::WindowEvent::Focused(f) = e {
                flag.store(*f, Ordering::Relaxed);
            }
        });
    }

    std::thread::spawn(move || {
        let mut gilrs = match Gilrs::new() {
            Ok(g) => g,
            Err(gilrs::Error::NotImplemented(g)) => g,
            Err(_) => return,
        };
        let mut last = PadState::default();
        loop {
            while gilrs.next_event().is_some() {}
            let focused = focused.load(Ordering::Relaxed);
            let now = match gilrs.gamepads().find(|(_, p)| p.is_connected()) {
                Some((_, p)) => PadState {
                    connected: true,
                    name: p.name().chars().take(80).collect(),
                    buttons: BUTTONS.iter().map(|b| focused && p.is_pressed(*b)).collect(),
                    axes: [Axis::LeftStickX, Axis::LeftStickY, Axis::RightStickX, Axis::RightStickY]
                        .iter()
                        .enumerate()
                        .map(|(i, a)| {
                            let v = if focused { p.value(*a) } else { 0.0 };
                            // Windows says up is +, the web says down is +.
                            tidy_axis(if i % 2 == 1 { -v } else { v })
                        })
                        .collect(),
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

#[cfg(not(windows))]
pub fn start<R: tauri::Runtime>(_app: tauri::AppHandle<R>) {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resting_sticks_read_as_zero() {
        assert_eq!(tidy_axis(0.08), 0.0);
        assert_eq!(tidy_axis(-0.1), 0.0);
        assert_eq!(tidy_axis(f32::NAN), 0.0);
        assert_eq!(tidy_axis(0.93), 0.95);
        assert_eq!(tidy_axis(-2.0), -1.0);
    }
}
