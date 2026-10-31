//! How the game looks on YOUR screen (in-game menu, "My screen" tab; boards IG1-IG2, approved 2026-10-31):
//! whole-pixel ("integer") scaling, a bezel picture around the game, and a "look" (a RetroArch shader).
//! None of this changes the game itself, so in Couch Play every player picks their own and the game stays
//! in sync (measured: tools/e2e/ingame_menu_test.py, 0 frames different with a different look per player).
//!
//! Bezels: B "tv" (NyNy77's dark TV frames, the default), A "photo" (Nosh01's console photos) and C "pad"
//! (libretro's animated NES pad / Super Famicom border). A and B are pictures with a hole for a stretched game,
//! so Game Night makes a copy for this screen at game start: scaled so the hole fits the whole-pixel game
//! exactly, the rest black, written to Game Night's cache folder. C comes with its own overlay file.

use std::path::{Path, PathBuf};

/// The looks, as RetroArch shader presets inside the player folder. None = no shader.
pub fn look_preset(player: &Path, look: &str) -> Option<PathBuf> {
    let s = player.join("shaders");
    match look {
        "scanlines" => Some(s.join("scanlines.slangp")),
        "lottes" => Some(s.join("slang").join("crt").join("crt-lottes.slangp")),
        "geom" => Some(s.join("slang").join("crt").join("crt-geom.slangp")),
        "royale" => Some(s.join("slang").join("crt").join("crt-royale.slangp")),
        "easymode" => Some(s.join("slang").join("crt").join("crt-easymode.slangp")),
        "lottesfast" => Some(s.join("slang").join("crt").join("crt-lottes-fast.slangp")),
        "hyllian" => Some(s.join("slang").join("crt").join("crt-hyllian.slangp")),
        "sharpsmooth" => Some(s.join("slang").join("pixel-art-scaling").join("sharp-bilinear.slangp")),
        "xbr" => Some(s.join("slang").join("edge-smoothing").join("xbr").join("xbr-lv2.slangp")),
        "scalefx" => Some(s.join("slang").join("edge-smoothing").join("scalefx").join("scalefx.slangp")),
        "hq4x" => Some(s.join("slang").join("edge-smoothing").join("hqx").join("hq4x.slangp")),
        _ => None,
    }
}

/// The plain look (sharp pixels, no effect). Switching to it is how a look is turned off while a game runs
/// (RetroArch's own shader on/off switch was unreliable; measured).
pub fn plain_preset(player: &Path) -> PathBuf {
    player.join("shaders").join("slang").join("nearest.slangp")
}

/// The picture a console's games send (width, height) with the emulator's default settings.
pub fn content_size(console: &str) -> (u32, u32) {
    match console {
        // FCEUmm crops the 8 overscan lines top and bottom by default (Strongly inferred; to measure in CI).
        "nes" => (256, 224),
        _ => (256, 224),
    }
}

/// Where RetroArch puts the game on a `screen` (width, height) with whole-pixel scaling, the same way
/// RetroArch 1.22.2 works it out (video_viewport_get_scaled_integer, default settings): the picture's width
/// for the shape, then the biggest whole multiple that fits, centred. `tv`: 4:3 like an old TV (aspect index 0);
/// otherwise square pixels (index 21). Measured at 1920x1080 for SNES: TV 1196x896 at (362, 92), square 1024x896
/// at (448, 92).
pub fn game_rect(screen: (u32, u32), content: (u32, u32), tv: bool) -> Option<(u32, u32, u32, u32)> {
    let (sw, sh) = screen;
    let (cw0, ch) = content;
    if sw == 0 || sh == 0 || ch == 0 || cw0 == 0 {
        return None;
    }
    let cw = if tv { ((ch as f32) * 4.0 / 3.0).round() as u32 } else { cw0 };
    if cw > sw || ch > sh {
        return None;
    }
    let s = (sw / cw).min(sh / ch).max(1);
    let (w, h) = (cw * s, ch * s);
    Some(((sw - w) / 2, (sh - h) / 2, w, h))
}

/// A bezel picture: RGBA pixels, plus the see-through hole it was drawn around (x, y, w, h).
pub struct Picture {
    pub w: u32,
    pub h: u32,
    pub rgba: Vec<u8>,
}

/// Reads a PNG as RGBA.
pub fn read_png(path: &Path) -> Result<Picture, String> {
    let file = std::fs::File::open(path).map_err(|_| "A bezel picture is missing.".to_string())?;
    let mut dec = png::Decoder::new(std::io::BufReader::new(file));
    dec.set_transformations(png::Transformations::EXPAND | png::Transformations::STRIP_16 | png::Transformations::ALPHA);
    let mut reader = dec.read_info().map_err(|_| "A bezel picture couldn't be read.".to_string())?;
    let mut buf = vec![0; reader.output_buffer_size().ok_or("A bezel picture is too big.")?];
    let info = reader.next_frame(&mut buf).map_err(|_| "A bezel picture couldn't be read.".to_string())?;
    buf.truncate(info.buffer_size());
    let rgba = match info.color_type {
        png::ColorType::Rgba => buf,
        png::ColorType::GrayscaleAlpha => buf.chunks(2).flat_map(|p| [p[0], p[0], p[0], p[1]]).collect(),
        _ => return Err("A bezel picture has an odd format.".into()),
    };
    Ok(Picture { w: info.width, h: info.height, rgba })
}

