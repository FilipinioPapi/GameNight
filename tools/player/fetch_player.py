"""Builds Game Night's "player" folder: the parts of RetroArch that Game Night needs, nothing more.

Used by the Windows build (.github/workflows/app.yml) and on a Windows PC for testing:
    python tools/player/fetch_player.py app/src-tauri/player

It downloads RetroArch's official Windows build at a fixed version, checks the downloads against the
SHA-256 fingerprints below (so a changed or tampered file stops the build), and copies out only:
retroarch.exe and the DLLs it loads, the NES and SNES emulators, controller profiles, a scanline shader,
three CRT looks (Lottes, Geom, Royale), the animated NES / Super Famicom bezels, and the NyNy77 and Nosh01
bezel pictures from libretro/overlay-borders. Needs 7-Zip on the PATH (the GitHub Windows machines have it).
"""
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "1.22.2"
BASE = f"https://buildbot.libretro.com/stable/{VERSION}/windows/x86_64/"
DOWNLOADS = {
    "RetroArch.7z": "b2139b1d0f9d4526dc6b5ce23cbb3efdc766096fa6f2c3df016818b486ac6372",
    "RetroArch_cores.7z": "86b871e11b9b4772ac644b40a38f2c8e9449da1f355eae7da08aa061148547b0",
}
CORES = ["fceumm_libretro.dll", "snes9x_libretro.dll"]
# Everything retroarch.exe and the two cores load (worked out from their import tables).
DLLS = [
    "Qt5Core.dll", "Qt5Gui.dll", "Qt5Network.dll", "Qt5Widgets.dll", "SDL2.dll", "avcodec-58.dll",
    "avdevice-58.dll", "avfilter-7.dll", "avformat-58.dll", "avresample-4.dll", "avutil-56.dll", "libass-9.dll",
    "libbluray-1.dll", "libbs2b-0.dll", "libbz2.dll", "libcaca-0.dll", "libcrypto-1_1-x64.dll", "libexpat-1.dll",
    "libfontconfig-1.dll", "libfreetype-6.dll", "libfribidi-0.dll", "libgcc_s_seh-1.dll", "libglib-2.0-0.dll",
    "libglut.dll", "libgmp-10.dll", "libgnutls-30.dll", "libgomp-1.dll", "libharfbuzz-0.dll", "libhogweed-6.dll",
    "libiconv-2.dll", "libidn2-0.dll", "libintl-8.dll", "liblzma-5.dll", "libmp3lame-0.dll", "libncurses5.dll",
    "libnettle-8.dll", "libogg-0.dll", "libopencore-amrnb-0.dll", "libopencore-amrwb-0.dll", "libopus-0.dll",
    "libpcre-1.dll", "libpcre2-16-0.dll", "libpng16-16.dll", "libsamplerate-0.dll", "libspeex-1.dll",
    "libssl-1_1-x64.dll", "libssp-0.dll", "libstdc++-6.dll", "libtasn1-6.dll", "libtheoradec-1.dll",
    "libunistring-2.dll", "libvidstab.dll", "libvo-amrwbenc-0.dll", "libvorbis-0.dll", "libvorbisenc-2.dll",
    "libwinpthread-1.dll", "libx264-155.dll", "libxml2-2.dll", "libzstd.dll", "postproc-55.dll", "swresample-3.dll",
    "swscale-5.dll", "xvidcore.dll", "zlib1.dll",
]
OTHER = ["retroarch.exe", "qt.conf", "platforms/qwindows.dll"]
SHADER = "shaders/shaders_slang/crt/shaders/zfast_crt"
# The in-game menu's "look" choices (approved 2026-10-31): CRT Lottes, CRT Geom and CRT Royale, from the same
# RetroArch download. Only the files each preset really uses are copied (worked out by following the presets'
# passes, pictures and #include lines), into player/shaders/slang/ with the same folder layout.
SLANG = "shaders/shaders_slang"
# "nearest" is the plain look (sharp pixels, no effect): switching to it is how a look is turned off live.
# Lighter CRT looks and smoothing looks (Jayden asked 2026-10-31): easymode, lottes-fast, hyllian; sharp bilinear,
# xBR, ScaleFX, HQ4x. "Old TV scanlines" is zfast CRT (above).
LOOKS = ["nearest.slangp", "crt/crt-lottes.slangp", "crt/crt-geom.slangp", "crt/crt-royale.slangp",
         "crt/crt-easymode.slangp", "crt/crt-lottes-fast.slangp", "crt/crt-hyllian.slangp",
         "pixel-art-scaling/sharp-bilinear.slangp", "edge-smoothing/xbr/xbr-lv2.slangp",
         "edge-smoothing/scalefx/scalefx.slangp", "edge-smoothing/hqx/hq4x.slangp"]
