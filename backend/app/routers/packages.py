from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ..config import get_settings
from ..database import get_session
from ..models import AnswerBankEntry, Application, ApplicationPackage, ApplicationStatus, CVProfile, Feedback, Job, \
    MatchResult, PipelineStatus
from ..schemas import AnswerIn, PackageDecision
from ..services.llm import LLMClient, LLMError, get_llm
from ..services.packages import prepare_package, seed_answer_bank
from .applications import apply_status

router = APIRouter(tags=["Bandeja"])


def _package_view(db: Session, pkg: ApplicationPackage) -> dict:
    job = db.get(Job, pkg.job_id)
    match = db.exec(select(MatchResult).where(MatchResult.job_id == job.id)
                    .order_by(MatchResult.created_at.desc())).first()
    return {
        **pkg.model_dump(mode="json"),
        "job": {"id": job.id, "title": job.title, "company": job.company, "location": job.location,
                "url": job.source_url, "apply_url": job.apply_url or job.source_url, "source": job.source,
                "posted_date": job.posted_date, "urgency": job.urgency, "triage_reason": (job.triage or {}).get("reason")},
        "match": ({"score": match.score, **match.result.get("analysis", {})} if match else None),
        "pending_answers": [a["question"] for a in pkg.answers if a.get("answer") is None],
    }


@router.get("/api/packages")
def list_packages(status: str = "pendiente", db: Session = Depends(get_session)):
    pkgs = db.exec(select(ApplicationPackage).where(ApplicationPackage.status == status)
                   .order_by(ApplicationPackage.created_at.desc())).all()
    views = [_package_view(db, p) for p in pkgs]
    # Primero lo que más encaja y más urge
    views.sort(key=lambda v: ((v["match"] or {}).get("score", 0) * 0.8
                              + (v["job"]["urgency"] or {}).get("score", 50) * 0.2), reverse=True)
    return views


@router.post("/api/jobs/{job_id}/prepare")
def prepare(job_id: int, cv_id: int, db: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)):
    """Prepara a mano una candidatura (también para ofertas añadidas manualmente)."""
    job, cv = db.get(Job, job_id), db.get(CVProfile, cv_id)
    if not job or not cv:
        raise HTTPException(404, "Oferta o CV no encontrado")
    try:
        pkg = prepare_package(db, llm, get_settings(), job, cv)
    except LLMError as e:
        raise HTTPException(502, str(e)) from e
    if job.pipeline_status != PipelineStatus.MANUAL.value:
        job.pipeline_status = PipelineStatus.IN_INBOX.value
        db.add(job)
        db.commit()
    return _package_view(db, pkg)


@router.get("/api/packages/{pkg_id}/cv.pdf")
def download_cv(pkg_id: int, db: Session = Depends(get_session)):
    pkg = db.get(ApplicationPackage, pkg_id)
    if not pkg or not pkg.cv_pdf_path or not Path(pkg.cv_pdf_path).exists():
        raise HTTPException(404, "PDF no disponible")
    return FileResponse(pkg.cv_pdf_path, media_type="application/pdf", filename=Path(pkg.cv_pdf_path).name)


@router.post("/api/packages/{pkg_id}/decision")
def decide(pkg_id: int, payload: PackageDecision, db: Session = Depends(get_session)):
    pkg = db.get(ApplicationPackage, pkg_id)
    if not pkg:
        raise HTTPException(404, "Candidatura no encontrada")
    job = db.get(Job, pkg.job_id)
    now = datetime.now(timezone.utc)
    if payload.cover_letter is not None:
        pkg.cover_letter = payload.cover_letter
    pkg.status, pkg.decided_at, pkg.decision_reason = payload.decision, now, payload.reason

    app = db.exec(select(Application).where(Application.job_id == job.id)).first()
    if payload.decision in ("aprobada", "enviada"):
        if job.pipeline_status != PipelineStatus.MANUAL.value:
            job.pipeline_status = PipelineStatus.APPROVED.value
        if not app:  # entra en el Kanban
            app = Application(job_id=job.id)
        if payload.decision == "enviada":
            apply_status(app, ApplicationStatus.APPLIED)
        db.add(app)
    else:
        if job.pipeline_status != PipelineStatus.MANUAL.value:
            job.pipeline_status = PipelineStatus.DISCARDED.value
    if payload.decision != "enviada":  # «enviada» confirma una aprobación previa, no es preferencia nueva
        db.add(Feedback(job_id=job.id, decision=payload.decision, reason=payload.reason,
                        title=job.title, company=job.company))
    db.add_all([pkg, job])
    db.commit()
    return _package_view(db, pkg)


@router.get("/api/answers", response_model=list[AnswerBankEntry])
def list_answers(db: Session = Depends(get_session)):
    seed_answer_bank(db)
    return db.exec(select(AnswerBankEntry).order_by(AnswerBankEntry.id)).all()


@router.put("/api/answers", response_model=AnswerBankEntry)
def upsert_answer(payload: AnswerIn, db: Session = Depends(get_session)):
    entry = db.exec(select(AnswerBankEntry).where(AnswerBankEntry.key == payload.key)).first() \
        or AnswerBankEntry(key=payload.key, question=payload.question)
    entry.question, entry.answer = payload.question, payload.answer
    entry.updated_at = datetime.now(timezone.utc)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/api/answers/{key}", status_code=204)
def delete_answer(key: str, db: Session = Depends(get_session)):
    entry = db.exec(select(AnswerBankEntry).where(AnswerBankEntry.key == key)).first()
    if entry:
        db.delete(entry)
        db.commit()
