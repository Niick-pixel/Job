"""Rellenar formularios de candidatura en el navegador (la app nunca pulsa «Enviar»)."""
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session

from ..config import DATA_DIR
from ..database import get_session
from ..models import ApplicationPackage, Job
from ..services.autofill import WORK, browser_available, read_status, write_status

router = APIRouter(tags=["Formularios"])
BACKEND_DIR = Path(__file__).resolve().parents[2]
_procs: dict[int, subprocess.Popen] = {}
_install: dict = {}


class AutofillIn(BaseModel):
    cover_letter: str | None = None  # la carta tal y como la tengas editada en la Bandeja


@router.post("/api/packages/{pkg_id}/autofill")
def start(pkg_id: int, payload: AutofillIn = Body(default_factory=AutofillIn), db: Session = Depends(get_session)):
    pkg = db.get(ApplicationPackage, pkg_id)
    if not pkg:
        raise HTTPException(404, "Candidatura no encontrada")
    if payload.cover_letter is not None and payload.cover_letter != pkg.cover_letter:
        pkg.cover_letter = payload.cover_letter
        db.add(pkg)
        db.commit()
    job = db.get(Job, pkg.job_id)
    if not (job.apply_url or job.source_url):
        raise HTTPException(409, "La oferta no tiene enlace al formulario")
    if any(p.poll() is None for p in _procs.values()):
        raise HTTPException(409, "Ya hay un formulario abierto: ciérralo antes de abrir otro")
    if not browser_available():
        raise HTTPException(412, "no_browser")
    WORK.mkdir(parents=True, exist_ok=True)
    write_status(pkg_id, state="starting", pid=None, submitted=False, error=None, filled=[], missing=[],
                 message="Abriendo el navegador…")
    log = open(WORK / f"{pkg_id}.log", "w")  # noqa: SIM115  (lo hereda el proceso hijo)
    proc = subprocess.Popen([sys.executable, "-m", "app.autofill", str(pkg_id)], cwd=BACKEND_DIR,
                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    _procs[pkg_id] = proc
    return write_status(pkg_id, pid=proc.pid)


@router.get("/api/packages/{pkg_id}/autofill")
def status(pkg_id: int):
    st = read_status(pkg_id)
    if not st:
        raise HTTPException(404, "Sin formulario abierto para esta candidatura")
    proc = _procs.get(pkg_id)
    if proc and proc.poll() is not None and st.get("state") in ("starting", "filling", "ready"):
        st["state"] = "closed"
    return st


@router.get("/api/packages/{pkg_id}/autofill.png")
def screenshot(pkg_id: int):
    path = WORK / f"{pkg_id}.png"
    if not path.exists():
        raise HTTPException(404, "Sin captura")
    return FileResponse(path, media_type="image/png")


@router.get("/api/autofill/browser")
def browser():
    proc = _install.get("proc")
    installing = bool(proc and proc.poll() is None)
    return {"available": browser_available(), "installing": installing,
            "failed": bool(proc and proc.poll() not in (None, 0))}


@router.post("/api/autofill/browser")
def install_browser():
    """Descarga Chromium para Playwright (≈ 150 MB) si no tienes Chrome ni Edge."""
    if _install.get("proc") and _install["proc"].poll() is None:
        return browser()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log = open(DATA_DIR / "browser-install.log", "w")  # noqa: SIM115
    _install["proc"] = subprocess.Popen([sys.executable, "-m", "playwright", "install", "chromium"],
                                        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    return browser()
