"""Reading Jayden's RomM library. Read-only: this never changes anything in RomM.

RomM stays private: only this server talks to it, with a read-only token (or a Viewer user).
"""
from __future__ import annotations

import asyncio
import hashlib
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
