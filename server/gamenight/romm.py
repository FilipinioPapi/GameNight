"""Reading Jayden's RomM library. Read-only: this never changes anything in RomM.

RomM stays private: only this server talks to it, with a read-only token (or a Viewer user).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from urllib.parse import quote
from dataclasses import dataclass

import aiohttp

# RomM platform slugs -> Game Night console ids. Folder names (fs slugs) are matched too,
# so Jayden's existing folders (NES, SNES, PS1, GameCube...) work without renaming.
PLATFORMS: dict[str, str] = {
    "nes": "nes", "famicom": "nes",
    "snes": "snes", "sfam": "snes",
    "genesis": "gen", "genesis-slash-megadrive": "gen", "megadrive": "gen", "mega-drive": "gen",
    "gb": "gb", "gbc": "gb",
    "gba": "gba",
    "arcade": "arc", "mame": "arc", "fbneo": "arc", "neogeoaes": "arc", "neogeomvs": "arc", "neogeo": "arc", "neo-geo": "arc", "cps1": "arc", "cps2": "arc", "cps3": "arc",
    "psx": "ps1", "ps1": "ps1", "ps": "ps1", "playstation": "ps1",
    "n64": "n64",
    "ngc": "gc", "gamecube": "gc", "gc": "gc",
    "wii": "wii",
    "ps2": "ps2",
}

CACHE_SECONDS = 300

log = logging.getLogger("gamenight")

# Game file types per console. Anything else in a console's folder (Windows' desktop.ini, Thumbs.db,
# readme files, pictures, save files...) is left out of Game Night's game lists. Only what Game Night
# shows changes: RomM and the files on the NAS are never touched.
ARCHIVES = {"zip", "7z"}
GAME_TYPES: dict[str, set[str]] = {
    "nes": {"nes", "fds", "unf", "unif"},
    "snes": {"sfc", "smc", "fig", "swc", "bs", "st"},
    "gen": {"md", "gen", "smd", "bin", "68k", "sgd"},
    "gb": {"gb", "gbc", "sgb", "dmg"},
    "gba": {"gba", "agb"},
    "arc": {"chd"},
    "ps1": {"cue", "bin", "chd", "pbp", "iso", "img", "m3u", "ccd", "mds", "ecm"},
    "n64": {"n64", "z64", "v64"},
    "gc": {"iso", "gcm", "gcz", "rvz", "ciso", "dol"},
    "wii": {"iso", "wbfs", "rvz", "wia", "gcz", "ciso", "wad"},
    "ps2": {"iso", "chd", "cso", "zso", "bin", "cue", "img"},
}
# Files that are never games, whatever they end in (Windows, Mac and Linux leave these about).
NEVER_GAMES = {"desktop.ini", "thumbs.db", "ehthumbs.db", "ehthumbs_vista.db", ".ds_store", "folder.jpg",
               "albumartsmall.jpg"}


def _type_of(name: str) -> str:
    """The file type: 'Contra (USA).nes' gives 'nes'. No real ending (a folder like 'Final Fantasy VII') gives ''."""
    stem, dot, ext = name.rpartition(".")
    ext = ext.lower()
    return ext if dot and stem and ext.isalnum() and len(ext) <= 5 and any(c.isalpha() for c in ext) else ""


def is_game(console: str, r: dict) -> bool:
    """Is this RomM entry a game, or a stray file sitting in a console's folder?"""
    name = (r.get("fs_name") or "").strip()
    if not name or name.lower() in NEVER_GAMES or name.startswith("."):
        return False
    ok = GAME_TYPES.get(console, set()) | ARCHIVES
    ext = (r.get("fs_extension") or "").lower().lstrip(".") if "fs_extension" in r else _type_of(name)
    if ext:
        return ext in ok
    # A game kept as a folder (several discs, cue + bin...): a game if any file inside is one.
    # When RomM doesn't list the files, keep it rather than hide a real game.
    files = [f.get("file_name") or "" for f in (r.get("files") or []) if isinstance(f, dict)]
    return not files or any(_type_of(f) in ok for f in files)


@dataclass(frozen=True)
class Game:
    id: int
    title: str
    console: str
    players: str
    size: int
    summary: str
    cover: str          # RomM's path to the large cover, or ""
    file_name: str

    def public(self) -> dict:
        """What the app sees. No server paths, no RomM internals."""
        return {
            "id": str(self.id), "title": self.title, "console": self.console, "players": self.players,
            "sizeBytes": self.size, "description": self.summary or None, "hasCover": bool(self.cover),
            # Changes when the cover changes in RomM (its address carries a timestamp), so the app
            # knows to fetch the new one instead of using the copy it saved.
            "coverVersion": hashlib.sha256(self.cover.encode()).hexdigest()[:12] if self.cover else None,
        }


