"""The server's small database: who has signed in, and their app sign-in passes.

Only a hash of each pass is stored, so a copy of this file can't be used to sign in.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    discord_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    avatar TEXT NOT NULL DEFAULT '',
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    discord_id TEXT NOT NULL REFERENCES users(discord_id) ON DELETE CASCADE,
    device TEXT NOT NULL DEFAULT '',
    created INTEGER NOT NULL,
    last_used INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(discord_id);
"""


@dataclass(frozen=True)
class User:
    discord_id: str
    name: str
    avatar: str


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Database:
    def __init__(self, path: str, session_days: int = 30):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        self.session_seconds = session_days * 86400

    def upsert_user(self, discord_id: str, name: str, avatar: str) -> User:
        now = int(time.time())
        self.conn.execute(
            "INSERT INTO users(discord_id, name, avatar, first_seen, last_seen) VALUES (?,?,?,?,?) "
            "ON CONFLICT(discord_id) DO UPDATE SET name=excluded.name, avatar=excluded.avatar, last_seen=excluded.last_seen",
            (discord_id, name, avatar, now, now),
        )
        self.conn.commit()
        return User(discord_id, name, avatar)

    def create_session(self, discord_id: str, device: str = "") -> str:
        """Makes a new sign-in pass for the app and returns it (shown once, never stored)."""
        token = "gn_" + secrets.token_urlsafe(32)
        now = int(time.time())
        self.conn.execute(
            "INSERT INTO sessions(token_hash, discord_id, device, created, last_used) VALUES (?,?,?,?,?)",
            (_hash(token), discord_id, device[:80], now, now),
        )
        self.conn.commit()
        return token

    def check_session(self, token: str) -> User | None:
        """Who this pass belongs to, if it's real and has been used in the last SESSION_DAYS."""
        if not token.startswith("gn_") or len(token) > 100:
            return None
        now = int(time.time())
        row = self.conn.execute(
            "SELECT u.discord_id, u.name, u.avatar, s.last_used FROM sessions s "
            "JOIN users u ON u.discord_id = s.discord_id WHERE s.token_hash = ?",
            (_hash(token),),
        ).fetchone()
        if not row:
            return None
        if now - row[3] > self.session_seconds:
            self.conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))
            self.conn.commit()
            return None
        if now - row[3] > 300:  # don't write on every request
            self.conn.execute("UPDATE sessions SET last_used = ? WHERE token_hash = ?", (now, _hash(token)))
            self.conn.commit()
        return User(row[0], row[1], row[2])

    def end_session(self, token: str) -> None:
        self.conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))
        self.conn.commit()

    def sign_out_everywhere(self, who: str) -> int:
        """Ends every pass for a Discord ID or name. Returns how many were ended."""
        cur = self.conn.execute(
            "DELETE FROM sessions WHERE discord_id = ? OR discord_id IN (SELECT discord_id FROM users WHERE lower(name) = lower(?))",
            (who, who),
        )
        self.conn.commit()
        return cur.rowcount

    def list_sessions(self) -> list[tuple[str, str, str, int]]:
        return self.conn.execute(
            "SELECT u.name, u.discord_id, s.device, s.last_used FROM sessions s JOIN users u ON u.discord_id = s.discord_id "
            "ORDER BY s.last_used DESC"
        ).fetchall()
