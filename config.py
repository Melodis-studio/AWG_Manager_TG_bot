import os
from dataclasses import dataclass

@dataclass
class Config:
    BOT_TOKEN: str
    ALLOWED_USER_IDS: list[int]
    AWG_BASE_URL: str
    AWG_FALLBACK_URL: str | None
    AWG_LOGIN: str
    AWG_PASSWORD: str
    TUNNEL_ID: str | None

    @staticmethod
    def load() -> "Config":
        token = os.getenv("BOT_TOKEN")
        if not token:
            raise ValueError("BOT_TOKEN не задан")
        raw_ids = os.getenv("ALLOWED_USER_IDS", "")
        allowed = [int(x.strip()) for x in raw_ids.split(",") if x.strip()]
        if not allowed:
            raise ValueError("ALLOWED_USER_IDS не задан")
        base_url = os.getenv("AWG_BASE_URL", "http://localhost:52819/api").rstrip("/")
        fallback_url = os.getenv("AWG_FALLBACK_URL", "").rstrip("/") or None
        login = os.getenv("AWG_LOGIN", "admin")
        password = os.getenv("AWG_PASSWORD", "")
        if not password:
            raise ValueError("AWG_PASSWORD не задан")
        tunnel_id = os.getenv("TUNNEL_ID", "").strip() or None
        return Config(
            BOT_TOKEN=token,
            ALLOWED_USER_IDS=allowed,
            AWG_BASE_URL=base_url,
            AWG_FALLBACK_URL=fallback_url,
            AWG_LOGIN=login,
            AWG_PASSWORD=password,
            TUNNEL_ID=tunnel_id,
        )
