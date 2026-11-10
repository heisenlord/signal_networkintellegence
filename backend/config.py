"""Load backend configuration before database/client initialization."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
# Process environment wins; backend/.env can override defaults in the root .env.
load_dotenv(ROOT / "backend/.env", override=False)
load_dotenv(ROOT / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
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
