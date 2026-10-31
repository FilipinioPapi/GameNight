"""Server settings, all from the container's environment variables (set in the Unraid template)."""
from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass


def _get(name: str, default: str = "", required: bool = False) -> str:
    value = os.getenv(name, default).strip()
    if required and not value:
        raise SystemExit(f"Missing required setting: {name} (add it to the Game Night container)")
    return value


@dataclass(frozen=True)
class Config:
    public_url: str              # how browsers reach this server, e.g. http://192.168.1.33:8094
    discord_client_id: str
    discord_client_secret: str
    guild_id: str                # Jayden's Discord server
    role_id: str                 # optional "Game Night" role; blank = anyone in the Discord server
    romm_url: str                # RomM on the home network, e.g. http://192.168.1.33:8084
    romm_token: str              # a read-only RomM API token (preferred)
    romm_user: str               # or a Viewer user + password
    romm_password: str
    data_dir: str
    port: int
    session_days: int
    trusted_proxies: tuple
    log_level: str

    @property
    def secure(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url}/auth/callback"


def load() -> Config:
    proxies = []
    for part in _get("TRUSTED_PROXIES", "172.16.0.0/12,127.0.0.1/32").split(","):
        if part.strip():
            proxies.append(ipaddress.ip_network(part.strip(), strict=False))
    cfg = Config(
        public_url=_get("PUBLIC_URL", required=True).rstrip("/"),
        discord_client_id=_get("DISCORD_CLIENT_ID", required=True),
        discord_client_secret=_get("DISCORD_CLIENT_SECRET", required=True),
        guild_id=_get("DISCORD_GUILD_ID", required=True),
        role_id=_get("DISCORD_ROLE_ID"),
        romm_url=_get("ROMM_URL", "http://192.168.1.33:8084").rstrip("/"),
        romm_token=_get("ROMM_TOKEN"),
        romm_user=_get("ROMM_USER"),
        romm_password=_get("ROMM_PASSWORD"),
        data_dir=_get("DATA_DIR", "/data"),
        port=int(_get("PORT", "8094")),
        session_days=int(_get("SESSION_DAYS", "30")),
        trusted_proxies=tuple(proxies),
        log_level=_get("LOG_LEVEL", "INFO").upper(),
    )
    if not cfg.romm_token and not (cfg.romm_user and cfg.romm_password):
        raise SystemExit("Add either ROMM_TOKEN, or ROMM_USER and ROMM_PASSWORD, to the Game Night container")
    return cfg
