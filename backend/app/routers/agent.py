from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..database import get_session
from ..models import AgentRun, Job, PipelineStatus
from ..schemas import SearchPreferences
from ..config import get_settings
from ..models import CVProfile
from ..schemas import CVExtraction
from ..services.agent import autoconfigure_preferences, load_preferences, save_preferences
from ..services.llm import LLMError
from ..services.llm import LLMClient, get_llm

router = APIRouter(prefix="/api/agent", tags=["Agente"])


def get_http_client():
    """Cliente HTTP para consultar las APIs públicas (sustituible en los tests)."""
    import httpx

    with httpx.Client(follow_redirects=True) as client:
        yield client


class DiscoverIn(BaseModel):
    companies: list[str]


@router.post("/discover")
def discover_companies(payload: DiscoverIn, client=Depends(get_http_client)):
    """Busca en qué ATS (Greenhouse, Lever, Ashby) publica cada empresa. El usuario confirma después."""
    from ..services.discovery import MAX_COMPANIES, discover

    names = [c for c in payload.companies if c.strip()]
    if not names:
        raise HTTPException(422, "Escribe al menos una empresa")
    if len(names) > MAX_COMPANIES:
        raise HTTPException(422, f"Como máximo {MAX_COMPANIES} empresas a la vez")
    found = discover(client, names)
    missing = sorted({n.strip() for n in names} - {b["query"] for b in found})
    return {"found": found, "missing": missing}


@router.get("/preferences", response_model=SearchPreferences)
def get_preferences(db: Session = Depends(get_session)):
    return load_preferences(db)


@router.put("/preferences", response_model=SearchPreferences)
def put_preferences(prefs: SearchPreferences, db: Session = Depends(get_session)):
    return save_preferences(db, prefs)


@router.post("/preferences/auto", response_model=SearchPreferences)
def auto_preferences(db: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)):
    """Rehace ubicación, búsquedas y exclusiones a partir del CV más reciente (conserva lo demás)."""
    cv = db.exec(select(CVProfile).order_by(CVProfile.created_at.desc())).first()
    if not cv:
        raise HTTPException(409, "Sube primero tu CV")
    try:
        prefs = autoconfigure_preferences(llm, get_settings(), CVExtraction.model_validate(cv.profile),
                                          base=load_preferences(db))
    except LLMError as e:
        raise HTTPException(502, str(e)) from e
    return save_preferences(db, prefs)


def _run_in_background(llm: LLMClient) -> None:
    from ..agent import AgentBusy, run_once

    try:
        run_once("manual", llm=llm)
    except AgentBusy:
        pass


@router.post("/run", status_code=202)
def run_now(background: BackgroundTasks, llm: LLMClient = Depends(get_llm)):
    from ..agent import AgentBusy, agent_lock

    try:  # el candado de fichero es la fuente de verdad (sobrevive a cierres inesperados)
        with agent_lock():
            pass
    except AgentBusy as e:
        raise HTTPException(409, str(e)) from e
    background.add_task(_run_in_background, llm)
    return {"status": "scheduled"}


@router.get("/runs", response_model=list[AgentRun])
def list_runs(limit: int = 10, db: Session = Depends(get_session)):
    return db.exec(select(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit)).all()


@router.get("/jobs")
def pipeline_jobs(status: str | None = None, limit: int = 100, db: Session = Depends(get_session)):
    """Ofertas descubiertas por el agente, con su estado en el embudo y el motivo."""
    q = select(Job).where(Job.pipeline_status != PipelineStatus.MANUAL.value)
    if status:
        q = q.where(Job.pipeline_status == status)
    jobs = db.exec(q.order_by(Job.created_at.desc()).limit(limit)).all()
    return [
        {"id": j.id, "title": j.title, "company": j.company, "location": j.location, "source": j.source,
         "status": j.pipeline_status, "url": j.source_url, "posted_date": j.posted_date,
         "score": (j.triage or {}).get("match_score") or (j.triage or {}).get("score"),
         "reason": (j.triage or {}).get("filter_reason") or (j.triage or {}).get("reason"),
         "urgency": (j.urgency or {}).get("level")}
        for j in jobs
    ]


@router.get("/digest", tags=["Resumen"])
def digest(db: Session = Depends(get_session)):
    """Lo que merece atención hoy (tarjeta «Hoy» de la Bandeja)."""
    from ..services.digest import build_digest

    return build_digest(db)
