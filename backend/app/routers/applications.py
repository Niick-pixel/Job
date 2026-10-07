from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..database import get_session
from ..models import Application, ApplicationStatus, Job, MatchResult
from ..schemas import ApplicationRead, ApplicationUpdate

router = APIRouter(prefix="/api/applications", tags=["Kanban"])


def to_read(db: Session, app: Application) -> ApplicationRead:
    job = db.get(Job, app.job_id)
    match = db.exec(
        select(MatchResult).where(MatchResult.job_id == app.job_id).order_by(MatchResult.created_at.desc())
    ).first()
    return ApplicationRead(
        id=app.id,
        job_id=app.job_id,
        status=app.status,
        notes=app.notes,
        applied_at=app.applied_at,
        interview_at=app.interview_at,
        job_title=job.title,
        company=job.company,
        match_score=match.score if match else None,
        urgency_level=job.urgency.get("level"),
    )


def apply_status(app: Application, status: ApplicationStatus) -> None:
    app.status = status
    now = datetime.now(timezone.utc)
    if status == ApplicationStatus.APPLIED and app.applied_at is None:
        app.applied_at = now
    app.updated_at = now


@router.get("", response_model=list[ApplicationRead])
def list_applications(db: Session = Depends(get_session)):
    apps = db.exec(select(Application).order_by(Application.updated_at.desc())).all()
    return [to_read(db, a) for a in apps]


@router.get("/board", response_model=dict[ApplicationStatus, list[ApplicationRead]])
def board(db: Session = Depends(get_session)):
    columns: dict[ApplicationStatus, list[ApplicationRead]] = {s: [] for s in ApplicationStatus}
    for app in db.exec(select(Application)).all():
        columns[app.status].append(to_read(db, app))
    return columns


@router.patch("/{app_id}", response_model=ApplicationRead)
def update_application(app_id: int, payload: ApplicationUpdate, db: Session = Depends(get_session)):
    app = db.get(Application, app_id)
    if not app:
        raise HTTPException(404, "Candidatura no encontrada")
    if payload.status is not None:
        apply_status(app, payload.status)
    if payload.notes is not None:
        app.notes = payload.notes
    if payload.interview_at is not None:
        app.interview_at = payload.interview_at
    db.add(app)
    db.commit()
    db.refresh(app)
    return to_read(db, app)
