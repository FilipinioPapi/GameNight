import ipaddress
from urllib.parse import parse_qs, urlparse

import pytest

from gamenight import app as appmod
from gamenight import discord_auth as da
from gamenight.config import Config
from gamenight.db import Database
from gamenight.romm import Game, console_for, players_from

VERIFIER = "v" * 50


def cfg(**kw):
    base = dict(public_url="http://nas:8094", discord_client_id="1", discord_client_secret="s", guild_id="10",
                role_id="20", romm_url="http://romm:8080", romm_token="rmm_x", romm_user="", romm_password="",
                data_dir="/tmp", port=8094, session_days=30,
                trusted_proxies=(ipaddress.ip_network("127.0.0.1/32"),), log_level="INFO")
    base.update(kw)
    return Config(**base)


class FakeRomM:
    def __init__(self, http, cfg):
        self.list = {7: Game(7, "Super Mario Bros.", "nes", "1-2", 40976, "Plumbers.", "", "Super Mario Bros. (World).nes")}

    async def games(self):
        return self.list


@pytest.fixture
async def client(aiohttp_client):
    db = Database(":memory:")
    a = appmod.build(cfg(), db=db, romm_factory=FakeRomM)
    c = await aiohttp_client(a)
    c.db = db
    return c


async def sign_in(client, monkeypatch, verifier=VERIFIER):
    async def fake_check(http, cfg, code):
        assert code == "discord-code"
        return "123", "Jayden", "https://cdn.discordapp.com/embed/avatars/0.png"
    monkeypatch.setattr(da, "check_member", fake_check)
    r = await client.get("/app/login", params={"challenge": da.challenge_of(verifier)}, allow_redirects=False)
    assert r.status == 302
    loc = urlparse(r.headers["Location"])
    assert loc.netloc == "discord.com"
    q = parse_qs(loc.query)
    assert q["scope"] == ["identify guilds.members.read"]
    r = await client.get("/auth/callback", params={"state": q["state"][0], "code": "discord-code"})
    assert r.status == 200
    body = await r.text()
    code = body.split("gamenight://signed-in?code=")[1].split('"')[0]
    return code


async def test_full_sign_in_and_games(client, monkeypatch):
    code = await sign_in(client, monkeypatch)
    r = await client.post("/api/session", json={"code": code, "verifier": VERIFIER, "device": "Living room PC"})
    assert r.status == 200
    data = await r.json()
    token = data["token"]
    assert token.startswith("gn_") and data["user"]["name"] == "Jayden"
    h = {"Authorization": f"Bearer {token}"}
    assert (await (await client.get("/api/me", headers=h)).json())["id"] == "123"
    games = (await (await client.get("/api/games", headers=h)).json())["games"]
    assert games == [{"id": "7", "title": "Super Mario Bros.", "console": "nes", "players": "1-2",
                      "sizeBytes": 40976, "description": "Plumbers.", "hasCover": False}]
    # the code only works once
    r = await client.post("/api/session", json={"code": code, "verifier": VERIFIER})
    assert r.status == 401
    # signing out ends the pass
    assert (await client.delete("/api/session", headers=h)).status == 200
    assert (await client.get("/api/me", headers=h)).status == 401


async def test_code_needs_the_apps_secret(client, monkeypatch):
    code = await sign_in(client, monkeypatch)
    r = await client.post("/api/session", json={"code": code, "verifier": "w" * 50})
    assert r.status == 401
    # and a wrong guess burns the code
    r = await client.post("/api/session", json={"code": code, "verifier": VERIFIER})
    assert r.status == 401


async def test_api_needs_a_pass(client):
    for path in ("/api/me", "/api/games", "/api/games/7/download", "/api/games/7/cover"):
        assert (await client.get(path)).status == 401
        assert (await client.get(path, headers={"Authorization": "Bearer gn_madeup"})).status == 401


async def test_not_in_role(client, monkeypatch):
    async def nope(http, cfg, code):
        raise da.NotAllowed()
    monkeypatch.setattr(da, "check_member", nope)
    r = await client.get("/app/login", params={"challenge": da.challenge_of(VERIFIER)}, allow_redirects=False)
    state = parse_qs(urlparse(r.headers["Location"]).query)["state"][0]
    r = await client.get("/auth/callback", params={"state": state, "code": "x"})
    assert r.status == 403
    assert "gamenight://" not in await r.text()


async def test_bad_or_reused_state(client):
    r = await client.get("/auth/callback", params={"state": "madeup", "code": "x"})
    assert r.status == 400
    r = await client.get("/app/login", params={"challenge": "short"})
    assert r.status == 400


async def test_security_headers(client):
    r = await client.get("/healthz")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["Server"] == "GameNight"


def test_players_and_consoles():
    assert players_from("1-2") == "1-2"
    assert players_from("2") == "1-2"
    assert players_from("1") == "1"
    assert players_from("") == "1"
    assert players_from("4-1") == "1-4"
    assert console_for("snes", "") == "snes"
    assert console_for("", "psx") == "ps1"
    assert console_for("dos", "dos") is None


def test_session_expiry(monkeypatch):
    import time as t
    db = Database(":memory:", session_days=1)
    db.upsert_user("1", "A", "")
    tok = db.create_session("1")
    assert db.check_session(tok).name == "A"
    real = t.time
    monkeypatch.setattr(t, "time", lambda: real() + 2 * 86400)
    assert db.check_session(tok) is None
    # only a fingerprint is stored
    assert tok not in str(db.conn.execute("SELECT * FROM sessions").fetchall())
