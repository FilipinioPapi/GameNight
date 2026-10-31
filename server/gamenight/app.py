"""The Game Night server's web addresses.

Browser pages:  /app/login, /auth/callback (Discord sign-in only)
App API:        /api/... (needs the app's sign-in pass, except trading a sign-in code for one)
Couch Play:     /api/lobbies/... (see docs/COUCH_PLAY_SPEC.md)

With BASE_PATH set (e.g. /gamenight), every address also answers under it (/gamenight/api/me),
so Nginx Proxy Manager can forward /gamenight/ with or without stripping it.
"""
from __future__ import annotations

import html
import ipaddress
import logging
import time

import aiohttp
from aiohttp import web

from . import discord_auth as da
from . import lobbies as lb
from .db import Database, User
from .romm import RomM

log = logging.getLogger("gamenight")

CFG = web.AppKey("cfg", object)
DB = web.AppKey("db", Database)
ROMM = web.AppKey("romm", RomM)
BOOK = web.AppKey("book", da.LoginBook)
HTTP = web.AppKey("http", aiohttp.ClientSession)
LIMITS = web.AppKey("limits", dict)
LOBBIES = web.AppKey("lobbies", lb.LobbyBook)
USER = web.RequestKey("user", User)
TOKEN = web.RequestKey("token", str)


class RateLimit:
    """At most `count` tries per `seconds` for each key (in memory)."""

    def __init__(self, count: int, seconds: float):
        self.count, self.seconds = count, seconds
        self.hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        recent = [t for t in self.hits.get(key, []) if now - t < self.seconds]
        if len(recent) >= self.count:
            self.hits[key] = recent
            return False
        recent.append(now)
        self.hits[key] = recent
        if len(self.hits) > 5000:
            self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < self.seconds}
        return True


def client_ip(request: web.Request) -> str:
    """The visitor's real address. Only a trusted proxy (Nginx Proxy Manager) may tell us it."""
    remote = request.remote or ""
    try:
        ip = ipaddress.ip_address(remote)
    except ValueError:
        return remote
    if any(ip in net for net in request.app[CFG].trusted_proxies):
        real = request.headers.get("X-Real-IP", "").strip()
        if real:
            return real
    return remote


