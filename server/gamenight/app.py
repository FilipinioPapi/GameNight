"""The Game Night server's web addresses.

Browser pages:  /app/login, /auth/callback (Discord sign-in only)
App API:        /api/... (needs the app's sign-in pass, except trading a sign-in code for one)
"""
from __future__ import annotations

import html
import ipaddress
import logging
import time

import aiohttp
from aiohttp import web

from . import discord_auth as da
from .db import Database, User
from .romm import RomM

log = logging.getLogger("gamenight")

CFG = web.AppKey("cfg", object)
DB = web.AppKey("db", Database)
ROMM = web.AppKey("romm", RomM)
BOOK = web.AppKey("book", da.LoginBook)
HTTP = web.AppKey("http", aiohttp.ClientSession)
LIMITS = web.AppKey("limits", dict)
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


@web.middleware
async def require_pass(request: web.Request, handler):
    """Every /api address needs the app's sign-in pass, except trading a code for one."""
    if request.path.startswith("/api/") and not (request.path == "/api/session" and request.method == "POST"):
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


async def healthz(_request: web.Request) -> web.Response:
    return web.Response(text="ok", headers={"Cache-Control": "no-store"})


def build(cfg, db: Database | None = None, romm_factory=None) -> web.Application:
    app = web.Application(middlewares=[security_headers, require_pass], client_max_size=64 * 1024)
    app[CFG] = cfg
    app[DB] = db or Database(f"{cfg.data_dir}/gamenight.db", cfg.session_days)
    app[BOOK] = da.LoginBook()
    app[LIMITS] = {"login": RateLimit(10, 60), "session": RateLimit(10, 60), "bad_pass": RateLimit(30, 60)}

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
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/app/login", app_login)
    app.router.add_get("/auth/callback", auth_callback)
    app.router.add_post("/api/session", make_session)
    app.router.add_delete("/api/session", end_session)
    app.router.add_get("/api/me", me)
    app.router.add_get("/api/games", list_games)
    app.router.add_get("/api/games/{id}/cover", cover)
    app.router.add_get("/api/games/{id}/download", download)
    return app
