"""Connection settings. Credentials come from the environment / .env, never from code."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


def load_dotenv(path: Path | str = ".env", environ: dict[str, str] | None = None) -> None:
    """Minimal .env reader: KEY=VALUE lines; existing environment variables win."""
    env = os.environ if environ is None else environ
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env.setdefault(key.strip(), value.strip().strip("'\""))


@dataclass(frozen=True)
class Settings:
    ch_host: str
    ch_port: int
    ch_user: str
    ch_password: str
    ch_database: str
    ch_compress: str | bool
    pg_host: str
    pg_port: int
    pg_user: str
    pg_password: str
    pg_database: str
    cold_restart_cmd: str | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ

        def need(key: str) -> str:
            value = env.get(key)
            if not value:
                raise RuntimeError(f"{key} is not set; copy .env.example to .env and fill it in")
            return value

        compress_raw = env.get("CH_COMPRESS", "false").strip().lower()
        compress: str | bool = False if compress_raw in ("", "false", "0", "no") else compress_raw
        return cls(
            ch_host=env.get("CH_HOST", "127.0.0.1"),
            ch_port=int(env.get("CH_HTTP_PORT", "8123")),
            ch_user=need("CH_USER"),
            ch_password=need("CH_PASSWORD"),
            ch_database=env.get("CH_DATABASE", "bench"),
            ch_compress=compress,
            pg_host=env.get("PG_HOST", "127.0.0.1"),
            pg_port=int(env.get("PG_PORT", "5433")),
            pg_user=need("PG_USER"),
            pg_password=need("PG_PASSWORD"),
            pg_database=env.get("PG_DATABASE", "bench"),
            cold_restart_cmd=(env.get("COLD_RESTART_CMD") or "").strip() or None,
        )

    def pg_uri(self) -> str:
        return (
            f"postgresql://{quote(self.pg_user, safe='')}:{quote(self.pg_password, safe='')}"
            f"@{self.pg_host}:{self.pg_port}/{quote(self.pg_database, safe='')}"
        )

    def public(self) -> dict[str, object]:
        """Settings safe to write into results files (no passwords)."""
        return {
            "ch_host": self.ch_host,
            "ch_port": self.ch_port,
            "ch_database": self.ch_database,
            "ch_compress": self.ch_compress,
            "pg_host": self.pg_host,
            "pg_port": self.pg_port,
            "pg_database": self.pg_database,
            "cold_restart_cmd": self.cold_restart_cmd,
        }
