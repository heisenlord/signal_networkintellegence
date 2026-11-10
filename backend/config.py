"""Load backend configuration before database/client initialization."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
# Process environment wins; backend/.env can override defaults in the root .env.
load_dotenv(ROOT / "backend/.env", override=False)
load_dotenv(ROOT / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    signal_environment: Literal["development", "production"] = "development"
    signal_allowed_hosts: list[str] = ["localhost", "127.0.0.1", "[::1]"]
    signal_allowed_origins: list[str] = []
    render_external_hostname: str = ""
    signal_oidc_issuer: str = ""
    signal_oidc_audience: str = ""
    signal_oidc_jwks_url: str = ""
    signal_static_dir: str = ""
    signal_max_body_bytes: int = Field(default=16384, ge=1024, le=1048576)
    signal_requests_per_minute: int = Field(default=300, ge=10, le=10000)
    signal_max_concurrent_investigations: int = Field(default=2, ge=1, le=8)
    signal_investigations_per_minute: int = Field(default=6, ge=1, le=60)

    @model_validator(mode="after")
    def secure_production(self):
        from urllib.parse import urlsplit
        import re
        defaults = ["localhost", "127.0.0.1", "[::1]"]
        if self.render_external_hostname and self.signal_allowed_hosts == defaults:
            if not re.fullmatch(r"[a-zA-Z0-9.-]+", self.render_external_hostname):
                raise ValueError("Invalid RENDER_EXTERNAL_HOSTNAME")
            self.signal_allowed_hosts = [self.render_external_hostname, "localhost"]
        for origin in self.signal_allowed_origins:
            url = urlsplit(origin)
            if (not url.hostname or "*" in origin or url.username or url.password or url.query or url.fragment
                    or url.path or url.scheme not in {"http", "https"}
                    or (self.signal_environment == "production" and url.scheme != "https")):
                raise ValueError("SIGNAL_ALLOWED_ORIGINS must contain exact origins without paths; production requires HTTPS")
        if self.signal_environment == "production":
            for value in (self.signal_oidc_issuer, self.signal_oidc_jwks_url):
                url = urlsplit(value)
                if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
                    raise ValueError("Production requires HTTPS OIDC issuer and JWKS URLs")
            if not self.signal_oidc_audience.strip():
                raise ValueError("Production requires SIGNAL_OIDC_AUDIENCE")
            if not self.signal_allowed_hosts or any("*" in host for host in self.signal_allowed_hosts):
                raise ValueError("Production requires explicit SIGNAL_ALLOWED_HOSTS without wildcards")
            if self.signal_allowed_hosts == defaults:
                raise ValueError("Set SIGNAL_ALLOWED_HOSTS explicitly for production")
        return self
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.5-flash"
    signal_agent_mode: Literal["auto", "llm", "deterministic"] = "auto"
    signal_llm_timeout_seconds: float = Field(default=15, ge=1, le=25)
    signal_agent_deadline_seconds: float = Field(default=30, ge=5, le=60)
    signal_agent_max_model_calls: int = Field(default=4, ge=2, le=6)
    signal_agent_max_tool_calls: int = Field(default=16, ge=12, le=24)
    signal_seed_sites: int = Field(default=18, ge=6, le=18)
    signal_seed_hours: int = Field(default=24, ge=3, le=24)

    @property
    def key_configured(self):
        key = self.gemini_api_key.get_secret_value().strip()
        return bool(key and not key.startswith(("your-", "replace-", "paste-")))


@lru_cache
def get_settings() -> Settings:
    return Settings()


def agent_status():
    settings = get_settings()
    enabled = settings.signal_agent_mode != "deterministic" and settings.key_configured
    return {"configured_mode": settings.signal_agent_mode, "active_mode": "llm" if enabled else "deterministic",
        "api_key_configured": settings.key_configured, "model": settings.gemini_model if enabled else None,
        "provider": "gemini" if enabled else "local", "max_tool_calls": settings.signal_agent_max_tool_calls,
        "max_model_calls": settings.signal_agent_max_model_calls, "deadline_seconds": settings.signal_agent_deadline_seconds,
        "message": "LLM tool-calling enabled. Connection is verified on investigation." if enabled else
            "Local evidence agent ready. Add GEMINI_API_KEY to backend/.env and restart for Gemini tool calling."}
