"""Ajustes: claves API, modelo de IA, apariencia y conexión con Gmail."""
import json
import os
from pathlib import Path

import anthropic
import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..config import DATA_DIR, get_settings
from ..services.secrets import NAME_RE, env_path, mask, read_env, write_env

router = APIRouter(prefix="/api/settings", tags=["Ajustes"])

# Claves conocidas: la interfaz explica para qué sirve cada una y cómo conseguirla
KNOWN_KEYS = [
    {
        "name": "ANTHROPIC_API_KEY", "label": "Claude (Anthropic)", "group": "Inteligencia artificial",
        "required": True, "placeholder": "sk-ant-…", "testable": True,
        "description": "Analiza tu CV y las ofertas, puntúa, redacta cartas y clasifica correos. Imprescindible.",
        "url": "https://console.anthropic.com/settings/keys",
        "steps": ["Crea una cuenta en console.anthropic.com", "Añade un método de pago en Billing (pago por uso)",
                  "Settings → API Keys → Create Key", "Copia la clave (empieza por sk-ant-) y pégala aquí"],
    },
    {
        "name": "ADZUNA_APP_ID", "label": "Adzuna · App ID", "group": "Fuentes de ofertas",
        "required": False, "placeholder": "p. ej. 1a2b3c4d", "testable": True,
        "description": "Busca ofertas en Adzuna (España y otros 15 países). Gratuita.",
        "url": "https://developer.adzuna.com/signup",
        "steps": ["Regístrate en developer.adzuna.com", "Entra en Dashboard → API Access Details",
                  "Copia el Application ID aquí y la Application Key en el campo siguiente"],
    },
    {
        "name": "ADZUNA_APP_KEY", "label": "Adzuna · App Key", "group": "Fuentes de ofertas",
        "required": False, "placeholder": "32 caracteres", "testable": True,
        "description": "Segunda mitad de las credenciales de Adzuna.",
        "url": "https://developer.adzuna.com/signup", "steps": [],
    },
]
KNOWN = {k["name"] for k in KNOWN_KEYS}
# Variables de configuración que no son secretos (se gestionan en otras secciones)
CONFIG_VARS = {"LLM_MODEL", "LLM_FAST_MODEL", "LLM_EFFORT", "EMAIL_MODE", "DATABASE_URL", "UPLOAD_DIR",
               "MATCH_LLM_WEIGHT", "BACKEND_URL", "GMAIL_CREDENTIALS_FILE", "GMAIL_TOKEN_FILE", "GMAIL_QUERY"}

MODELS = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "note": "El más capaz · recomendado"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "note": "Equilibrio entre calidad y coste"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "note": "El más rápido y barato"},
]
EFFORTS = ["low", "medium", "high", "xhigh", "max"]
THEMES = ["auto", "porcelana", "grafito", "oceano", "bosque", "atardecer", "lavanda", "medianoche", "arena"]


def _current(name: str) -> str | None:
    return os.environ.get(name) or read_env().get(name)


# ── Claves API ──────────────────────────────────────────────────


class KeyIn(BaseModel):
    name: str
    value: str


@router.get("/keys")
def list_keys():
    env = read_env()
    keys = [{**k, "configured": bool(_current(k["name"])), "preview": mask(_current(k["name"]))} for k in KNOWN_KEYS]
    custom = [{"name": n, "preview": mask(v), "configured": bool(v)}
              for n, v in sorted(env.items()) if n not in KNOWN and n not in CONFIG_VARS]
    return {"path": str(env_path()), "keys": keys, "custom": custom}


@router.put("/keys")
def save_key(payload: KeyIn):
    name, value = payload.name.strip().upper(), payload.value.strip()
    if not NAME_RE.match(name):
        raise HTTPException(422, "Nombre inválido: usa MAYÚSCULAS, números y _ (p. ej. MI_SERVICIO_API_KEY)")
    if name in CONFIG_VARS:
        raise HTTPException(422, "Esa variable se configura en otra sección de Ajustes")
    if not value:
        raise HTTPException(422, "La clave está vacía")
    try:
        write_env({name: value})
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"name": name, "configured": True, "preview": mask(value)}


@router.delete("/keys/{name}", status_code=204)
def delete_key(name: str):
    if not NAME_RE.match(name) or name in CONFIG_VARS:
        raise HTTPException(422, "Nombre inválido")
    write_env({name: None})


