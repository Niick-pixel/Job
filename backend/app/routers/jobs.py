from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..config import get_settings
from ..database import get_session
from ..models import Application, CVProfile, Job, MatchResult, PipelineStatus
from ..schemas import CVExtraction, JobCreate, JobExtraction, JobRead, MatchRead, OptimizationResult
from ..services.job_ingest import JobFetchError, analyze_job, fetch_job_text
from ..services.llm import LLMClient, LLMError, get_llm
from ..services.matcher import evaluate_match
from ..services.optimizer import optimize_application
from ..services.urgency import assess_urgency

router = APIRouter(prefix="/api/jobs", tags=["Ofertas"])


def _job_read(job: Job) -> JobRead:
    return JobRead.model_validate(job, from_attributes=True)


def _load(db: Session, job_id: int, cv_id: int) -> tuple[Job, CVProfile]:
    job, cv = db.get(Job, job_id), db.get(CVProfile, cv_id)
    if not job:
        raise HTTPException(404, "Oferta no encontrada")
    if not cv:
        raise HTTPException(404, "CV no encontrado")
    return job, cv


@router.post("", response_model=JobRead)
def create_job(payload: JobCreate, db: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)):
    if not payload.text and not payload.url:
        raise HTTPException(422, "Envía el texto de la oferta o un enlace")
    try:
        text = payload.text or fetch_job_text(payload.url)  # type: ignore[arg-type]
        details = analyze_job(llm, text)
    except JobFetchError as e:
        raise HTTPException(422, str(e)) from e
    except LLMError as e:
        raise HTTPException(502, str(e)) from e

    # Lo que indique el usuario manda sobre lo que deduzca la IA
    posted = payload.posted_date or details.posted_date
    applicants = payload.applicants_count if payload.applicants_count is not None else details.applicants_count
    urgency = assess_urgency(posted, applicants)

    job = Job(
        title=details.title,
        company=details.company,
        location=details.location,
        source_url=payload.url,
        raw_text=text,
        posted_date=posted,
        applicants_count=applicants,
        details=details.model_dump(mode="json"),
        urgency=urgency.model_dump(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    # Toda oferta nueva entra al Kanban en "Por aplicar"
    db.add(Application(job_id=job.id))
    db.commit()
    return _job_read(job)


HIDDEN = (PipelineStatus.FILTERED.value, PipelineStatus.LOW_SCORE.value, PipelineStatus.DISCARDED.value)


@router.get("", response_model=list[JobRead])
def list_jobs(db: Session = Depends(get_session)):
    """Ofertas útiles: las tuyas y las del agente que siguen vivas (las descartadas, en /api/agent/jobs)."""
    q = select(Job).where(Job.pipeline_status.not_in(HIDDEN)).order_by(Job.created_at.desc())
    return [_job_read(j) for j in db.exec(q).all()]


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: int, db: Session = Depends(get_session)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Oferta no encontrada")
    return _job_read(job)


@router.post("/{job_id}/match", response_model=MatchRead)
def match_job(job_id: int, cv_id: int, db: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)):
    job, cv = _load(db, job_id, cv_id)
    try:
        score, coverage, analysis = evaluate_match(
            llm,
            CVExtraction.model_validate(cv.profile),
            JobExtraction.model_validate(job.details),
            cv.raw_text,
            llm_weight=get_settings().match_llm_weight,
        )
    except LLMError as e:
        raise HTTPException(502, str(e)) from e

    result = MatchResult(
        cv_id=cv.id,
        job_id=job.id,
        score=score,
        result={"llm_score": analysis.score, "skills_coverage": coverage, "analysis": analysis.model_dump()},
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return MatchRead(
        id=result.id, cv_id=cv.id, job_id=job.id, score=score,
        llm_score=analysis.score, skills_coverage=coverage, analysis=analysis,
    )


@router.post("/{job_id}/optimize", response_model=OptimizationResult)
def optimize(job_id: int, cv_id: int, db: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)):
    job, cv = _load(db, job_id, cv_id)
    last_match = db.exec(
        select(MatchResult)
        .where(MatchResult.job_id == job_id, MatchResult.cv_id == cv_id)
        .order_by(MatchResult.created_at.desc())
    ).first()
    missing = last_match.result["analysis"]["missing_keywords"] if last_match else []
    try:
        return optimize_application(
            llm, CVExtraction.model_validate(cv.profile), JobExtraction.model_validate(job.details), missing
        )
    except LLMError as e:
        raise HTTPException(502, str(e)) from e