/// Writes RGBA pixels as a PNG.
pub fn write_png(path: &Path, p: &Picture) -> Result<(), String> {
    let file = std::fs::File::create(path).map_err(|_| "Couldn't save the bezel.".to_string())?;
    let mut enc = png::Encoder::new(std::io::BufWriter::new(file), p.w, p.h);
    enc.set_color(png::ColorType::Rgba);
    enc.set_depth(png::BitDepth::Eight);
    let mut w = enc.write_header().map_err(|_| "Couldn't save the bezel.".to_string())?;
    w.write_image_data(&p.rgba).map_err(|_| "Couldn't save the bezel.".to_string())
}

/// The see-through hole in a bezel picture: the box around every pixel that is (almost) fully see-through.
pub fn hole(p: &Picture) -> Option<(u32, u32, u32, u32)> {
    let (mut x0, mut y0, mut x1, mut y1) = (u32::MAX, u32::MAX, 0, 0);
    for y in 0..p.h {
        for x in 0..p.w {
            if p.rgba[((y * p.w + x) * 4 + 3) as usize] < 10 {
                x0 = x0.min(x);
                y0 = y0.min(y);
                x1 = x1.max(x);
                y1 = y1.max(y);
            }
        }
    }
    (x0 <= x1 && y0 <= y1).then(|| (x0, y0, x1 - x0 + 1, y1 - y0 + 1))
}

/// The bezel for this screen: `src` scaled evenly so its hole is as tall as the game, centred on the game; the
/// game's rectangle fully see-through; everything else solid (black where the picture doesn't reach, and
/// inside the hole beside a narrower game).
pub fn fit_bezel(src: &Picture, src_hole: (u32, u32, u32, u32), screen: (u32, u32), game: (u32, u32, u32, u32)) -> Picture {
    let (sw, sh) = screen;
    let (gx, gy, gw, gh) = game;
    let (hx, hy, hw, hh) = src_hole;
    let k = gh as f64 / hh.max(1) as f64;
    // where the source picture's top-left lands, so the hole's centre sits on the game's centre
    let ox = (gx as f64 + gw as f64 / 2.0) - (hx as f64 + hw as f64 / 2.0) * k;
    let oy = (gy as f64 + gh as f64 / 2.0) - (hy as f64 + hh as f64 / 2.0) * k;
    let mut out = vec![0u8; (sw * sh * 4) as usize];
    let at = |x: i64, y: i64, c: usize| -> f64 {
        let x = x.clamp(0, src.w as i64 - 1) as u32;
        let y = y.clamp(0, src.h as i64 - 1) as u32;
        src.rgba[((y * src.w + x) * 4) as usize + c] as f64
    };
    for y in 0..sh {
        for x in 0..sw {
            let i = ((y * sw + x) * 4) as usize;
            if x >= gx && x < gx + gw && y >= gy && y < gy + gh {
                continue; // the game: see-through
            }
            // bilinear sample of the source picture
            let fx = (x as f64 + 0.5 - ox) / k - 0.5;
            let fy = (y as f64 + 0.5 - oy) / k - 0.5;
            let mut px = [0.0f64; 4];
            if fx >= -0.5 && fy >= -0.5 && fx < src.w as f64 - 0.5 && fy < src.h as f64 - 0.5 {
                let (x0, y0) = (fx.floor() as i64, fy.floor() as i64);
                let (tx, ty) = (fx - x0 as f64, fy - y0 as f64);
                for (c, v) in px.iter_mut().enumerate() {
                    let a = at(x0, y0, c) * (1.0 - tx) + at(x0 + 1, y0, c) * tx;
                    let b = at(x0, y0 + 1, c) * (1.0 - tx) + at(x0 + 1, y0 + 1, c) * tx;
                    *v = a * (1.0 - ty) + b * ty;
                }
            }
            // on black: anything see-through outside the game shows black, never the desktop or a stretched game
            let a = px[3] / 255.0;
            for c in 0..3 {
                out[i + c] = (px[c] * a).round().clamp(0.0, 255.0) as u8;
            }
            out[i + 3] = 255;
        }
    }
    Picture { w: sw, h: sh, rgba: out }
}