def console_for(platform_slug: str, fs_slug: str) -> str | None:
    for s in (platform_slug, fs_slug):
        key = (s or "").strip().lower()
        if key in PLATFORMS:
            return PLATFORMS[key]
    return None


def players_from(raw: str) -> str:
    """RomM says things like "1", "1-2", "2" or "1-4". Keep it to that shape."""
    nums = [int(n) for n in re.findall(r"\d+", raw or "")][:2]
    if not nums:
        return "1"
    lo, hi = (1, nums[0]) if len(nums) == 1 else (min(nums), max(nums))
    return str(hi) if hi == 1 else f"{lo}-{hi}"


class RomM:
    def __init__(self, http: aiohttp.ClientSession, cfg):
        self.http, self.base = http, cfg.romm_url
        if cfg.romm_token:
            self.headers = {"Authorization": f"Bearer {cfg.romm_token}"}
            self.auth = None
        else:
            self.headers = {}
            self.auth = aiohttp.BasicAuth(cfg.romm_user, cfg.romm_password)
        self._games: dict[int, Game] = {}
        self._loaded = 0.0
        self._lock = asyncio.Lock()
        self._hidden: list[str] = []

    async def _get_json(self, path: str, params: dict | None = None):
        async with self.http.get(self.base + path, params=params, headers=self.headers, auth=self.auth,
                                 timeout=aiohttp.ClientTimeout(total=60)) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def games(self) -> dict[int, Game]:
        """Every game on a console Game Night knows, refreshed every few minutes."""
        if time.time() - self._loaded < CACHE_SECONDS and self._games:
            return self._games
        async with self._lock:
            if time.time() - self._loaded < CACHE_SECONDS and self._games:
                return self._games
            found: dict[int, Game] = {}
            hidden: list[str] = []
            offset, limit = 0, 500
            while True:
                page = await self._get_json("/api/roms", {
                    "limit": limit, "offset": offset, "order_by": "name", "order_dir": "asc",
                    "with_char_index": "false", "with_filter_values": "false",
                    "with_rom_id_index": "false", "with_provider_metadata": "false",
                })
                items = page.get("items", [])
                for r in items:
                    console = console_for(r.get("platform_slug", ""), r.get("platform_fs_slug", ""))
                    if not console or r.get("missing_from_fs"):
                        continue
                    if not is_game(console, r):
                        hidden.append(f"{console}/{(r.get('fs_name') or '?')[:80]}")
                        continue
                    found[int(r["id"])] = Game(
                        id=int(r["id"]),
                        title=(r.get("name") or r.get("fs_name_no_ext") or r.get("fs_name") or "Untitled")[:120],
                        console=console,
                        players=players_from((r.get("metadatum") or {}).get("player_count", "")),
                        size=int(r.get("fs_size_bytes") or 0),
                        summary=(r.get("summary") or "")[:1500],
                        cover=r.get("path_cover_large") or "",
                        file_name=r.get("fs_name") or "game",
                    )
                offset += len(items)
                if len(items) < limit:
                    break
            if hidden and sorted(hidden) != self._hidden:
                # Only when the list changes, so the log isn't repeated every few minutes.
                log.info("Not games, left out of the game lists (%d): %s", len(hidden), ", ".join(sorted(hidden)))
            self._hidden = sorted(hidden)
            self._games, self._loaded = found, time.time()
            return found

    async def open_cover(self, game: Game) -> aiohttp.ClientResponse:
        if not game.cover.startswith("/"):
            raise ValueError("no cover")
        return await self.http.get(self.base + game.cover, headers=self.headers, auth=self.auth,
                                   timeout=aiohttp.ClientTimeout(total=30))

    async def open_download(self, game: Game, range_header: str | None) -> aiohttp.ClientResponse:
        headers = dict(self.headers)
        if range_header:
            headers["Range"] = range_header
        name = quote(game.file_name, safe="")
        return await self.http.get(f"{self.base}/api/roms/{game.id}/content/{name}", params={"purpose": "download"},
                                   headers=headers, auth=self.auth,
                                   timeout=aiohttp.ClientTimeout(total=None, sock_read=120))
