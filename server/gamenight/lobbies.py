"""Couch Play lobbies: who is hosting what, who sits where, and the relay details for the game.

Everything lives in memory (a server restart closes every lobby). Game traffic never comes
through here: it goes through libretro's relay. This only keeps the lobby book and hands the
relay details to people who are in the lobby.

Pure logic: no web code. The clock can be swapped for tests.
"""
from __future__ import annotations

import base64
import binascii
import ipaddress
import math
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Callable

CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no O/0/I/1
CODE_LENGTH = 6
CODE_RE = re.compile(f"^[{CODE_LETTERS}]{{{CODE_LENGTH}}}$")

SEATS = 4
MAX_WATCHERS = 4
MAX_LOBBIES = 200
DROP_SECONDS = 10        # no heartbeat for this long = dropped
HOLD_SECONDS = 120       # a dropped player's seat is kept for them this long
HOST_GONE_SECONDS = 30   # host silent this long = lobby closed
ENDED_KEEP_SECONDS = 60  # members can still see "this lobby ended" for a minute
PAUSE_MAX_SECONDS = 600  # a "pause for everyone" ends by itself after 10 minutes
RESUME_NOTE_SECONDS = 15  # how long the lobby says when the last pause ended
CONSOLES = ("nes", "snes")
RETROARCH_STATES = ("running", "starting", "stopped")

_LABEL = r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
HOST_RE = re.compile(rf"^(?=.{{1,253}}$){_LABEL}(?:\.{_LABEL})*$")
SESSION_RE = re.compile(r"^[A-Za-z0-9+/]{16}$")   # 12 bytes in base64 = 16 characters, no padding
USER_ID_RE = re.compile(r"^[0-9]{1,25}$")


class LobbyError(Exception):
    """Something the person asked for can't happen. `status` is the web answer code."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


NO_LOBBY = "That code doesn't match an open lobby."
SEATS_FULL = "All 4 seats are taken. You can watch."
HOST_ONLY = "Only the host can do that."


def normalise_code(raw: str) -> str | None:
    """A code as typed (any case, spaces around it) -> the code, or None if it can't be one."""
    code = (raw or "").strip().upper()
    return code if CODE_RE.match(code) else None


def valid_relay_server(server: object) -> bool:
    if not isinstance(server, str) or not server or len(server) > 253:
        return False
    try:
        ipaddress.ip_address(server)
        return True
    except ValueError:
        return bool(HOST_RE.match(server))


def valid_session(session: object) -> bool:
    if not isinstance(session, str) or not SESSION_RE.match(session):
        return False
    try:
        return len(base64.b64decode(session, validate=True)) == 12
    except (binascii.Error, ValueError):
        return False


def valid_user_id(uid: object) -> bool:
    return isinstance(uid, str) and bool(USER_ID_RE.match(uid))


@dataclass
class Member:
    user: dict                    # {"id", "name", "avatar"}
    seat: int | None              # 1-4 when playing (or held), None when watching
    last_seen: float
    held_until: float | None = None
    retroarch: str = "starting"


@dataclass
class Lobby:
    code: str
    game: dict                    # {"id", "title", "console", "players"}
    host_id: str
    open: bool
    created: float
    members: dict[str, Member] = field(default_factory=dict)
    seats: dict[int, str | None] = field(default_factory=lambda: {n: None for n in range(1, SEATS + 1)})
    watchers: list[str] = field(default_factory=list)
    relay: dict | None = None
    ended: str | None = None      # None, "host-left" or "host-ended"
    ended_at: float = 0.0
    paused_by: str | None = None  # who paused the game for everyone (in-game menu), if anyone
    paused_at: float = 0.0
    resumed_at: float | None = None  # when the last pause for everyone ended

    def free_seat(self) -> int | None:
        return next((n for n, uid in self.seats.items() if uid is None), None)