/// The bezel source pictures in the player folder (fetched by tools/player/fetch_player.py, fixed fingerprints).
pub fn bezel_source(player: &Path, style: &str, console: &str) -> Option<PathBuf> {
    let c = if console == "nes" { "nes" } else { "snes" };
    let name = match style {
        "tv" => format!("tv-{c}.png"),
        "photo" => format!("photo-{c}.png"),
        _ => return None,
    };
    Some(player.join("overlays").join("bezels").join(name))
}

/// Bezel C: libretro's animated border overlay file (its buttons light up with the pad).
pub fn animated_overlay(player: &Path, console: &str) -> PathBuf {
    let d = player.join("overlays").join("animated-border");
    if console == "nes" {
        d.join("nes-border.cfg")
    } else {
        d.join("super_famicom_animated_border.cfg")
    }
}

/// Makes (or reuses) the bezel for this screen and returns the overlay file RetroArch should load.
/// `cache`: Game Night's cache folder for the player. None = no bezel (style "none", or no picture).
pub fn prepare_bezel(player: &Path, cache: &Path, style: &str, console: &str, screen: (u32, u32), tv: bool) -> Result<Option<PathBuf>, String> {
    if style == "pad" {
        let f = animated_overlay(player, console);
        return Ok(f.is_file().then_some(f));
    }
    let Some(src_path) = bezel_source(player, style, console) else { return Ok(None) };
    let Some(game) = game_rect(screen, content_size(console), tv) else { return Ok(None) };
    let dir = cache.join("bezels");
    std::fs::create_dir_all(&dir).map_err(|_| "Couldn't make the bezel folder.")?;
    let stem = format!("{style}-{console}-{}x{}-{}", screen.0, screen.1, if tv { "tv" } else { "square" });
    let png_path = dir.join(format!("{stem}.png"));
    let cfg_path = dir.join(format!("{stem}.cfg"));
    if !png_path.is_file() {
        let src = read_png(&src_path)?;
        let h = hole(&src).ok_or("A bezel picture has no hole for the game.")?;
        let out = fit_bezel(&src, h, screen, game);
        let tmp = dir.join(format!("{stem}.tmp"));
        write_png(&tmp, &out)?;
        std::fs::rename(&tmp, &png_path).map_err(|_| "Couldn't save the bezel.")?;
    }
    // A picture only: no buttons on it (nothing to click), full screen.
    let cfg = format!(
        "overlays = 1\noverlay0_overlay = \"{}\"\noverlay0_full_screen = true\noverlay0_normalized = true\noverlay0_descs = 0\n",
        png_path.file_name().and_then(|n| n.to_str()).unwrap_or_default()
    );
    std::fs::write(&cfg_path, cfg).map_err(|_| "Couldn't save the bezel.")?;
    Ok(Some(cfg_path))
}

/// RetroArch settings for the display choices. `overlay`: from `prepare_bezel`.
pub fn config_lines(overlay: Option<&Path>, tv: bool, stretch: bool) -> Vec<(String, String)> {
    let path = |p: &Path| p.to_string_lossy().replace('"', "");
    let mut v: Vec<(&str, String)> = vec![
        ("video_scale_integer", (!stretch).to_string()),
        // 0 = 4:3 (TV shape), 21 = square pixels, 24 = fill the screen
        ("aspect_ratio_index", if stretch { "24" } else if tv { "0" } else { "21" }.into()),
        ("video_scale_integer_axis", "0".into()),
        ("video_scale_integer_scaling", "0".into()),
        ("video_viewport_bias_x", "0.500000".into()),
        ("video_viewport_bias_y", "0.500000".into()),
        // The bezel is a picture only: it never hides because a pad is plugged in, and is drawn at full size.
        ("input_overlay_enable", overlay.is_some().to_string()),
        ("input_overlay", overlay.map(path).unwrap_or_default()),
        ("input_overlay_enable_autopreferred", "false".into()),
        ("input_overlay_hide_when_gamepad_connected", "false".into()),
        ("input_overlay_hide_in_menu", "false".into()),
        ("input_overlay_behind_menu", "true".into()),
        ("input_overlay_auto_scale", "false".into()),
        ("input_overlay_scale_landscape", "1.000000".into()),
        ("input_overlay_opacity", "1.000000".into()),
        ("input_overlay_pointer_enable", "false".into()),
        ("input_overlay_show_mouse_cursor", "false".into()),
        // Bezel C's buttons light up with the pad of player 1 on this PC.
        ("input_overlay_show_inputs", "2".into()),
        ("input_overlay_show_inputs_port", "0".into()),
    ];
    if stretch {
        v.retain(|(k, _)| !k.starts_with("input_overlay") || *k == "input_overlay_enable");
        v.iter_mut().filter(|(k, _)| *k == "input_overlay_enable").for_each(|(_, val)| *val = "false".into());
    }
    v.into_iter().map(|(k, v)| (k.to_string(), v)).collect()
}

