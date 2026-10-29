"""Start the Game Night server, or run a small admin command.

    python -m gamenight                     run the server
    python -m gamenight sessions            list who is signed in, and on which PC
    python -m gamenight sign-out <who>      end every sign-in for a Discord name or ID
"""
from __future__ import annotations

import logging
import os
import sys
import time

from aiohttp import web

from . import config
from .app import build
from .db import Database


def _db() -> Database:
    data = os.getenv("DATA_DIR", "/data")
    return Database(f"{data}/gamenight.db", int(os.getenv("SESSION_DAYS", "30") or 30))


def main(argv: list[str]) -> int:
    if argv[:1] == ["sessions"]:
        for name, uid, device, last in _db().list_sessions():
            print(f"{name:<24} {uid:<20} {device or '-':<24} last used {time.strftime('%Y-%m-%d %H:%M', time.localtime(last))}")
        return 0
    if argv[:1] == ["sign-out"] and len(argv) == 2:
        print(f"Ended {_db().sign_out_everywhere(argv[1])} sign-in(s).")
        return 0
    if argv:
        print(__doc__)
        return 2
    cfg = config.load()
    logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)  # no web addresses (with codes) in the log
    logging.getLogger("gamenight").info("Game Night server starting on port %s (%s)", cfg.port, cfg.public_url)
    web.run_app(build(cfg), host="0.0.0.0", port=cfg.port, print=None, access_log=None)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