class LobbyBook:
    def __init__(self, clock: Callable[[], float] = time.monotonic, log=None):
        self.clock = clock
        self.log = log
        self.lobbies: dict[str, Lobby] = {}
        self.where: dict[str, str] = {}   # user id -> code of the (live) lobby they're in

    # ---------- housekeeping ----------

    def _say(self, msg: str, *args) -> None:
        if self.log:
            self.log.info(msg, *args)

    def tick(self) -> None:
        """Drop silent people, empty seats whose hold ran out, close lobbies whose host left."""
        now = self.clock()
        for code, lobby in list(self.lobbies.items()):
            if lobby.ended:
                if now - lobby.ended_at >= ENDED_KEEP_SECONDS:
                    del self.lobbies[code]
                continue
            host = lobby.members[lobby.host_id]
            if now - host.last_seen >= HOST_GONE_SECONDS:
                self._end(lobby, "host-left", host.last_seen + HOST_GONE_SECONDS)
                self._say("%s's lobby for %s closed: the host went quiet", host.user["name"], lobby.game["title"])
                continue
            if lobby.paused_by is not None:
                who = lobby.members.get(lobby.paused_by)
                if now - lobby.paused_at >= PAUSE_MAX_SECONDS or not who or who.seat is None \
                        or now - who.last_seen >= DROP_SECONDS:
                    self._unpause(lobby)
                    self._say("%s in %s carries on (the pause ended by itself)", lobby.game["title"], lobby.code)
            for uid, m in list(lobby.members.items()):
                if uid == lobby.host_id or now - m.last_seen < DROP_SECONDS:
                    continue
                if m.seat is None:
                    self._remove(lobby, uid)
                    self._say("%s stopped watching %s (went quiet)", m.user["name"], lobby.game["title"])
                elif m.held_until is None:
                    m.held_until = m.last_seen + DROP_SECONDS + HOLD_SECONDS
                    self._say("%s dropped out of %s; seat %s is held for them", m.user["name"], lobby.game["title"], m.seat)
                if m.held_until is not None and now >= m.held_until:
                    self._say("Seat %s in %s was emptied (%s didn't come back)", m.seat, lobby.game["title"], m.user["name"])
                    self._remove(lobby, uid)

    def _end(self, lobby: Lobby, why: str, when: float | None = None) -> None:
        lobby.ended = why
        lobby.ended_at = self.clock() if when is None else when
        lobby.relay = None
        for uid in lobby.members:
            if self.where.get(uid) == lobby.code:
                del self.where[uid]

    def _unpause(self, lobby: Lobby) -> None:
        lobby.paused_by = None
        lobby.resumed_at = self.clock()

    def _remove(self, lobby: Lobby, uid: str) -> None:
        m = lobby.members.pop(uid, None)
        if not m:
            return
        if lobby.paused_by == uid:
            self._unpause(lobby)
        if m.seat is not None and lobby.seats.get(m.seat) == uid:
            lobby.seats[m.seat] = None
        if uid in lobby.watchers:
            lobby.watchers.remove(uid)
        if self.where.get(uid) == lobby.code:
            del self.where[uid]

    def _leave_other(self, uid: str, keep: str | None = None) -> None:
        """Everyone is in at most one lobby. Going somewhere new leaves the old one."""
        code = self.where.get(uid)
        if code and code != keep and code in self.lobbies:
            self.leave(code, uid)

    def _new_code(self) -> str:
        while True:
            code = "".join(secrets.choice(CODE_LETTERS) for _ in range(CODE_LENGTH))
            if code not in self.lobbies:
                return code

    def _get(self, raw_code: str) -> Lobby:
        code = normalise_code(raw_code)
        lobby = self.lobbies.get(code) if code else None
        if not lobby:
            raise LobbyError(404, NO_LOBBY)
        return lobby

    def _live(self, raw_code: str) -> Lobby:
        lobby = self._get(raw_code)
        if lobby.ended:
            raise LobbyError(404, NO_LOBBY)
        return lobby

    def _host_lobby(self, raw_code: str, uid: str) -> Lobby:
        lobby = self._get(raw_code)
        if uid not in lobby.members:   # same answer as a wrong code, so codes can't be tested here
            raise LobbyError(404, NO_LOBBY)
        if lobby.ended:
            raise LobbyError(409, "This lobby has ended.")
        if lobby.host_id != uid:
            raise LobbyError(403, HOST_ONLY)
        return lobby

    # ---------- what people see ----------

    def summary(self, lobby: Lobby) -> dict:
        host = lobby.members[lobby.host_id]
        return {
            "code": lobby.code,
            "open": lobby.open,
            "game": dict(lobby.game),
            "host": dict(host.user),
            "players": sum(1 for uid in lobby.seats.values() if uid),
            "watchers": len(lobby.watchers),
            "started": lobby.relay is not None,
        }

    def view(self, lobby: Lobby, uid: str) -> dict:
        """The full lobby, for someone who is in it. Only members ever get the relay details."""
        now = self.clock()
        me = lobby.members[uid]
        seats = []
        for n, sid in lobby.seats.items():
            if sid is None:
                seats.append({"n": n, "user": None, "status": "empty", "held_left": None})
                continue
            m = lobby.members[sid]
            left = None
            if lobby.ended:
                status = "playing"
            elif m.held_until is not None:
                status, left = "held", max(0, math.ceil(m.held_until - now))
            elif sid == lobby.host_id and now - m.last_seen >= DROP_SECONDS:
                status, left = "held", max(0, math.ceil(m.last_seen + HOST_GONE_SECONDS - now))
            else:
                status = "playing"
            seats.append({"n": n, "user": dict(m.user), "status": status, "held_left": left})
        out = self.summary(lobby)
        out.update({
            "you": {"id": uid, "role": "host" if uid == lobby.host_id else ("play" if me.seat else "watch"),
                    "seat": me.seat},
            "seats": seats,
            "watchers": [dict(lobby.members[w].user) for w in lobby.watchers],
            "relay": dict(lobby.relay) if lobby.relay and not lobby.ended else None,
            "ended": lobby.ended,
            # "ago" / "resumed_ago" (seconds, to 0.01) let every PC pause and resume in the order RetroArch's netplay
            # survives (the host first, friends after it), each on its own heartbeat (app: couch.rs follow_pause).
            "paused": ({"by": dict(lobby.members[lobby.paused_by].user), "seconds": max(0, int(now - lobby.paused_at)),
                        "ago": round(max(0.0, now - lobby.paused_at), 2)}
                       if lobby.paused_by in lobby.members and not lobby.ended else None),
            "resumed_ago": (round(max(0.0, now - lobby.resumed_at), 2)
                            if lobby.paused_by is None and lobby.resumed_at is not None
                            and now - lobby.resumed_at < RESUME_NOTE_SECONDS and not lobby.ended else None),
        })
        return out

    def is_member(self, raw_code: str, uid: str) -> bool:
        code = normalise_code(raw_code)
        lobby = self.lobbies.get(code) if code else None
        return bool(lobby and uid in lobby.members)

    # ---------- calls ----------

    def open_list(self) -> list[dict]:
        self.tick()
        live = [lb for lb in self.lobbies.values() if lb.open and not lb.ended]
        live.sort(key=lambda lb: lb.created)
        return [self.summary(lb) for lb in live]

    def host(self, user: dict, game: dict, is_open: bool) -> dict:
        self.tick()
        uid = user["id"]
        self._leave_other(uid)   # one lobby per host: hosting again ends the old one
        if sum(1 for lb in self.lobbies.values() if not lb.ended) >= MAX_LOBBIES:
            raise LobbyError(503, "Too many lobbies are open right now. Try again in a little while.")
        now = self.clock()
        lobby = Lobby(code=self._new_code(), game=dict(game), host_id=uid, open=is_open, created=now)
        lobby.members[uid] = Member(user=dict(user), seat=1, last_seen=now)
        lobby.seats[1] = uid
        self.lobbies[lobby.code] = lobby
        self.where[uid] = lobby.code
        self._say("%s opened a %s lobby for %s", user["name"], "open" if is_open else "closed", game["title"])
        return self.view(lobby, uid)

    def lookup(self, raw_code: str, uid: str) -> dict:
        self.tick()
        lobby = self._get(raw_code)
        if uid in lobby.members:
            return self.view(lobby, uid)
        if lobby.ended:
            raise LobbyError(404, NO_LOBBY)
        return self.summary(lobby)

    def join(self, raw_code: str, user: dict, as_: str) -> dict:
        self.tick()
        lobby = self._live(raw_code)
        uid = user["id"]
        m = lobby.members.get(uid)
        if m:
            m.user = dict(user)
            m.last_seen = self.clock()
            if m.held_until is not None:
                m.held_until = None
                self._say("%s came back to %s and got seat %s back", user["name"], lobby.game["title"], m.seat)
            if (as_ == "play") != (m.seat is not None):
                return self.switch(raw_code, uid, as_)
            return self.view(lobby, uid)
        if as_ == "play":
            seat = lobby.free_seat()
            if seat is None:
                raise LobbyError(409, SEATS_FULL)
        else:
            seat = None
            if len(lobby.watchers) >= MAX_WATCHERS:
                raise LobbyError(409, "This lobby is full.")
        self._leave_other(uid, keep=lobby.code)
        lobby.members[uid] = Member(user=dict(user), seat=seat, last_seen=self.clock())
        if seat:
            lobby.seats[seat] = uid
        else:
            lobby.watchers.append(uid)
        self.where[uid] = lobby.code
        self._say("%s joined %s's %s lobby %s", user["name"], lobby.members[lobby.host_id].user["name"],
                  lobby.game["title"], f"in seat {seat}" if seat else "to watch")
        return self.view(lobby, uid)

    def _member(self, raw_code: str, uid: str) -> tuple[Lobby, Member]:
        lobby = self._get(raw_code)
        m = lobby.members.get(uid)
        if not m:
            raise LobbyError(404, NO_LOBBY)   # same answer as a wrong code
        return lobby, m

    def switch(self, raw_code: str, uid: str, as_: str) -> dict:
        self.tick()
        lobby, m = self._member(raw_code, uid)
        if lobby.ended:
            raise LobbyError(409, "This lobby has ended.")
        if as_ == "watch" and m.seat is not None:
            if uid == lobby.host_id:
                raise LobbyError(409, "The host always plays in seat 1.")
            if len(lobby.watchers) >= MAX_WATCHERS:
                raise LobbyError(409, "There's no room to watch right now.")
            lobby.seats[m.seat] = None
            m.seat, m.held_until = None, None
            lobby.watchers.append(uid)
            if lobby.paused_by == uid:
                self._unpause(lobby)
        elif as_ == "play" and m.seat is None:
            seat = lobby.free_seat()
            if seat is None:
                raise LobbyError(409, SEATS_FULL)
            lobby.watchers.remove(uid)
            lobby.seats[seat] = uid
            m.seat = seat
        return self.view(lobby, uid)

    def pause(self, raw_code: str, uid: str, on: bool) -> dict:
        """"Pause for everyone" from the in-game menu. Anyone playing can pause; the one who paused or the
        host can resume. The host's app does the real pausing (its RetroArch pauses the game for everyone)."""
        self.tick()
        lobby, m = self._member(raw_code, uid)
        if lobby.ended:
            raise LobbyError(409, "This lobby has ended.")
        if on:
            if m.seat is None:
                raise LobbyError(409, "Only players can pause the game.")
            if lobby.paused_by is None:
                lobby.paused_by, lobby.paused_at = uid, self.clock()
                self._say("%s paused %s for everyone", m.user["name"], lobby.game["title"])
        elif lobby.paused_by is not None:
            if uid not in (lobby.paused_by, lobby.host_id):
                raise LobbyError(403, "Only the one who paused, or the host, can resume.")
            self._unpause(lobby)
            self._say("%s resumed %s for everyone", m.user["name"], lobby.game["title"])
        return self.view(lobby, uid)

    def heartbeat(self, raw_code: str, uid: str, retroarch: str) -> dict:
        self.tick()
        lobby, m = self._member(raw_code, uid)
        if not lobby.ended:
            m.last_seen = self.clock()
            m.retroarch = retroarch
            if m.held_until is not None:
                m.held_until = None
                self._say("%s is back in %s (seat %s)", m.user["name"], lobby.game["title"], m.seat)
        return self.view(lobby, uid)

    def set_relay(self, raw_code: str, uid: str, server: str, port: int, session: str) -> dict:
        self.tick()
        lobby = self._host_lobby(raw_code, uid)
        lobby.relay = {"server": server, "port": port, "session": session}
        lobby.members[uid].last_seen = self.clock()
        self._say("%s's %s lobby is ready to play", lobby.members[uid].user["name"], lobby.game["title"])
        return self.view(lobby, uid)

    def set_open(self, raw_code: str, uid: str, is_open: bool) -> dict:
        self.tick()
        lobby = self._host_lobby(raw_code, uid)
        lobby.open = is_open
        return self.view(lobby, uid)

    def seat_action(self, raw_code: str, uid: str, seat: int, action: str, target: str | None) -> dict:
        self.tick()
        lobby = self._host_lobby(raw_code, uid)
        if seat == 1:
            raise LobbyError(409, "Seat 1 is the host's seat.")
        sid = lobby.seats[seat]
        sm = lobby.members.get(sid) if sid else None
        if action == "hold":
            if not sm or sm.held_until is None:
                raise LobbyError(409, "That seat isn't waiting for anyone.")
            sm.held_until = self.clock() + HOLD_SECONDS
        elif action == "empty":
            if not sm:
                raise LobbyError(409, "That seat is already empty.")
            if sm.held_until is None and len(lobby.watchers) < MAX_WATCHERS:
                lobby.seats[seat] = None      # someone still here: move them to watching
                sm.seat = None
                lobby.watchers.append(sid)
            else:
                self._remove(lobby, sid)
        elif action == "give":
            if not target or target not in lobby.watchers:
                raise LobbyError(409, "That person isn't watching this lobby.")
            if sm and sm.held_until is None:
                raise LobbyError(409, "Someone is playing in that seat.")
            if sm:
                self._remove(lobby, sid)
            lobby.watchers.remove(target)
            lobby.seats[seat] = target
            lobby.members[target].seat = seat
        return self.view(lobby, uid)

    def leave(self, raw_code: str, uid: str) -> None:
        """Always fine, even for a wrong code (so it can't be used to test codes)."""
        self.tick()
        code = normalise_code(raw_code)
        lobby = self.lobbies.get(code) if code else None
        if not lobby or uid not in lobby.members or lobby.ended:
            return
        if uid == lobby.host_id:
            self._end(lobby, "host-ended")
            self._say("%s ended their %s lobby", lobby.members[uid].user["name"], lobby.game["title"])
        else:
            self._say("%s left %s", lobby.members[uid].user["name"], lobby.game["title"])
            self._remove(lobby, uid)
