"""Configuración central leída desde variables de entorno / .env."""
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
VERSION = (ROOT_DIR / "VERSION").read_text().strip()

# Instalación OTA: el código vive en versions/<x.y.z>/ y los datos/config fuera,
# para que sobrevivan a las actualizaciones. En desarrollo todo queda en el repo.
JOBTRACKER_HOME = Path(os.environ["JOBTRACKER_HOME"]) if os.getenv("JOBTRACKER_HOME") else None
DATA_DIR = Path(os.getenv("JOBTRACKER_DATA_DIR", ROOT_DIR / "data"))
_ENV_FILES = (ROOT_DIR / ".env", JOBTRACKER_HOME / ".env") if JOBTRACKER_HOME else ROOT_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILES, extra="ignore")

    anthropic_api_key: str | None = None
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"
    # Modelo rápido y barato para la criba masiva de ofertas
    llm_fast_model: str = "claude-haiku-5-5"

    # Fuentes de ofertas con credenciales (opcionales)
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None

    database_url: str = f"sqlite:///{DATA_DIR / 'jobtracker.db'}"
    upload_dir: Path = DATA_DIR / "uploads"
    generated_dir: Path = DATA_DIR / "generated"
    match_llm_weight: float = 0.7

    email_mode: str = "simulated"  # simulated | gmail
    gmail_credentials_file: Path = DATA_DIR / "gmail_credentials.json"
    gmail_token_file: Path = DATA_DIR / "gmail_token.json"
    gmail_query: str = "newer_than:14d"
    sample_emails_file: Path = ROOT_DIR / "data" / "samples" / "sample_emails.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
