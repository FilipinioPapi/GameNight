"""Only games reach Game Night's lists: stray files in Jayden's console folders (Windows' desktop.ini in
every folder, Thumbs.db, readmes, pictures) are left out. RomM itself is only read, never changed."""
import logging

from aiohttp import web

from gamenight import app as appmod
from gamenight.db import Database
from gamenight.romm import is_game

from test_server import VERIFIER, cfg, sign_in

# Shaped like RomM's /api/roms answer (only the fields Game Night reads).
ROMM_ITEMS = [
    # Real games
    {"id": 1, "name": "Super Mario Bros.", "fs_name": "Super Mario Bros. (World).nes", "fs_extension": "nes", "platform_slug": "nes"},
    {"id": 2, "name": "Super Metroid", "fs_name": "Super Metroid (USA).sfc", "fs_extension": "sfc", "platform_slug": "snes"},
    {"id": 3, "name": "Contra", "fs_name": "Contra (USA).zip", "fs_extension": "zip", "platform_slug": "nes"},
    {"id": 4, "name": "Final Fantasy VII", "fs_name": "Final Fantasy VII (USA)", "fs_extension": "", "platform_slug": "psx",
     "files": [{"file_name": "FF7 (Disc 1).cue"}, {"file_name": "FF7 (Disc 1).bin"}]},
    {"id": 5, "name": "Sonic", "fs_name": "Sonic the Hedgehog (USA, Europe).md", "fs_extension": "md", "platform_slug": "genesis"},
    # Not games: what Windows and others leave in the folders
    {"id": 101, "name": "desktop", "fs_name": "desktop.ini", "fs_extension": "ini", "platform_slug": "nes"},
    {"id": 102, "name": "desktop", "fs_name": "desktop.ini", "fs_extension": "ini", "platform_slug": "snes"},
    {"id": 103, "name": "desktop", "fs_name": "desktop.ini", "fs_extension": "ini", "platform_slug": "psx"},
    {"id": 104, "name": "Thumbs", "fs_name": "Thumbs.db", "fs_extension": "db", "platform_slug": "genesis"},
    {"id": 105, "name": "readme", "fs_name": "readme.txt", "fs_extension": "txt", "platform_slug": "snes"},
    {"id": 106, "name": "cover", "fs_name": "cover.jpg", "fs_extension": "jpg", "platform_slug": "nes"},
    {"id": 107, "name": "Pictures", "fs_name": "Pictures", "fs_extension": "", "platform_slug": "psx",
     "files": [{"file_name": "a.png"}, {"file_name": "desktop.ini"}]},
    {"id": 108, "name": "Mario save", "fs_name": "Super Mario Bros. (World).srm", "fs_extension": "srm", "platform_slug": "nes"},
    {"id": 109, "name": "_", "fs_name": "._Super Metroid (USA).sfc", "fs_extension": "sfc", "platform_slug": "snes"},
]


async def test_game_lists_leave_out_files_that_are_not_games(aiohttp_client, aiohttp_server, monkeypatch, caplog):
    asked = []

    async def roms(request):
        asked.append(request.method)
        return web.json_response({"items": ROMM_ITEMS})

    romm_app = web.Application()
    romm_app.router.add_route("*", "/api/roms", roms)
    romm = await aiohttp_server(romm_app)

    db = Database(":memory:")
    c = await aiohttp_client(appmod.build(cfg(romm_url=str(romm.make_url("")).rstrip("/")), db=db))
    code = await sign_in(c, monkeypatch)
    token = (await (await c.post("/api/session", json={"code": code, "verifier": VERIFIER})).json())["token"]
    auth = {"Authorization": f"Bearer {token}"}

    with caplog.at_level(logging.INFO, logger="gamenight"):
        r = await c.get("/api/games", headers=auth)
    assert r.status == 200
    shown = sorted(g["title"] for g in (await r.json())["games"])
    assert shown == ["Contra", "Final Fantasy VII", "Sonic", "Super Mario Bros.", "Super Metroid"]

    # A hidden file can't be downloaded either.
    assert (await c.get("/api/games/101/download", headers=auth)).status == 404

    # The server's log names what it left out, so it can be checked on the NAS.
    note = [m for m in caplog.messages if m.startswith("Not games")]
    assert len(note) == 1 and "nes/desktop.ini" in note[0] and "(9)" in note[0]

    # RomM was only read.
    assert asked and set(asked) == {"GET"}


def test_folder_games_without_a_file_list_are_kept():
    assert is_game("ps1", {"fs_name": "Crash Bandicoot (USA)", "fs_extension": ""})
    assert is_game("ps1", {"fs_name": "Crash Bandicoot v1.1"})  # older RomM, no file type given
    assert not is_game("ps1", {"fs_name": "desktop.ini"})
    assert not is_game("nes", {"fs_name": "Thumbs.db"})
    assert not is_game("nes", {"fs_name": ""})
    assert is_game("snes", {"fs_name": "Chrono Trigger (USA).SFC", "fs_extension": "SFC"})
    assert not is_game("snes", {"fs_name": "Sonic.md", "fs_extension": "md"})  # wrong console's game type