# Bezel C (approved 2026-10-31): libretro common-overlays' animated NES and Super Famicom borders (CC BY 4.0).
BORDERS = "overlays/borders/animated-border"
BORDER_FILES = ["nes-border.cfg", "img-nes/*", "super_famicom_animated_border.cfg", "img-sfc/*"]
# Bezels B (default) and A (approved 2026-10-31): libretro/overlay-borders (MIT) at a fixed commit, each picture
# checked against its fingerprint. Game Night fits them to the whole-pixel game at game start (display.rs).
BEZEL_BASE = "https://raw.githubusercontent.com/libretro/overlay-borders/9aceca2dd514c589a57d40086557b804851aafcf/"
BEZELS = {
    "tv-nes.png": ("16x9 Collections/NyNy77 1080 Bezel/NintendoEntertainmentSystem-nyny77.png",
                   "cdc92e63595f96f07cdfc47a30764e8008859182b612d5e057b744dd8efb1c63"),
    "tv-snes.png": ("16x9 Collections/NyNy77 1080 Bezel/NintendoSuperNintendo-nyny77.png",
                    "5442ba0a64380781356b126146c08627801c0f52429319dcd9d846331bf7f4f4"),
    "photo-nes.png": ("16x9 Collections/Nosh01 1440 Plain/Nintendo-Entertainment-System-Bezel-16x9-2560x1440.png",
                      "3a147ba0211f084771cffb01034264f19512c914c63e7c75aa6c741a64d2edd3"),
    "photo-snes.png": ("16x9 Collections/Nosh01 1440 Plain/Super-Nintendo-Entertainment-System-Bezel-16x9-2560x1440.png",
                       "6e05ebda89d1d34c3b199ca9a2ba05cdb8f9ae86cb1b6a1ea927052b2042ab4e"),
    "LICENSE-overlay-borders.txt": ("LICENSE", "afb11426e09da40a1ae4f8fa17ddcc6b6a52d14df04c29bc5bcd06eb8730624d"),
}

HERE = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def slang_files(root: Path, presets: list[str]) -> set[str]:
    """Every file the presets need, as paths relative to the slang shader folder."""
    import posixpath
    import re
    need, todo = set(), []
    for preset in presets:
        need.add(preset)
        base = posixpath.dirname(preset)
        for line in (root / preset).read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r'\s*([A-Za-z0-9_]+)\s*=\s*"?([^"#]+?)"?\s*(#.*)?$', line)
            if m and re.search(r"\.(slang|png|jpg|jpeg)$", m.group(2).strip(), re.I):
                todo.append(posixpath.normpath(posixpath.join(base, m.group(2).strip())))
    while todo:
        f = todo.pop()
        if f in need:
            continue
        if not (root / f).is_file():
            sys.exit(f"a shader file is missing from RetroArch's download: {f}. Stopping.")
        need.add(f)
        if f.endswith((".slang", ".h", ".inc")):
            for inc in re.findall(r'#include\s+"([^"]+)"', (root / f).read_text(encoding="utf-8", errors="replace")):
                todo.append(posixpath.normpath(posixpath.join(posixpath.dirname(f), inc)))
    return need


# A controller profile line that binds one of the game's own buttons or sticks: kept. Every other button line
# (RetroArch shortcuts) goes, see strip_autoconfig_shortcuts.
GAME_BIND = re.compile(r"^input_(a|b|x|y|l|r|l2|r2|l3|r3|start|select|up|down|left|right|"
                       r"[lr]_[xy]_(plus|minus))_(btn|axis|mbtn)(_label)?$")
