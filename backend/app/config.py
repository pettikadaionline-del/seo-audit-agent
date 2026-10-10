"""Runtime configuration, loaded from environment variables (prefix SEO_)."""
import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Applied on serverless platforms (Vercel sets VERCEL=1) unless overridden by env.
# Each request must finish inside the function time limit and the filesystem is
# read-only except /tmp.
SERVERLESS_DEFAULTS = {
    "max_pages_limit": 30,
    "default_max_pages": 25,
    "request_timeout_s": 8.0,
    "crawl_time_budget_s": 40.0,
    "concurrency": 6,
    "delay_between_requests_s": 0.1,
    "database_path": "/tmp/audits.db",
    "ai_effort": "low",  # keeps the Claude call well inside the function time limit
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SEO_", env_file=".env", extra="ignore")

    serverless: bool = bool(os.getenv("VERCEL"))
    crawl_time_budget_s: float = 0  # 0 = unlimited; stops crawling (keeps results) when exceeded

    # Crawl limits (hard ceilings; per-request values are clamped to these)
    max_pages_limit: int = 500
    default_max_pages: int = 50
    max_depth_limit: int = 6
    request_timeout_s: float = 15.0
    max_response_bytes: int = 5 * 1024 * 1024
    max_redirects: int = 5
    concurrency: int = 4
    delay_between_requests_s: float = 0.25
    user_agent: str = "SEOAuditBot/1.0 (+https://example.com/bot)"

    # Security
    allow_private_networks: bool = False  # only for local dev / tests
    rate_limit_per_minute: int = 10  # audit submissions per client IP
    api_key: str | None = None  # if set, required as X-API-Key header

    # AI layer (Anthropic). ANTHROPIC_API_KEY is read by the SDK itself.
    ai_enabled: bool = True
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "medium"
    ai_max_issues_in_prompt: int = 60

    # Optional Google PageSpeed Insights key for lab Core Web Vitals
    pagespeed_api_key: str | None = None

    # Storage
    database_path: str = "data/audits.db"
    cors_origins: str = "http://localhost:3000"

    @model_validator(mode="after")
    def _serverless_defaults(self) -> "Settings":
        if self.serverless:
            for key, value in SERVERLESS_DEFAULTS.items():
                if key not in self.model_fields_set:
                    setattr(self, key, value)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
