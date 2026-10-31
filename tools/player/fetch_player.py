"""Builds Game Night's "player" folder: the parts of RetroArch that Game Night needs, nothing more.

Used by the Windows build (.github/workflows/app.yml) and on a Windows PC for testing:
    python tools/player/fetch_player.py app/src-tauri/player

It downloads RetroArch's official Windows build at a fixed version, checks the downloads against the
SHA-256 fingerprints below (so a changed or tampered file stops the build), and copies out only:
retroarch.exe and the DLLs it loads, the NES and SNES emulators, controller profiles and one
scanline shader. Needs 7-Zip on the PATH (the GitHub Windows machines have it).
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

HERE = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


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
        wanted = [f"RetroArch-Win64/{n}" for n in DLLS + OTHER] + [f"RetroArch-Win64/{SHADER}/*", "RetroArch-Win64/autoconfig/*"]
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
        shutil.copy2(HERE / "NOTICE.txt", out / "NOTICE.txt")
    print(f"player ready in {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "app/src-tauri/player"))
