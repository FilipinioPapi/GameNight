"""Signing in with Discord, for the Windows app.

How it works:
1. The app opens the browser at /app/login with a "challenge" (a fingerprint of a secret
   only the app knows).
2. We send the browser to Discord's own page. Passwords are only ever typed there.
3. Discord sends the browser back with a one-time code. We ask Discord "who is this, and
   are they in Jayden's server?" (plus the Game Night role, if one is set) (scopes: identify +
   guilds.members.read), then hand Discord's token straight back (revoke). We never keep it.
4. The browser passes a short-lived code to the app (gamenight://signed-in). The app trades
   it, together with its secret, for its own sign-in pass. Another program that grabbed the
   code can't use it, because it doesn't have the secret.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import aiohttp

DISCORD_API = "https://discord.com/api/v10"
AUTHORIZE = "https://discord.com/oauth2/authorize"
SCOPES = "identify guilds.members.read"
LOGIN_SECONDS = 600     # time allowed on Discord's page
CODE_SECONDS = 120      # time allowed for the app to pick up its code
MAX_PENDING = 2000


class NotAllowed(Exception):
    """Signed in fine, but not a Game Night member."""


class DiscordError(Exception):
    """Discord didn't cooperate."""


@dataclass
class Pending:
    challenge: str
    expires: float


@dataclass
class Ticket:
    discord_id: str
    name: str
    avatar: str
    challenge: str
    expires: float


def challenge_of(verifier: str) -> str:
    """The PKCE S256 fingerprint of the app's secret."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def valid_challenge(c: str) -> bool:
    return 43 <= len(c) <= 128 and all(ch.isalnum() or ch in "-_" for ch in c)


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    return AUTHORIZE + "?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": SCOPES, "state": state, "prompt": "none",
    })


def avatar_url(user_id: str, avatar_hash: str | None) -> str:
    if avatar_hash:
        return f"https://cdn.discordapp.com/avatars/{int(user_id)}/{avatar_hash}.png?size=128"
    return f"https://cdn.discordapp.com/embed/avatars/{(int(user_id) >> 22) % 6}.png"


class LoginBook:
    """Remembers sign-ins in progress (in memory, short-lived)."""

    def __init__(self):
        self.pending: dict[str, Pending] = {}
        self.tickets: dict[str, Ticket] = {}

    def _tidy(self) -> None:
        now = time.time()
        self.pending = {k: v for k, v in self.pending.items() if v.expires > now}
        self.tickets = {k: v for k, v in self.tickets.items() if v.expires > now}

    def start(self, challenge: str) -> str:
        self._tidy()
        if len(self.pending) >= MAX_PENDING:
            raise DiscordError("Too many sign-ins at once. Try again in a few minutes.")
        state = secrets.token_urlsafe(24)
        self.pending[state] = Pending(challenge, time.time() + LOGIN_SECONDS)
        return state

    def finish(self, state: str) -> Pending | None:
        p = self.pending.pop(state, None)
        return p if p and p.expires > time.time() else None

    def issue(self, discord_id: str, name: str, avatar: str, challenge: str) -> str:
        self._tidy()
        code = secrets.token_urlsafe(24)
        self.tickets[code] = Ticket(discord_id, name, avatar, challenge, time.time() + CODE_SECONDS)
        return code

    def redeem(self, code: str, verifier: str) -> Ticket | None:
        """One use only. Needs the app's secret that matches the challenge it started with."""
        t = self.tickets.pop(code, None)
        if not t or t.expires < time.time():
            return None
        if not secrets.compare_digest(challenge_of(verifier), t.challenge):
            return None
        return t


def has_access(member: dict, role_id: str) -> bool:
    """Being in Jayden's Discord server is enough when no role is set. If a role is set, you need it."""
    if not str(role_id or "").strip():
        return True
    return str(role_id).strip() in [str(r) for r in member.get("roles", [])]


async def check_member(http: aiohttp.ClientSession, cfg, code: str) -> tuple[str, str, str]:
    """Swap Discord's code for who you are, and check you're in Jayden's server (and have the role, if one is set).
    Returns (discord id, display name, avatar url). Discord's token is revoked right after."""
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": cfg.redirect_uri}
    auth = aiohttp.BasicAuth(cfg.discord_client_id, cfg.discord_client_secret)
    async with http.post(f"{DISCORD_API}/oauth2/token", data=form, auth=auth) as resp:
        if resp.status != 200:
            raise DiscordError("Discord didn't accept the sign-in. Try again.")
        token = (await resp.json()).get("access_token", "")
    try:
        headers = {"Authorization": f"Bearer {token}"}
        async with http.get(f"{DISCORD_API}/users/@me/guilds/{cfg.guild_id}/member", headers=headers) as resp:
            if resp.status == 404:
                raise NotAllowed()
            if resp.status != 200:
                raise DiscordError("Discord didn't say who you are. Try again.")
            member = await resp.json()
    finally:
        try:
            async with http.post(f"{DISCORD_API}/oauth2/token/revoke", auth=auth,
                                 data={"token": token, "token_type_hint": "access_token"}):
                pass
        except aiohttp.ClientError:
            pass
    if not has_access(member, cfg.role_id):
        raise NotAllowed()
    user = member.get("user") or {}
    uid = str(user.get("id", ""))
    if not uid.isdigit():
        raise DiscordError("Discord sent something odd. Try again.")
    name = member.get("nick") or user.get("global_name") or user.get("username") or "Player"
    return uid, str(name)[:40], avatar_url(uid, user.get("avatar"))
