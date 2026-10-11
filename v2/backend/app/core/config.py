from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Storage
    database_url: str = "sqlite+aiosqlite:///./seo_agent.db"

    # Crawl limits (defaults sized for SME sites; override per audit up to the hard caps)
    default_max_pages: int = 50
    hard_max_pages: int = 500
    default_max_depth: int = 4
    crawl_concurrency: int = 4
    request_delay_seconds: float = 0.5  # polite delay between requests to the same host
    request_timeout_seconds: float = 15.0
    max_response_bytes: int = 5_000_000
    max_redirects: int = 5
    user_agent: str = "SEOAuditAgent/1.0 (+https://github.com/seo-audit-agent)"
    max_concurrent_audits: int = 2

    # Security: block private / loopback / link-local targets (SSRF). Only disable for local testing.
    allow_private_targets: bool = False

    # AI
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    ai_effort: str = "medium"
    ai_enabled: bool = True

    # Real-user performance data (optional). Without a key the API is called anonymously (low quota).
    pagespeed_api_key: str | None = None
    pagespeed_enabled: bool = True

    cors_origins: str = "http://localhost:3000"

    # When set, every /api call (except health) must send this code. Set it on any public deployment
    # so strangers can't run audits on your Claude/hosting bill.
    access_code: str | None = None
    # Directory with the exported dashboard (frontend `next build` output). Served at "/" when present.
    static_dir: str = "static"

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, v: str) -> str:
        # Hosting platforms hand out postgres:// URLs; SQLAlchemy async needs the asyncpg driver.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+asyncpg://" + v[len(prefix):]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
