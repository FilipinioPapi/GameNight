#!/usr/bin/env python3
"""CI only (never on the NAS): runs Game Night's REAL server code on this machine for the Couch Play app test,
with a pretend RomM (one test game) and two pretend signed-in friends instead of Discord.

    python couch_server_standin.py <server folder> <work folder> <rom size> <port>

Writes <work folder>/standin.json with the address and both sign-in passes once it's listening.
Only listens on 127.0.0.1.
"""
import ipaddress
import json
import sys
from pathlib import Path

SERVER, WORK, ROM_SIZE, PORT = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), int(sys.argv[3]), int(sys.argv[4])
sys.path.insert(0, str(SERVER))

from aiohttp import web  # noqa: E402

from gamenight import app as appmod  # noqa: E402
from gamenight.config import Config  # noqa: E402
from gamenight.db import Database  # noqa: E402
from gamenight.romm import Game  # noqa: E402

GAME = Game(1, "Netplay test", "nes", "1-2", ROM_SIZE, "", "", "test.nes")


class OneGame:
    def __init__(self, http, cfg):
        pass

    async def games(self):
        return {1: GAME}


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    url = f"http://127.0.0.1:{PORT}"
    cfg = Config(public_url=url, discord_client_id="1", discord_client_secret="ci-only", guild_id="10", role_id="",
                 romm_url="http://127.0.0.1:9", romm_token="ci-only", romm_user="", romm_password="",
                 data_dir=str(WORK), port=PORT, session_days=1, trusted_proxies=(ipaddress.ip_network("127.0.0.1/32"),),
                 log_level="INFO", **({"base_path": ""} if "base_path" in Config.__dataclass_fields__ else {}))
    db = Database(str(WORK / "standin.db"), 1)
    passes = {}
    for uid, name in (("100", "Host"), ("200", "Friend"), ("300", "Watcher")):
        db.upsert_user(uid, name, "")
        passes[name.lower()] = db.create_session(uid, "ci")
    (WORK / "standin.json").write_text(json.dumps({"url": url, "passes": passes}))
    web.run_app(appmod.build(cfg, db=db, romm_factory=OneGame), host="127.0.0.1", port=PORT, print=print)


if __name__ == "__main__":
    main()
