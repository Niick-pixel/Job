"""Versión instalada y disparador de actualizaciones OTA."""
import json
import os
import subprocess
import sys

from fastapi import APIRouter, HTTPException

from ..config import JOBTRACKER_HOME, VERSION

router = APIRouter(prefix="/api/system", tags=["Sistema"])
UPDATER_LABEL = "com.jobtrackerai.updater"


def _state() -> dict:
    if not JOBTRACKER_HOME:
        return {}
    try:
        return json.loads((JOBTRACKER_HOME / "state.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


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
    }


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