SHORTCUT = re.compile(r"^input_\w+_(btn|axis|mbtn)(_label)?$|^input_menu_toggle(_label)?$")


def strip_autoconfig_shortcuts(folder: Path) -> int:
    """RetroArch's controller profiles also bind shortcuts, mostly "Xbox / PS button = RetroArch's menu"
    (input_menu_toggle_btn, 136 profiles in 1.22.2). Game Night's in-game menu opens RetroArch's hidden menu
    itself (MENU_TOGGLE), so RetroArch reacting to the same button flipped that menu twice: the game took
    presses meant for Game Night's menu and then locked up after Resume (Jayden, 2026-11-01). A setting can't
    turn a profile's shortcut off ("nul" falls back to the profile), so the shortcut lines are left out of
    Game Night's copy. The game's own buttons and the profile's name, maker and model lines stay."""
    removed = 0
    for cfg in folder.rglob("*.cfg"):
        # Bytes, so every other line stays exactly as RetroArch shipped it (line endings, odd characters).
        lines = cfg.read_bytes().splitlines(keepends=True)
        keep = []
        for line in lines:
            key = line.split(b"=", 1)[0].strip().decode("ascii", errors="replace")
            if b"=" in line and SHORTCUT.match(key) and not GAME_BIND.match(key):
                removed += 1
                continue
            keep.append(line)
        if len(keep) != len(lines):
            cfg.write_bytes(b"".join(keep))
    print(f"controller profiles: {removed} RetroArch shortcut lines left out (the Xbox / PS button is Game Night's)")
    return removed


def main(out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for name, want in DOWNLOADS.items():
            dest = tmp / name
            print(f"downloading {name}")
            with urllib.request.urlopen(BASE + name, timeout=120) as r, dest.open("wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            got = sha256(dest)
            if got != want:
                sys.exit(f"{name} doesn't match its fingerprint ({got}). Stopping.")
        x = tmp / "x"
        wanted = [f"RetroArch-Win64/{n}" for n in DLLS + OTHER] + [f"RetroArch-Win64/{SHADER}/*", "RetroArch-Win64/autoconfig/*",
                                                                 f"RetroArch-Win64/{SLANG}/*", *[f"RetroArch-Win64/{BORDERS}/{f}" for f in BORDER_FILES]]
        subprocess.run(["7z", "x", "-y", f"-o{x}", str(tmp / "RetroArch.7z"), *wanted], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["7z", "x", "-y", f"-o{x}", str(tmp / "RetroArch_cores.7z"), *[f"RetroArch-Win64/cores/{c}" for c in CORES]],
                       check=True, stdout=subprocess.DEVNULL)
        src = x / "RetroArch-Win64"
        if out.exists():
            shutil.rmtree(out)
        (out / "cores").mkdir(parents=True)
        (out / "platforms").mkdir()
        for n in DLLS + OTHER:
            shutil.copy2(src / n, out / n)
        for c in CORES:
            shutil.copy2(src / "cores" / c, out / "cores" / c)
        shutil.copytree(src / "autoconfig", out / "autoconfig")
        strip_autoconfig_shortcuts(out / "autoconfig")
        shutil.copytree(src / SHADER, out / "shaders" / "zfast_crt")
        shutil.copy2(HERE / "scanlines.slangp", out / "shaders" / "scanlines.slangp")
        for f in sorted(slang_files(src / SLANG, LOOKS)):
            (out / "shaders" / "slang" / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / SLANG / f, out / "shaders" / "slang" / f)
        shutil.copytree(src / BORDERS, out / "overlays" / "animated-border")
        (out / "overlays" / "bezels").mkdir(parents=True)
        for name, (path, want) in BEZELS.items():
            dest = out / "overlays" / "bezels" / name
            with urllib.request.urlopen(BEZEL_BASE + urllib.parse.quote(path), timeout=120) as r:
                dest.write_bytes(r.read())
            got = sha256(dest)
            if got != want:
                sys.exit(f"bezel {name} doesn't match its fingerprint ({got}). Stopping.")
        shutil.copy2(HERE / "NOTICE.txt", out / "NOTICE.txt")
    print(f"player ready in {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "app/src-tauri/player"))
