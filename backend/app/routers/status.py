"""Estado de la app: diagnóstico de todas las piezas y gasto en IA."""
import json
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from .. import keychain
from ..backups import list_backups
from ..config import DATA_DIR, JOBTRACKER_HOME, VERSION, get_settings
from ..database import get_session
from ..models import AgentRun, CVProfile
from ..services.agent import load_preferences
from ..services.autofill import browser_available
from ..services.secrets import keychain_names, read_env
from ..services.usage import spend_summary

router = APIRouter(prefix="/api/status", tags=["Estado"])
AGENT_EVERY_H = 3


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ago(dt: datetime, now: datetime) -> str:
    mins = int((now - dt).total_seconds() // 60)
    if mins < 60:
        return f"hace {max(mins, 1)} min"
    if mins < 48 * 60:
        return f"hace {mins // 60} h"
    return f"hace {mins // 1440} días"


def _usd(x: float) -> str:
    return f"{x:,.2f} $".replace(",", " ").replace(".", ",")


def check(id_, label, status, detail, action=None):
    return {"id": id_, "label": label, "status": status, "detail": detail, "action": action}


@router.get("/spend")
def spend(db: Session = Depends(get_session)):
    prefs = load_preferences(db)
    s = get_settings()
    return {**spend_summary(db, budget=prefs.monthly_budget_usd), "model": s.llm_model, "fast_model": s.llm_fast_model}


@router.get("/diagnostics")
def diagnostics(db: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    s = get_settings()
    prefs = load_preferences(db)
    checks = []

    # IA
    if s.anthropic_api_key:
        checks.append(check("claude", "Clave de Claude", "ok", "Configurada · pulsa «Probar» en Claves API para verificarla"))
    else:
        checks.append(check("claude", "Clave de Claude", "error", "Falta: sin ella la IA no funciona",
                            {"label": "Añadir clave", "route": "ajustes", "anchor": "claves"}))

    # Dónde están las claves
    env = read_env()
    in_kc = set(keychain_names(env))
    plain = [n for n in ("ANTHROPIC_API_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY") if env.get(n)]
    if not keychain.available():
        checks.append(check("keychain", "Claves protegidas", "off", "En este sistema se guardan en un archivo con permisos solo para ti"))
    elif plain:
        checks.append(check("keychain", "Claves protegidas", "warn",
                            f"{', '.join(plain)} aún en texto plano: pasarán al Llavero al reiniciar la app"))
    else:
        checks.append(check("keychain", "Claves protegidas", "ok",
                            f"En el Llavero de macOS ({len(in_kc)} clave{'s' if len(in_kc) != 1 else ''})" if in_kc else "Sin claves guardadas"))

    # CV
    cv = db.exec(select(CVProfile).order_by(CVProfile.created_at.desc())).first()
    checks.append(check("cv", "Tu CV", "ok", f"{cv.filename} · subido {_ago(_aware(cv.created_at), now)}") if cv else
                  check("cv", "Tu CV", "error", "Sube tu CV para que el agente sepa qué buscar", {"label": "Subir CV", "route": "perfil"}))

    # Agente
    last = db.exec(select(AgentRun).order_by(AgentRun.started_at.desc())).first()
    if not prefs.enabled:
        checks.append(check("agent", "Agente de búsqueda", "off", "Desactivado en Agente", {"label": "Activar", "route": "agente"}))
    elif not last:
        checks.append(check("agent", "Agente de búsqueda", "warn", "Aún no ha buscado: pulsa «Buscar ahora» en la Bandeja",
                            {"label": "Ir a la Bandeja", "route": "bandeja"}))
    else:
        when = _aware(last.finished_at or last.started_at)
        stats = last.stats or {}
        if last.status == "error":
            checks.append(check("agent", "Agente de búsqueda", "error", f"La última búsqueda falló: {last.error}",
                                {"label": "Ver agente", "route": "agente"}))
        elif last.error and "tope de gasto" in last.error:
            checks.append(check("agent", "Agente de búsqueda", "warn", "En pausa: alcanzaste tu tope de gasto en IA de este mes",
                                {"label": "Cambiar tope", "route": "ajustes", "anchor": "gasto"}))
        elif (now - when).total_seconds() > (AGENT_EVERY_H * 2 + 2) * 3600:
            checks.append(check("agent", "Agente de búsqueda", "warn",
                                f"Última búsqueda {_ago(when, now)}: el Mac estuvo apagado o en reposo, o el servicio no está activo"))
        else:
            checks.append(check("agent", "Agente de búsqueda", "ok",
                                f"Última búsqueda {_ago(when, now)} · {stats.get('descubiertas', 0)} ofertas revisadas"))
        failing = {k: v for k, v in (stats.get("fuentes") or {}).items() if isinstance(v, str) and v.startswith("error")}
        total = len(stats.get("fuentes") or {})
        if failing:
            checks.append(check("sources", "Fuentes de ofertas", "warn",
                                f"{len(failing)} de {total} fallaron en la última búsqueda: {', '.join(list(failing)[:4])}",
                                {"label": "Revisar fuentes", "route": "agente"}))
        elif total:
            checks.append(check("sources", "Fuentes de ofertas", "ok", f"Las {total} respondieron en la última búsqueda"))

    # Gmail
    if s.email_mode != "gmail":
        checks.append(check("gmail", "Gmail", "off", "Modo de prueba: conéctalo para leer respuestas y alertas",
                            {"label": "Conectar", "route": "ajustes", "anchor": "gmail"}))
    elif s.gmail_token_file.exists():
        checks.append(check("gmail", "Gmail", "ok", "Conectado"))
    else:
        checks.append(check("gmail", "Gmail", "warn", "Falta autorizar: pulsa «Sincronizar» en Correos", {"label": "Ir a Correos", "route": "correos"}))

    # Navegador para rellenar formularios
    checks.append(check("browser", "Navegador para formularios", "ok", "Disponible") if browser_available() else
                  check("browser", "Navegador para formularios", "warn", "Instala Google Chrome (o descarga Chromium desde la Bandeja al rellenar)"))

    # Copias de seguridad
    db_path = DATA_DIR / "jobtracker.db"
    backups = list_backups(db_path)
    if not backups:
        checks.append(check("backups", "Copias de seguridad", "warn", "Aún no hay ninguna: se hará al reiniciar la app"))
    else:
        age = now - datetime.fromtimestamp(backups[0].stat().st_mtime, timezone.utc)
        checks.append(check("backups", "Copias de seguridad", "ok" if age.days <= 8 else "warn",
                            f"{len(backups)} guardadas · la última {_ago(now - age, now)}"))

    # Actualizaciones
    state = None
    if JOBTRACKER_HOME and (JOBTRACKER_HOME / "state.json").exists():
        try:
            state = json.loads((JOBTRACKER_HOME / "state.json").read_text())
        except (OSError, ValueError):
            state = None
    if not state:
        checks.append(check("updates", "Actualizaciones", "off", f"Versión {VERSION} (instalación de desarrollo)"))
    elif state.get("available"):
        checks.append(check("updates", "Actualizaciones", "warn", f"Hay una versión nueva: {state['available'].get('version')}"))
    else:
        last_check = state.get("last_check")
        detail = f"Versión {VERSION} al día" + (f" · comprobado {_ago(datetime.fromisoformat(last_check), now)}" if last_check else "")
        if state.get("auto_update") is False:
            detail += " · actualización automática desactivada"
        checks.append(check("updates", "Actualizaciones", "ok", detail))

    # Gasto
    sp = spend_summary(db, now, prefs.monthly_budget_usd)
    if not prefs.monthly_budget_usd:
        checks.append(check("spend", "Gasto en IA", "ok", f"{_usd(sp['month_usd'])} este mes · sin tope (puedes poner uno abajo)"))
    else:
        status = "error" if sp["over_budget"] else "warn" if sp["budget_ratio"] >= 0.8 else "ok"
        checks.append(check("spend", "Gasto en IA", status, f"{_usd(sp['month_usd'])} de {_usd(prefs.monthly_budget_usd)} este mes"))

    # Disco
    free = shutil.disk_usage(DATA_DIR if DATA_DIR.exists() else DATA_DIR.parent).free
    size = db_path.stat().st_size if db_path.exists() else 0
    checks.append(check("disk", "Espacio en disco", "ok" if free > 1_000_000_000 else "warn",
                        f"{free / 1e9:.1f} GB libres · tus datos ocupan {size / 1e6:.1f} MB".replace(".", ",")))

    order = {"error": 0, "warn": 1, "ok": 2, "off": 3}
    summary = {k: sum(c["status"] == k for c in checks) for k in order}
    return {"checks": sorted(checks, key=lambda c: order[c["status"]]), "summary": summary, "version": VERSION,
            "checked_at": now.isoformat()}
