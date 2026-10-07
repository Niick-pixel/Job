"""Configuración central leída desde variables de entorno / .env."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    anthropic_api_key: str | None = None
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"

    database_url: str = f"sqlite:///{ROOT_DIR / 'data' / 'jobtracker.db'}"
    upload_dir: Path = ROOT_DIR / "data" / "uploads"
    match_llm_weight: float = 0.7

    email_mode: str = "simulated"  # simulated | gmail
    gmail_credentials_file: Path = ROOT_DIR / "data" / "gmail_credentials.json"
    gmail_token_file: Path = ROOT_DIR / "data" / "gmail_token.json"
    gmail_query: str = "newer_than:14d"
    sample_emails_file: Path = ROOT_DIR / "data" / "samples" / "sample_emails.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