/// RetroArch's own menu, used only to hold your presses back while Game Night's menu is open (it stops
/// your buttons reaching the game; measured): drawn fully see-through, with nothing on it to choose.
pub fn hidden_menu_theme() -> String {
    ["entry_normal", "entry_hover", "title", "bg_dark", "bg_light", "border_dark", "border_light", "shadow", "particle"]
        .iter()
        .map(|k| format!("rgui_{k}_color = \"0x00000000\"\n"))
        .collect()
}

pub fn hidden_menu_lines(theme: &Path, online: bool) -> Vec<(String, String)> {
    let path = theme.to_string_lossy().replace('"', "");
    let mut v: Vec<(String, String)> = [
        ("rgui_menu_color_theme", "0".to_string()),
        ("rgui_menu_theme_preset", path),
        ("menu_rgui_transparency", "true".into()),
        ("menu_rgui_shadows", "false".into()),
        ("rgui_particle_effect", "0".into()),
        ("menu_enable_widgets", "false".into()),
        ("kiosk_mode_enable", "true".into()),
        // Solo: the menu pauses the game. Couch Play: the game keeps going for everyone.
        ("menu_pause_libretro", (!online).to_string()),
        ("menu_show_load_core", "false".into()),
        ("menu_show_load_content", "false".into()),
        ("menu_show_quit_retroarch", "false".into()),
        ("menu_show_restart_retroarch", "false".into()),
        ("menu_show_information", "false".into()),
        ("menu_show_configurations", "false".into()),
        ("menu_show_help", "false".into()),
        ("menu_show_overlays", "false".into()),
        ("menu_show_rewind", "false".into()),
        ("menu_show_latency", "false".into()),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_string(), v))
    .collect();
    for k in [
        "resume_content", "restart_content", "close_content", "savestate_submenu", "save_load_state", "replay", "take_screenshot",
        "undo_save_load_state", "add_to_favorites", "add_to_playlist", "start_recording", "start_streaming", "set_core_association",
        "reset_core_association", "options", "core_options_flush", "controls", "cheats", "shaders", "save_core_overrides",
        "save_content_dir_overrides", "save_game_overrides", "information", "download_thumbnails",
    ] {
        v.push((format!("quick_menu_show_{k}"), "false".into()));
    }
    v
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn whole_pixel_rect_matches_what_retroarch_did_on_windows() {
        // CI run 41222656188, SNES at 1920x1080
        assert_eq!(game_rect((1920, 1080), (256, 224), true), Some((362, 92, 1196, 896)));
        assert_eq!(game_rect((1920, 1080), (256, 224), false), Some((448, 92, 1024, 896)));
        // 1440p: 6x, 4K: 9x
        assert_eq!(game_rect((2560, 1440), (256, 224), false).map(|r| r.3), Some(1344));
        assert_eq!(game_rect((3840, 2160), (256, 224), false).map(|r| r.3), Some(2016));
        assert_eq!(game_rect((100, 100), (256, 224), true), None);
    }

    #[test]
    fn bezel_hole_is_exactly_the_game() {
        // a 40x30 frame with a 20x16 hole
        let mut rgba = vec![200u8; 40 * 30 * 4];
        for y in 7..23 {
            for x in 10..30 {
                rgba[((y * 40 + x) * 4 + 3) as usize] = 0;
            }
        }
        let src = Picture { w: 40, h: 30, rgba };
        let h = hole(&src).unwrap();
        assert_eq!(h, (10, 7, 20, 16));
        let game = (30, 10, 40, 32);
        let out = fit_bezel(&src, h, (100, 52), game);
        let a = |x: u32, y: u32| out.rgba[((y * 100 + x) * 4 + 3) as usize];
        assert_eq!(a(30, 10), 0);
        assert_eq!(a(69, 41), 0);
        assert_eq!(a(29, 10), 255);
        assert_eq!(a(70, 41), 255);
        assert_eq!(a(0, 0), 255);
    }

    #[test]
    fn looks_and_menu_settings() {
        let p = Path::new("player");
        assert!(look_preset(p, "royale").unwrap().ends_with("crt-royale.slangp"));
        assert!(look_preset(p, "sharp").is_none());
        let lines = config_lines(None, true, false);
        assert!(lines.contains(&("aspect_ratio_index".into(), "0".into())));
        assert!(lines.contains(&("input_overlay_enable".into(), "false".into())));
        let solo = hidden_menu_lines(Path::new("t.cfg"), false);
        assert!(solo.contains(&("menu_pause_libretro".into(), "true".into())));
        let online = hidden_menu_lines(Path::new("t.cfg"), true);
        assert!(online.contains(&("menu_pause_libretro".into(), "false".into())));
        assert!(hidden_menu_theme().lines().all(|l| l.ends_with("\"0x00000000\"")));
    }
}
