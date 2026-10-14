from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..config import get_settings
from ..database import get_session
from ..models import AgentRun, CVProfile, Job, PipelineStatus
from ..schemas import CalibrationIn, CVExtraction, IdealProfile, QueriesProposal, SearchPreferences, TraceIn, VoteIn
from ..services import targeting
from ..services.agent import _ingest, autoconfigure_preferences, load_preferences, save_preferences
from ..services.llm import LLMClient, LLMError, get_llm

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
    votes = targeting.job_votes(db, [j.id for j in jobs])
    return [
        {"id": j.id, "title": j.title, "company": j.company, "location": j.location, "source": j.source,
         "vote": votes.get(j.id),
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


# ── Afinar la búsqueda (0.9.0) ──────────────────────────────────


def _latest_cv(db: Session) -> CVExtraction:
    cv = db.exec(select(CVProfile).order_by(CVProfile.created_at.desc())).first()
    if not cv:
        raise HTTPException(409, "Sube primero tu CV")
    return CVExtraction.model_validate(cv.profile)


@router.post("/jobs/{job_id}/vote")
def vote(job_id: int, payload: VoteIn, db: Session = Depends(get_session)):
    """👍 «más como esta» / 👎 «menos como esta», en cualquier oferta (también las descartadas)."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Oferta no encontrada")
    targeting.record_vote(db, job, payload.vote, payload.reason)
    low = job.pipeline_status in (PipelineStatus.LOW_SCORE.value, PipelineStatus.FILTERED.value)
    return {"vote": payload.vote, "can_prepare": payload.vote == "like" and low}


def _card(j: Job) -> dict:
    t = j.triage or {}
    return {"id": j.id, "title": j.title, "company": j.company, "location": j.location, "source": j.source,
            "url": j.source_url or j.apply_url, "salary": t.get("salary"), "remote": t.get("remote"),
            "score": t.get("match_score") or t.get("score"), "status": j.pipeline_status,
            "snippet": (j.raw_text or "")[:900]}


@router.get("/calibration")
def calibration_sample(db: Session = Depends(get_session), client=Depends(get_http_client)):
    """15 ofertas variadas para votar. Si aún hay pocas, se traen de tus fuentes (sin gastar IA)."""
    jobs = targeting.calibration_sample(db)
    if len(jobs) < 8:
        from ..services.sources import collect

        prefs = load_preferences(db)
        raws, _ = collect(client, prefs.sources, None, country=prefs.country)
        stats = {"duplicadas": 0, "filtradas": 0, "nuevas": 0}
        for raw in raws[:150]:
            _ingest(db, raw, prefs, stats)
        db.commit()
        jobs = targeting.calibration_sample(db)
    return {"jobs": [_card(j) for j in jobs]}


@router.post("/calibration")
def calibrate(payload: CalibrationIn, db: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)):
    """Guarda los votos y propone el perfil ideal y las búsquedas (no se aplican hasta que confirmes)."""
    voted = []
    for v in payload.votes:
        job = db.get(Job, v.job_id)
        if not job:
            continue
        if v.vote != "skip":
            targeting.record_vote(db, job, v.vote, v.reason)
        voted.append((job, v.vote, v.reason))
    if not any(v != "skip" for _, v, _ in voted):
        raise HTTPException(422, "Vota al menos una oferta con 👍 o 👎")
    prefs = load_preferences(db)
    try:
        out = targeting.calibrate(llm, get_settings(), _latest_cv(db), prefs, voted, payload.notes)
    except LLMError as e:
        raise HTTPException(502, str(e)) from e
    return {**out.model_dump(), "ideal": targeting.merge_ideal(prefs.ideal, out.ideal).model_dump(),
            "before": prefs.ideal.model_dump()}


class TargetingApply(BaseModel):
    ideal: IdealProfile | None = None
    queries: QueriesProposal | None = None


@router.post("/targeting/apply", response_model=SearchPreferences)
def apply_targeting(payload: TargetingApply, db: Session = Depends(get_session)):
    prefs = load_preferences(db)
    if payload.ideal is not None:
        prefs.ideal = payload.ideal
    if payload.queries is not None:
        prefs = targeting.apply_queries(prefs, payload.queries)
    return save_preferences(db, prefs)


@router.post("/queries/suggest", response_model=QueriesProposal)
def suggest_queries(db: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)):
    try:
        return targeting.suggest_queries(llm, get_settings(), _latest_cv(db), load_preferences(db))
    except LLMError as e:
        raise HTTPException(502, str(e)) from e


@router.post("/trace")
def trace_job(payload: TraceIn, db: Session = Depends(get_session), llm: LLMClient = Depends(get_llm),
              client=Depends(get_http_client)):
    """«¿Por qué no vi esta oferta?»: en qué paso se quedó, o qué habría pasado."""
    from ..services.trace import trace

    if not (payload.url or payload.text):
        raise HTTPException(422, "Pega el enlace o el texto de la oferta")
    try:
        return trace(db, llm, client, load_preferences(db), payload.url, payload.text)
    except LLMError as e:
        raise HTTPException(502, str(e)) from e


@router.get("/tuning")
def tuning(db: Session = Depends(get_session)):
    """Sugerencias para afinar la búsqueda (calculadas con tus datos, sin IA)."""
    from ..services.tuning import suggestions

    return {"suggestions": suggestions(db, load_preferences(db))}


class TuningApply(BaseModel):
    id: str


@router.post("/tuning/apply", response_model=SearchPreferences)
def tuning_apply(payload: TuningApply, db: Session = Depends(get_session)):
    from ..services.tuning import apply, suggestions

    prefs = load_preferences(db)
    s = next((x for x in suggestions(db, prefs) if x["id"] == payload.id), None)
    if not s:
        raise HTTPException(404, "Esa sugerencia ya no aplica")
    try:
        return save_preferences(db, apply(prefs, s))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