@router.post("/keys/{name}/test")
def test_key(name: str):
    """Comprueba que una clave funciona haciendo una llamada mínima y gratuita."""
    if name == "ANTHROPIC_API_KEY":
        key = _current(name)
        if not key:
            raise HTTPException(409, "Primero guarda la clave")
        try:
            model = anthropic.Anthropic(api_key=key, max_retries=0, timeout=15).models.retrieve(get_settings().llm_model)
        except anthropic.AuthenticationError:
            return {"ok": False, "message": "La clave no es válida o ha sido revocada"}
        except anthropic.PermissionDeniedError:
            return {"ok": False, "message": "La clave no tiene permiso para usar la API"}
        except anthropic.NotFoundError:
            return {"ok": False, "message": f"La clave funciona, pero no tiene acceso a {get_settings().llm_model}"}
        except anthropic.APIConnectionError:
            return {"ok": False, "message": "No hay conexión con la API de Anthropic"}
        except anthropic.APIStatusError as e:
            return {"ok": False, "message": f"Error {e.status_code} de la API"}
        return {"ok": True, "message": f"Funciona · {model.display_name}"}

    if name in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
        app_id, app_key = _current("ADZUNA_APP_ID"), _current("ADZUNA_APP_KEY")
        if not (app_id and app_key):
            return {"ok": False, "message": "Faltan el App ID o la App Key"}
        try:
            r = httpx.get("https://api.adzuna.com/v1/api/jobs/es/search/1", timeout=15,
                          params={"app_id": app_id, "app_key": app_key, "results_per_page": 1, "what": "developer"})
        except httpx.HTTPError:
            return {"ok": False, "message": "No hay conexión con Adzuna"}
        if r.status_code in (401, 403):
            return {"ok": False, "message": "Credenciales de Adzuna no válidas"}
        if r.status_code != 200:
            return {"ok": False, "message": f"Adzuna respondió {r.status_code}"}
        return {"ok": True, "message": f"Funciona · {r.json().get('count', 0):,} ofertas disponibles".replace(",", ".")}

    return {"ok": None, "message": "No hay prueba automática para esta clave"}


# ── Modelo de IA ────────────────────────────────────────────────


class AIConfig(BaseModel):
    model: str
    fast_model: str
    effort: str


@router.get("/ai")
def get_ai():
    s = get_settings()
    return {"model": s.llm_model, "fast_model": s.llm_fast_model, "effort": s.llm_effort,
            "models": MODELS, "efforts": EFFORTS}


@router.put("/ai")
def put_ai(cfg: AIConfig):
    ids = {m["id"] for m in MODELS}
    if cfg.model not in ids or cfg.fast_model not in ids or cfg.effort not in EFFORTS:
        raise HTTPException(422, "Modelo o esfuerzo no válidos")
    write_env({"LLM_MODEL": cfg.model, "LLM_FAST_MODEL": cfg.fast_model, "LLM_EFFORT": cfg.effort})
    return get_ai()


# ── Apariencia ──────────────────────────────────────────────────


class UIConfig(BaseModel):
    theme: str = "auto"
    reduce_motion: bool = False


def _ui_file() -> Path:
    return DATA_DIR / "ui.json"


def load_ui() -> UIConfig:
    try:
        return UIConfig.model_validate_json(_ui_file().read_text())
    except (FileNotFoundError, ValueError):
        return UIConfig()


@router.get("/ui", response_model=UIConfig)
def get_ui():
    return load_ui()


@router.put("/ui", response_model=UIConfig)
def put_ui(cfg: UIConfig):
    if cfg.theme not in THEMES:
        raise HTTPException(422, "Tema desconocido")
    _ui_file().parent.mkdir(parents=True, exist_ok=True)
    _ui_file().write_text(cfg.model_dump_json())
    return cfg


# ── Gmail ───────────────────────────────────────────────────────


@router.get("/gmail")
def gmail_status():
    s = get_settings()
    return {"mode": s.email_mode, "credentials": s.gmail_credentials_file.exists(),
            "connected": s.gmail_token_file.exists()}


@router.post("/gmail/credentials")
async def upload_gmail_credentials(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        data = json.loads(raw)
    except ValueError:
        raise HTTPException(422, "No es un JSON válido") from None
    if "installed" not in data:
        raise HTTPException(422, "Debe ser un cliente OAuth de tipo «Aplicación de escritorio» (clave «installed»)")
    s = get_settings()
    s.gmail_credentials_file.parent.mkdir(parents=True, exist_ok=True)
    s.gmail_credentials_file.write_bytes(raw)
    s.gmail_credentials_file.chmod(0o600)
    write_env({"EMAIL_MODE": "gmail"})
    return gmail_status()


@router.delete("/gmail")
def disconnect_gmail():
    s = get_settings()
    s.gmail_token_file.unlink(missing_ok=True)
    write_env({"EMAIL_MODE": "simulated"})
    return gmail_status()
