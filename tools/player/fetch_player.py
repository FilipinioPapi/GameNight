"""Builds Game Night's "player" folder: the parts of RetroArch that Game Night needs, nothing more.

Used by the Windows build (.github/workflows/app.yml) and on a Windows PC for testing:
    python tools/player/fetch_player.py app/src-tauri/player

It downloads RetroArch's official Windows build at a fixed version, checks the downloads against the
SHA-256 fingerprints below (so a changed or tampered file stops the build), and copies out only:
retroarch.exe and the DLLs it loads, the NES and SNES emulators, controller profiles, a scanline shader,
three CRT looks (Lottes, Geom, Royale) and the animated NES / Super Famicom bezels. Needs 7-Zip on the PATH (the GitHub Windows machines have it).
"""
import hashlib
import shutil
import subprocess
import sys
import tempfile
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
LOOKS = ["crt/crt-lottes.slangp", "crt/crt-geom.slangp", "crt/crt-royale.slangp"]
# Bezel C (approved 2026-10-31): libretro common-overlays' animated NES and Super Famicom borders (CC BY 4.0).
BORDERS = "overlays/borders/animated-border"
BORDER_FILES = ["nes-border.cfg", "img-nes/*", "super_famicom_animated_border.cfg", "img-sfc/*"]

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
        shutil.copytree(src / SHADER, out / "shaders" / "zfast_crt")
        shutil.copy2(HERE / "scanlines.slangp", out / "shaders" / "scanlines.slangp")
        for f in sorted(slang_files(src / SLANG, LOOKS)):
            (out / "shaders" / "slang" / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / SLANG / f, out / "shaders" / "slang" / f)
        shutil.copytree(src / BORDERS, out / "overlays" / "animated-border")
        shutil.copy2(HERE / "NOTICE.txt", out / "NOTICE.txt")
    print(f"player ready in {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "app/src-tauri/player"))
