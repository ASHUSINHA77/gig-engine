"""Application configuration loaded from environment variables."""

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database — defaults to SQLite for zero-config local dev.
    # Accepts raw postgres:// / postgresql:// URLs (Replit-managed) and
    # automatically rewrites them to the asyncpg async driver URL.
    database_url: str = "sqlite+aiosqlite:///./gig_engine.db"

    # Set automatically during normalisation — True when the upstream URL
    # contained sslmode=require (asyncpg needs ssl via connect_args, not URL).
    db_require_ssl: bool = False

    @classmethod
    def _normalize_db_url(cls, v: str) -> tuple[str, bool]:
        """
        Rewrite sync postgres:// URLs to async postgresql+asyncpg://.
        asyncpg does not accept ?sslmode=… in the URL — strip it and return
        a separate flag so database.py can pass ssl='require' via connect_args.
        """
        require_ssl = False

        if v.startswith("postgres://"):
            v = "postgresql+asyncpg://" + v[len("postgres://"):]
        elif v.startswith("postgresql://") and "+asyncpg" not in v:
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]

        # Strip sslmode — asyncpg ignores / rejects it in the DSN
        if "sslmode" in v:
            parsed = urlparse(v)
            params = {k: vals[0] for k, vals in parse_qs(parsed.query).items()}
            ssl_val = params.pop("sslmode", None)
            require_ssl = ssl_val in ("require", "verify-ca", "verify-full")
            v = urlunparse(parsed._replace(query=urlencode(params)))

        return v, require_ssl

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        url, ssl = self._normalize_db_url(self.database_url)
        object.__setattr__(self, "database_url", url)
        object.__setattr__(self, "db_require_ssl", ssl)

    # Uvicorn server
    port: int = 8000
    log_level: str = "info"

    # Matching algorithm tunables
    # Weight for normalised distance in compound score (0-1)
    distance_weight: float = 0.6
    # Weight for normalised (inverted) skill rating in compound score (0-1)
    rating_weight: float = 0.4
    # Reference distance (km) used for normalisation
    max_reference_distance_km: float = 100.0
    # Reference skill rating cap used for normalisation
    max_skill_rating: float = 10.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