def page(title: str, body: str, status: int = 200, extra_head: str = "") -> web.Response:
    """A small page in Game Night colours, for the browser during sign-in."""
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · Game Night</title>{extra_head}
<style>
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:radial-gradient(ellipse at 50% 30%,#2a1718 0%,#120c0c 60%);color:#f6e9e9;font-family:Inter,system-ui,sans-serif}}
.card{{width:min(460px,90vw);border-radius:16px;background:#1e1415;border:1px solid #3a2526;padding:28px;box-shadow:0 20px 50px rgba(0,0,0,.5)}}
h1{{margin:0 0 12px;font-size:22px}}p{{color:#e3d2d3;line-height:1.6;font-size:15px;margin:0 0 12px}}
a.btn{{display:inline-block;margin-top:8px;padding:12px 20px;border-radius:10px;background:#ce1a22;color:#fff;font-weight:700;text-decoration:none;border:2px solid #000;box-shadow:0 3px 0 #000}}
.muted{{color:#bfa7a8;font-size:13px}}
</style></head><body><div class="card"><h1>{html.escape(title)}</h1>{body}</div></body></html>"""
    return web.Response(text=doc, status=status, content_type="text/html")


@web.middleware
async def security_headers(request: web.Request, handler):
    try:
        resp = await handler(request)
    except web.HTTPException as e:
        resp = e
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; frame-ancestors 'none'")
    resp.headers.setdefault("Cache-Control", "no-store")
    if request.app[CFG].secure:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    if isinstance(resp, web.HTTPException):
        raise resp
    return resp


def local_path(request: web.Request) -> str:
    """The address without BASE_PATH in front, so /gamenight/api/me and /api/me are treated the same."""
    path, base = request.path, getattr(request.app[CFG], "base_path", "")
    if base and (path == base or path.startswith(base + "/")):
        return path[len(base):] or "/"
    return path


@web.middleware
async def require_pass(request: web.Request, handler):
    """Every /api address needs the app's sign-in pass, except trading a code for one."""
    path = local_path(request)
    if path.startswith("/api/") and not (path == "/api/session" and request.method == "POST"):
        auth = request.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        user = request.app[DB].check_session(token) if token else None
        if not user:
            if not request.app[LIMITS]["bad_pass"].allow(client_ip(request)):
                raise web.HTTPTooManyRequests(text="Too many tries. Wait a minute.")
            raise web.HTTPUnauthorized(text="Please sign in again.")
        request[USER] = user
        request[TOKEN] = token
    return await handler(request)


# ---------- browser sign-in ----------

async def app_login(request: web.Request) -> web.StreamResponse:
    challenge = request.query.get("challenge", "")
    if not da.valid_challenge(challenge):
        return page("That link didn't work", "<p>Start signing in from the Game Night app.</p>", 400)
    if not request.app[LIMITS]["login"].allow(client_ip(request)):
        return page("Slow down a little", "<p>Too many sign-in tries. Wait a minute, then try again from the app.</p>", 429)
    try:
        state = request.app[BOOK].start(challenge)
    except da.DiscordError as e:
        return page("Try again soon", f"<p>{html.escape(str(e))}</p>", 503)
    cfg = request.app[CFG]
    raise web.HTTPFound(da.authorize_url(cfg.discord_client_id, cfg.redirect_uri, state))


async def auth_callback(request: web.Request) -> web.StreamResponse:
    pending = request.app[BOOK].finish(request.query.get("state", ""))
    if request.query.get("error"):
        return page("Sign-in cancelled", "<p>No problem. Go back to Game Night and press <b>Log in with Discord</b> to try again.</p>")
    if not pending or not request.query.get("code"):
        return page("That sign-in expired", "<p>Go back to Game Night and press <b>Log in with Discord</b> again.</p>", 400)
    try:
        uid, name, avatar = await da.check_member(request.app[HTTP], request.app[CFG], request.query["code"])
    except da.NotAllowed:
        return page("Not on the list yet",
                    "<p>Game Night is for friends on Jayden's Discord server. "
                    "Ask Jayden for an invite (or the Game Night role, if he uses one), then try again.</p>", 403)
    except (da.DiscordError, aiohttp.ClientError) as e:
        log.warning("Discord sign-in failed: %s", e)
        return page("Discord had a hiccup", "<p>Go back to Game Night and try again in a moment.</p>", 502)
    request.app[DB].upsert_user(uid, name, avatar)
    code = request.app[BOOK].issue(uid, name, avatar, pending.challenge)
    link = "gamenight://signed-in?code=" + code
    log.info("%s signed in", name)
    return page(f"Hi {name}!",
                "<p>You're signed in. Switching back to Game Night…</p>"
                f'<a class="btn" href="{html.escape(link)}">Open Game Night</a>'
                '<p class="muted" style="margin-top:16px">If your browser asks, allow it to open Game Night. You can close this tab afterwards.</p>',
                extra_head=f'<meta http-equiv="refresh" content="0;url={html.escape(link)}">')


# ---------- app API ----------

def user_json(u: User) -> dict:
    return {"id": u.discord_id, "name": u.name, "avatar": u.avatar}


async def make_session(request: web.Request) -> web.Response:
    if not request.app[LIMITS]["session"].allow(client_ip(request)):
        raise web.HTTPTooManyRequests(text="Too many tries. Wait a minute.")
    try:
        body = await request.json()
        code, verifier = str(body["code"]), str(body["verifier"])
        device = str(body.get("device", ""))[:80]
    except Exception:
        raise web.HTTPBadRequest(text="Bad request.")
    ticket = request.app[BOOK].redeem(code, verifier)
    if not ticket:
        raise web.HTTPUnauthorized(text="That sign-in expired. Try again.")
    db = request.app[DB]
    user = db.upsert_user(ticket.discord_id, ticket.name, ticket.avatar)
    token = db.create_session(user.discord_id, device)
    return web.json_response({"token": token, "user": user_json(user)})


async def end_session(request: web.Request) -> web.Response:
    request.app[DB].end_session(request[TOKEN])
    return web.json_response({"ok": True})


async def me(request: web.Request) -> web.Response:
    return web.json_response(user_json(request[USER]))


async def list_games(request: web.Request) -> web.Response:
    try:
        games = await request.app[ROMM].games()
    except (aiohttp.ClientError, TimeoutError) as e:
        log.warning("RomM unreachable: %s", e)
        raise web.HTTPServiceUnavailable(text="The game library is offline right now.")
    return web.json_response({"games": [g.public() for g in games.values()]})


async def _game(request: web.Request):
    try:
        gid = int(request.match_info["id"])
        games = await request.app[ROMM].games()
    except ValueError:
        raise web.HTTPNotFound()
    except (aiohttp.ClientError, TimeoutError):
        raise web.HTTPServiceUnavailable(text="The game library is offline right now.")
    game = games.get(gid)
    if not game:
        raise web.HTTPNotFound(text="No such game.")
    return game


async def cover(request: web.Request) -> web.StreamResponse:
    game = await _game(request)
    if not game.cover:
        raise web.HTTPNotFound()
    try:
        upstream = await request.app[ROMM].open_cover(game)
    except (aiohttp.ClientError, TimeoutError, ValueError):
        raise web.HTTPNotFound()
    async with upstream:
        ctype = upstream.headers.get("Content-Type", "")
        if upstream.status != 200 or not ctype.startswith("image/") or "svg" in ctype:
            raise web.HTTPNotFound()
        # Read the whole picture. A single read() can stop part-way, which showed only the top of each cover.
        data = bytearray()
        async for chunk in upstream.content.iter_chunked(64 * 1024):
            data += chunk
            if len(data) > 8 * 1024 * 1024:
                raise web.HTTPNotFound()
    resp = web.Response(body=bytes(data), content_type=ctype.split(";")[0])
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp


async def download(request: web.Request) -> web.StreamResponse:
    game = await _game(request)
    rng = request.headers.get("Range")
    if rng and not (rng.startswith("bytes=") and len(rng) < 100):
        rng = None
    try:
        upstream = await request.app[ROMM].open_download(game, rng)
    except (aiohttp.ClientError, TimeoutError):
        raise web.HTTPServiceUnavailable(text="The game library is offline right now.")
    async with upstream:
        if upstream.status not in (200, 206):
            raise web.HTTPBadGateway(text="The game library couldn't send that game.")
        resp = web.StreamResponse(status=upstream.status)
        for h in ("Content-Length", "Content-Range", "Accept-Ranges", "Content-Type"):
            if h in upstream.headers:
                resp.headers[h] = upstream.headers[h]
        resp.headers["X-Game-File"] = game.file_name.encode("ascii", "ignore").decode()[:200] or "game"
        await resp.prepare(request)
        async for chunk in upstream.content.iter_chunked(256 * 1024):
            await resp.write(chunk)
        await resp.write_eof()
        log.info("%s downloaded %s", request[USER].name, game.title)
        return resp


# ---------- Couch Play lobbies ----------

def _lobby_call(fn, *args):
    try:
        return fn(*args)
    except lb.LobbyError as e:
        raise {403: web.HTTPForbidden, 404: web.HTTPNotFound, 409: web.HTTPConflict,
               503: web.HTTPServiceUnavailable}.get(e.status, web.HTTPBadRequest)(text=e.message)


async def _body(request: web.Request, allowed: set[str]) -> dict:
    """The JSON body: an object with only the expected keys."""
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Bad request.")
    if not isinstance(body, dict) or not set(body) <= allowed:
        raise web.HTTPBadRequest(text="Bad request.")
    return body


def _choice(body: dict, key: str, options: tuple) -> str:
    value = body.get(key)
    if not isinstance(value, str) or value not in options:
        raise web.HTTPBadRequest(text="Bad request.")
    return value


def _flag(body: dict, key: str) -> bool:
    value = body.get(key)
    if not isinstance(value, bool):
        raise web.HTTPBadRequest(text="Bad request.")
    return value


def _whole(value, lo: int, hi: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi


def _code_check(request: web.Request) -> str:
    """Looking up or joining by code: 20 a minute per person, so codes can't be guessed.
    People already in that lobby aren't counted."""
    code, uid = request.match_info["code"], request[USER].discord_id
    if not request.app[LOBBIES].is_member(code, uid) and not request.app[LIMITS]["code"].allow(uid):
        log.info("%s tried too many lobby codes; slowing them down", request[USER].name)
        raise web.HTTPTooManyRequests(text="Too many tries. Wait a minute, then check the code.")
    return code


async def lobby_list(request: web.Request) -> web.Response:
    return web.json_response({"lobbies": request.app[LOBBIES].open_list()})


async def lobby_host(request: web.Request) -> web.Response:
    body = await _body(request, {"game_id", "open"})
    gid, is_open = body.get("game_id"), _flag(body, "open")
    if not isinstance(gid, str) or not 1 <= len(gid) <= 12 or not gid.isascii() or not gid.isdigit():
        raise web.HTTPBadRequest(text="Bad request.")
    if not request.app[LIMITS]["host"].allow(request[USER].discord_id):
        raise web.HTTPTooManyRequests(text="Too many lobbies opened. Wait a minute.")
    try:
        games = await request.app[ROMM].games()
    except (aiohttp.ClientError, TimeoutError) as e:
        log.warning("RomM unreachable: %s", e)
        raise web.HTTPServiceUnavailable(text="The game library is offline right now.")
    game = games.get(int(gid))
    if not game:
        raise web.HTTPNotFound(text="No such game.")
    if game.console not in lb.CONSOLES:
        raise web.HTTPBadRequest(text="Only NES and SNES games can be played online for now.")
    info = {"id": str(game.id), "title": game.title, "console": game.console, "players": game.players}
    return web.json_response(_lobby_call(request.app[LOBBIES].host, user_json(request[USER]), info, is_open))


async def lobby_get(request: web.Request) -> web.Response:
    code = _code_check(request)
    return web.json_response(_lobby_call(request.app[LOBBIES].lookup, code, request[USER].discord_id))


async def lobby_join(request: web.Request) -> web.Response:
    code = _code_check(request)
    as_ = _choice(await _body(request, {"as"}), "as", ("play", "watch"))
    return web.json_response(_lobby_call(request.app[LOBBIES].join, code, user_json(request[USER]), as_))


async def lobby_switch(request: web.Request) -> web.Response:
    as_ = _choice(await _body(request, {"as"}), "as", ("play", "watch"))
    return web.json_response(_lobby_call(request.app[LOBBIES].switch, request.match_info["code"],
                                         request[USER].discord_id, as_))


async def lobby_heartbeat(request: web.Request) -> web.Response:
    state = _choice(await _body(request, {"retroarch"}), "retroarch", lb.RETROARCH_STATES)
    return web.json_response(_lobby_call(request.app[LOBBIES].heartbeat, request.match_info["code"],
                                         request[USER].discord_id, state))


async def lobby_pause(request: web.Request) -> web.Response:
    on = _flag(await _body(request, {"on"}), "on")
    return web.json_response(_lobby_call(request.app[LOBBIES].pause, request.match_info["code"],
                                         request[USER].discord_id, on))


async def lobby_relay(request: web.Request) -> web.Response:
    body = await _body(request, {"server", "port", "session"})
    server, port, session = body.get("server"), body.get("port"), body.get("session")
    if not lb.valid_relay_server(server) or not lb.valid_session(session) or not _whole(port, 1, 65535):
        raise web.HTTPBadRequest(text="Bad request.")
    return web.json_response(_lobby_call(request.app[LOBBIES].set_relay, request.match_info["code"],
                                         request[USER].discord_id, server, port, session))


async def lobby_patch(request: web.Request) -> web.Response:
    is_open = _flag(await _body(request, {"open"}), "open")
    return web.json_response(_lobby_call(request.app[LOBBIES].set_open, request.match_info["code"],
                                         request[USER].discord_id, is_open))


async def lobby_seat(request: web.Request) -> web.Response:
    body = await _body(request, {"seat", "action", "user"})
    seat, target = body.get("seat"), body.get("user")
    action = _choice(body, "action", ("hold", "give", "empty"))
    if not _whole(seat, 1, lb.SEATS):
        raise web.HTTPBadRequest(text="Bad request.")
    if (action == "give" or target is not None) and not lb.valid_user_id(target):
        raise web.HTTPBadRequest(text="Bad request.")
    return web.json_response(_lobby_call(request.app[LOBBIES].seat_action, request.match_info["code"],
                                         request[USER].discord_id, seat, action,
                                         target if action == "give" else None))


async def lobby_leave(request: web.Request) -> web.Response:
    _lobby_call(request.app[LOBBIES].leave, request.match_info["code"], request[USER].discord_id)
    return web.json_response({"ok": True})


async def healthz(_request: web.Request) -> web.Response:
    return web.Response(text="ok", headers={"Cache-Control": "no-store"})


def build(cfg, db: Database | None = None, romm_factory=None, lobbies: lb.LobbyBook | None = None) -> web.Application:
    app = web.Application(middlewares=[security_headers, require_pass], client_max_size=64 * 1024)
    app[CFG] = cfg
    app[DB] = db or Database(f"{cfg.data_dir}/gamenight.db", cfg.session_days)
    app[BOOK] = da.LoginBook()
    app[LIMITS] = {"login": RateLimit(10, 60), "session": RateLimit(10, 60), "bad_pass": RateLimit(30, 60),
                   "code": RateLimit(20, 60), "host": RateLimit(10, 60)}
    app[LOBBIES] = lobbies or lb.LobbyBook(log=log)

    async def startup(a: web.Application):
        a[HTTP] = aiohttp.ClientSession(headers={"User-Agent": "GameNight/0.1"})
        a[ROMM] = (romm_factory or RomM)(a[HTTP], cfg)

    async def cleanup(a: web.Application):
        await a[HTTP].close()

    async def hide_version(_request, resp):
        resp.headers["Server"] = "GameNight"

    app.on_response_prepare.append(hide_version)
    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    routes = [
        ("GET", "/healthz", healthz),
        ("GET", "/app/login", app_login),
        ("GET", "/auth/callback", auth_callback),
        ("POST", "/api/session", make_session),
        ("DELETE", "/api/session", end_session),
        ("GET", "/api/me", me),
        ("GET", "/api/games", list_games),
        ("GET", "/api/games/{id}/cover", cover),
        ("GET", "/api/games/{id}/download", download),
        ("GET", "/api/lobbies", lobby_list),
        ("POST", "/api/lobbies", lobby_host),
        ("GET", "/api/lobbies/{code}", lobby_get),
        ("PATCH", "/api/lobbies/{code}", lobby_patch),
        ("POST", "/api/lobbies/{code}/join", lobby_join),
        ("POST", "/api/lobbies/{code}/switch", lobby_switch),
        ("POST", "/api/lobbies/{code}/heartbeat", lobby_heartbeat),
        ("POST", "/api/lobbies/{code}/relay", lobby_relay),
        ("POST", "/api/lobbies/{code}/seat", lobby_seat),
        ("POST", "/api/lobbies/{code}/pause", lobby_pause),
        ("POST", "/api/lobbies/{code}/leave", lobby_leave),
    ]
    # Every address answers both as /x and, with BASE_PATH set, as BASE_PATH/x.
    base = getattr(cfg, "base_path", "")
    for prefix in ("", base) if base else ("",):
        for method, path, handler in routes:
            if method == "GET":
                app.router.add_get(prefix + path, handler)
            else:
                app.router.add_route(method, prefix + path, handler)
    return app
