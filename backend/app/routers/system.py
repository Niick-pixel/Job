"""Versión instalada, actualizaciones OTA (comprobar, instalar, novedades) y tus datos."""
import fcntl
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..backups import list_backups, make_backup
from ..config import DATA_DIR, JOBTRACKER_HOME, ROOT_DIR, VERSION

router = APIRouter(prefix="/api/system", tags=["Sistema"])
UPDATER_LABEL = "com.jobtrackerai.updater"
UPDATER_INTERVAL = 3600  # debe coincidir con CHECK_INTERVAL_SECONDS del instalador


def _state() -> dict:
    if not JOBTRACKER_HOME:
        return {}
    try:
        return json.loads((JOBTRACKER_HOME / "state.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _ctl() -> list[str]:
    """El CLI del instalador de la versión instalada (solo usa la biblioteca estándar)."""
    return [sys.executable, str(JOBTRACKER_HOME / "current" / "installer" / "jobtracker.py")]


def _require_installed() -> None:
    if not JOBTRACKER_HOME or not (JOBTRACKER_HOME / "current").exists():
        raise HTTPException(409, "Solo disponible en la app instalada (no en modo desarrollo)")


def update_running() -> bool:
    """¿Hay una instalación/actualización en curso? (el actualizador tiene el candado)."""
    if not JOBTRACKER_HOME:
        return False
    try:
        with open(JOBTRACKER_HOME / ".lock", "a") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(fh, fcntl.LOCK_UN)
    except OSError:
        return False
    return False


@router.get("/version")
def version():
    state = _state()
    available = state.get("available") or {}
    return {
        "version": VERSION,
        "installed": JOBTRACKER_HOME is not None,
        "update_available": bool(available),
        "latest": available.get("version"),
        "notes": available.get("notes"),
        "auto_update": state.get("auto_update"),
        "last_check": state.get("last_check"),
        "rolled_back_from": state.get("rolled_back_from"),
        "previous": state.get("previous"),
        "updating": update_running(),
    }


@router.post("/check")
def check_now():
    """Comprueba ahora si hay una versión nueva (descarga y verifica el manifiesto firmado)."""
    _require_installed()
    if update_running():
        return {**version(), "message": "Hay una actualización en curso"}
    env = {**os.environ, "JOBTRACKER_HOME": str(JOBTRACKER_HOME)}
    r = subprocess.run([*_ctl(), "check"], capture_output=True, text=True, timeout=90, env=env)
    if r.returncode != 0:
        raise HTTPException(502, (r.stderr or r.stdout).strip().lstrip("❌ ") or "No se pudo comprobar")
    return version()


@router.post("/update", status_code=202)
def trigger_update():
    """Pide al agente de launchd que actualice ya (corre fuera de este proceso,
    porque la actualización reinicia el propio backend)."""
    if not JOBTRACKER_HOME or sys.platform != "darwin":
        raise HTTPException(409, "Solo disponible en una instalación de macOS (no en modo desarrollo)")
    (JOBTRACKER_HOME / "force_update").touch()
    r = subprocess.run(["launchctl", "kickstart", f"gui/{os.getuid()}/{UPDATER_LABEL}"], capture_output=True, text=True)
    if r.returncode != 0:
        raise HTTPException(500, f"No se pudo lanzar el actualizador: {r.stderr.strip()}")
    return {"status": "scheduled"}


class Toggle(BaseModel):
    enabled: bool


@router.post("/auto-update")
def set_auto_update(payload: Toggle):
    _require_installed()
    env = {**os.environ, "JOBTRACKER_HOME": str(JOBTRACKER_HOME)}
    r = subprocess.run([*_ctl(), "config", "auto-update", "on" if payload.enabled else "off"],
                       capture_output=True, text=True, timeout=30, env=env)
    if r.returncode != 0:
        raise HTTPException(502, (r.stderr or r.stdout).strip())
    return version()


# ── Novedades ───────────────────────────────────────────────────


def changelog_sections(text: str) -> list[dict]:
    """Secciones «## x.y.z …» del CHANGELOG."""
    out = []
    for m in re.finditer(r"^## (\d+\.\d+\.\d+)([^\n]*)\n(.*?)(?=^## \d|\Z)", text, re.M | re.S):
        out.append({"version": m.group(1), "title": m.group(2).strip(" —-"), "body": m.group(3).strip()})
    return out


@router.get("/changelog")
def changelog(since: str | None = None, limit: int = 3):
    """Novedades de la versión instalada (y de las anteriores hasta «since», sin incluirla)."""
    try:
        sections = changelog_sections((ROOT_DIR / "CHANGELOG.md").read_text(encoding="utf-8"))
    except OSError:
        sections = []
    if since:
        cut = next((i for i, s in enumerate(sections) if s["version"] == since), None)
        sections = sections[:cut] if cut is not None else sections[:1]
    return {"version": VERSION, "sections": sections[:limit]}


# ── Tus datos ───────────────────────────────────────────────────


@router.get("/data")
def data_info():
    db_path = DATA_DIR / "jobtracker.db"
    backups = [{"name": b.name, "size_kb": b.stat().st_size // 1024,
                "created_at": datetime.fromtimestamp(b.stat().st_mtime, timezone.utc).isoformat()}
               for b in list_backups(db_path)]
    return {"data_dir": str(DATA_DIR), "db_size_kb": db_path.stat().st_size // 1024 if db_path.exists() else 0,
            "backups": backups, "can_reveal": sys.platform == "darwin"}


@router.post("/backups")
def backup_now():
    made = make_backup(DATA_DIR / "jobtracker.db", "manual")
    if not made:
        raise HTTPException(409, "Aún no hay datos que copiar")
    return data_info()


@router.post("/reveal")
def reveal_data():
    """Abre la carpeta de datos en el Finder."""
    if sys.platform != "darwin":
        raise HTTPException(409, "Solo en macOS")
    subprocess.run(["open", str(DATA_DIR)], check=False)
    return {"opened": True}


# ── Al arrancar: recargar el actualizador si cambió su intervalo ──


def maybe_reload_updater(delay: float = 90) -> None:
    """Las versiones < 0.9.1 comprobaban cada 6 h; launchd no relee el plist hasta recargarlo. Se hace desde
    aquí (no desde el actualizador, que se mataría a sí mismo) y nunca con una actualización en curso."""
    if sys.platform != "darwin" or not JOBTRACKER_HOME:
        return
    marker = JOBTRACKER_HOME / ".updater_interval"
    if marker.exists() and marker.read_text().strip() == str(UPDATER_INTERVAL):
        return

    def run():
        time.sleep(delay)  # deja terminar la actualización que acaba de reiniciar el backend
        if update_running():
            return
        env = {**os.environ, "JOBTRACKER_HOME": str(JOBTRACKER_HOME)}
        subprocess.run([*_ctl(), "reload-updater"], capture_output=True, timeout=60, env=env)

    threading.Thread(target=run, daemon=True).start()
