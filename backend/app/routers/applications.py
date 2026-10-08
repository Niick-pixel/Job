import csv
import io
import subprocess
import sys
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..config import DATA_DIR, get_settings
from ..database import get_session
from ..models import Application, ApplicationStatus, CVProfile, EmailEvent, InterviewPrep, Job, MatchResult, MockInterview
from ..schemas import (ApplicationRead, ApplicationUpdate, CVExtraction, GmailDraftIn, JobExtraction, MessageIn, MockIn,
                       MockTurn, NegotiateIn, OfferDetails)
from ..services import email_sources
from ..services.interviews import (build_ics, compare_offers, contact_from_senders, draft_message, mock_step, negotiate,
                                   prepare_interview)
from ..services.llm import LLMClient, LLMError, get_llm
from ..timeutil import to_utc

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


STATUS_LABEL = {"por_aplicar": "Por aplicar", "aplicado": "Aplicado", "entrevista": "Entrevista",
                "oferta": "Oferta", "rechazado": "Rechazado"}


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_session)):
    """Todas las candidaturas en CSV (se abre directamente en Excel o Numbers)."""
    def local(dt):
        return to_utc(dt).astimezone().strftime("%Y-%m-%d %H:%M") if dt else ""

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")  # Excel en español espera «;»
    w.writerow(["Empresa", "Puesto", "Estado", "Encaje %", "Fuente", "Ubicación", "Enlace", "Fecha de aplicación",
                "Entrevista", "Último seguimiento", "Notas", "Añadida"])
    for app in db.exec(select(Application).order_by(Application.updated_at.desc())).all():
        job = db.get(Job, app.job_id)
        r = to_read(db, app)
        w.writerow([job.company or "", job.title, STATUS_LABEL.get(app.status.value, app.status.value),
                    round(r.match_score) if r.match_score is not None else "", job.source, job.location or "",
                    job.source_url or job.apply_url or "", local(app.applied_at), local(app.interview_at),
                    local(app.follow_up_at), (app.notes or "").replace("\n", " "), local(job.created_at)])
    name = f"candidaturas-{datetime.now():%Y-%m-%d}.csv"
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


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
        app.interview_at = to_utc(payload.interview_at)
    if payload.clear_interview:
        app.interview_at = None
    db.add(app)
    db.commit()
    db.refresh(app)
    return to_read(db, app)



# ── Ficha, calendario, preparación y seguimiento (0.6.0) ───────


def _get(db: Session, app_id: int) -> tuple[Application, Job]:
    app = db.get(Application, app_id)
    if not app:
        raise HTTPException(404, "Candidatura no encontrada")
    return app, db.get(Job, app.job_id)


def _cv(db: Session) -> CVExtraction:
    cv = db.exec(select(CVProfile).order_by(CVProfile.created_at.desc())).first()
    if not cv:
        raise HTTPException(409, "Sube primero tu CV")
    return CVExtraction.model_validate(cv.profile)


def _emails(db: Session, app_id: int) -> list[EmailEvent]:
    return db.exec(select(EmailEvent).where(EmailEvent.application_id == app_id)
                   .order_by(EmailEvent.received_at.desc())).all()


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/{app_id}/detail")
def detail(app_id: int, db: Session = Depends(get_session)):
    app, job = _get(db, app_id)
    emails = _emails(db, app_id)
    prep = db.exec(select(InterviewPrep).where(InterviewPrep.application_id == app_id)).first()
    now = datetime.now(timezone.utc)
    applied = _as_utc(app.applied_at)
    interview = _as_utc(app.interview_at)
    return {
        **to_read(db, app).model_dump(mode="json"),
        "follow_up_at": app.follow_up_at,
        "job": {"id": job.id, "title": job.title, "company": job.company, "location": job.location,
                "url": job.source_url or job.apply_url, "urgency": job.urgency,
                "salary": (job.details or {}).get("salary_range")},
        "emails": [{"subject": e.subject, "sender": e.sender, "category": e.category, "received_at": e.received_at,
                    "summary": (e.analysis or {}).get("summary")} for e in emails],
        "contact": contact_from_senders([e.sender for e in emails]),
        "prep": prep.content if prep else None,
        "offer": app.offer or None,
        "other_offers": len([a for a in db.exec(select(Application).where(Application.status == ApplicationStatus.OFFER)).all()
                             if a.id != app.id and a.offer]),
        "gmail": get_settings().email_mode == "gmail" and get_settings().gmail_token_file.exists(),
        "mocks": [{"average": m.average, "created_at": m.created_at} for m in db.exec(
            select(MockInterview).where(MockInterview.application_id == app_id).order_by(MockInterview.created_at)).all()],
        "days_since_applied": (now - applied).days if applied else None,
        "suggest_follow_up": bool(app.status == ApplicationStatus.APPLIED and applied and (now - applied).days >= 7
                                  and not [e for e in emails if e.category != "confirmacion_recepcion"]),
        "suggest_thanks": bool(app.status == ApplicationStatus.INTERVIEW and interview and interview < now),
    }


@router.get("/{app_id}/calendar.ics")
def calendar_file(app_id: int, db: Session = Depends(get_session)):
    app, job = _get(db, app_id)
    if not app.interview_at:
        raise HTTPException(409, "Primero indica la fecha de la entrevista")
    ics = build_ics(
        uid=f"jobtracker-app-{app.id}@jobtracker.local", start=to_utc(app.interview_at),
        summary=f"Entrevista · {job.company or ''} — {job.title}".replace(" ·  —", " ·"),
        description="Preparada con JobTracker AI." + (f"\n\nNotas: {app.notes}" if app.notes else ""),
        url=job.source_url,
    )
    return Response(ics, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="entrevista-{app.id}.ics"'})


@router.post("/{app_id}/calendar")
def add_to_calendar(app_id: int, db: Session = Depends(get_session)):
    """En macOS abre el evento en Calendario (que pide confirmación); en otros sistemas, descarga."""
    ics = calendar_file(app_id, db).body
    if sys.platform == "darwin":
        folder = DATA_DIR / "calendar"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"entrevista-{app_id}.ics"
        path.write_bytes(ics)
        subprocess.run(["open", str(path)], check=False)
        return {"opened": True}
    return {"opened": False, "url": f"/api/applications/{app_id}/calendar.ics"}


@router.post("/{app_id}/prep")
def generate_prep(app_id: int, db: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)):
    app, job = _get(db, app_id)
    details = JobExtraction.model_validate(job.details) if job.details else None
    try:
        out = prepare_interview(llm, _cv(db), details, job.raw_text)
    except LLMError as e:
        raise HTTPException(502, str(e)) from e
    prep = db.exec(select(InterviewPrep).where(InterviewPrep.application_id == app_id)).first() \
        or InterviewPrep(application_id=app_id)
    prep.content = out.model_dump()
    prep.created_at = datetime.now(timezone.utc)
    db.add(prep)
    db.commit()
    return prep.content


@router.post("/{app_id}/message")
def message(app_id: int, payload: MessageIn, db: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)):
    app, job = _get(db, app_id)
    applied = _as_utc(app.applied_at)
    days = (datetime.now(timezone.utc) - applied).days if applied else None
    local = to_utc(app.interview_at).astimezone() if app.interview_at else None
    when = local.strftime("%d/%m %H:%M") if local else None
    try:
        draft = draft_message(llm, payload.kind, _cv(db), job.title, job.company, days=days, when=when, notes=app.notes)
    except LLMError as e:
        raise HTTPException(502, str(e)) from e
    return {**draft.model_dump(), "to": contact_from_senders([e.sender for e in _emails(db, app_id)])}


@router.post("/{app_id}/follow-up-sent")
def follow_up_sent(app_id: int, db: Session = Depends(get_session)):
    app, _ = _get(db, app_id)
    app.follow_up_at = datetime.now(timezone.utc)
    db.add(app)
    db.commit()
    return {"follow_up_at": app.follow_up_at}


@router.post("/{app_id}/mock")
def mock(app_id: int, payload: MockIn, db: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)):
    """Un paso del simulacro: evalúa la respuesta y hace la siguiente pregunta. Al terminar, se guarda."""
    app, job = _get(db, app_id)
    prep = db.exec(select(InterviewPrep).where(InterviewPrep.application_id == app_id)).first()
    try:
        step = mock_step(llm, _cv(db), job.title, job.company, job.raw_text, prep.content if prep else None,
                         payload.history, payload.current_question, payload.answer, payload.total, payload.finish)
    except LLMError as e:
        raise HTTPException(502, str(e)) from e
    out = step.model_dump()
    if step.next_question is None:
        turns = list(payload.history)
        if payload.current_question and payload.answer:
            turns.append(MockTurn(question=payload.current_question, answer=payload.answer, feedback=step.feedback))
        scores = [t.feedback.score for t in turns if t.feedback]
        if turns:
            session = MockInterview(application_id=app_id, transcript=[t.model_dump() for t in turns],
                                    average=round(sum(scores) / len(scores), 1) if scores else None, summary=step.summary)
            db.add(session)
            db.commit()
            out["saved_id"] = session.id
            out["average"] = session.average
    return out


@router.get("/{app_id}/mocks")
def mocks(app_id: int, db: Session = Depends(get_session)):
    _get(db, app_id)
    rows = db.exec(select(MockInterview).where(MockInterview.application_id == app_id)
                   .order_by(MockInterview.created_at)).all()
    return [{"id": m.id, "created_at": m.created_at, "average": m.average, "questions": len(m.transcript),
             "summary": m.summary} for m in rows]


# ── Ofertas ─────────────────────────────────────────────────────


@router.put("/{app_id}/offer")
def save_offer(app_id: int, payload: OfferDetails, db: Session = Depends(get_session)):
    """Apunta las condiciones de una oferta (y mueve la candidatura a «Oferta»)."""
    app, _ = _get(db, app_id)
    app.offer = payload.model_dump(exclude_none=True)
    if app.status != ApplicationStatus.OFFER:
        apply_status(app, ApplicationStatus.OFFER)
    db.add(app)
    db.commit()
    return app.offer


@router.post("/{app_id}/negotiate")
def negotiation(app_id: int, payload: NegotiateIn, db: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)):
    app, job = _get(db, app_id)
    if not app.offer:
        raise HTTPException(409, "Apunta primero las condiciones de la oferta")
    try:
        out = negotiate(llm, _cv(db), job.title, job.company, job.raw_text, app.offer, payload.target, payload.priorities)
    except LLMError as e:
        raise HTTPException(502, str(e)) from e
    return {**out.model_dump(), "to": contact_from_senders([e.sender for e in _emails(db, app_id)])}


class CompareIn(BaseModel):
    application_ids: list[int] = Field(default_factory=list, max_length=6)
    priorities: list[str] = Field(default_factory=list, max_length=8)


@router.post("/compare-offers")
def compare(payload: CompareIn, db: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)):
    apps = [a for a in db.exec(select(Application).where(Application.status == ApplicationStatus.OFFER)).all() if a.offer]
    if payload.application_ids:
        apps = [a for a in apps if a.id in payload.application_ids]
    if len(apps) < 2:
        raise HTTPException(409, "Hacen falta al menos dos ofertas con sus condiciones apuntadas")
    offers = []
    for a in apps:
        job = db.get(Job, a.job_id)
        o = OfferDetails.model_validate(a.offer)
        offers.append({"application_id": a.id, "title": job.title, "company": job.company, "offer": a.offer,
                       "total": (o.base_salary or 0) + (o.variable or 0) or None, "currency": o.currency})
    try:
        result = compare_offers(llm, _cv(db), offers, payload.priorities)
    except LLMError as e:
        raise HTTPException(502, str(e)) from e
    by_id = {x.application_id: x for x in result.offers}
    return {"offers": [{**o, **(by_id[o["application_id"]].model_dump() if o["application_id"] in by_id else {})} for o in offers],
            "recommendation": result.recommendation, "questions_to_clarify": result.questions_to_clarify}


# ── Gmail: borrador dentro del hilo de la empresa ──────────────


@router.post("/{app_id}/gmail-draft")
def gmail_draft(app_id: int, payload: GmailDraftIn, db: Session = Depends(get_session)):
    """Deja el correo como borrador en Gmail (respuesta en el hilo de la empresa si lo hay). No se envía."""
    settings = get_settings()
    if settings.email_mode != "gmail":
        raise HTTPException(409, "Conecta Gmail en Ajustes para crear borradores")
    _get(db, app_id)
    emails = [e for e in _emails(db, app_id) if e.thread_id]
    ref = next((e for e in emails if email_sources.same_address(e.sender, payload.to)), None) or (emails[0] if emails else None)
    try:
        return email_sources.create_draft(settings, payload.to, payload.subject, payload.body,
                                          thread_id=ref.thread_id if ref else None,
                                          in_reply_to=ref.rfc_message_id if ref else None,
                                          reply_subject=ref.subject if ref else None)
    except Exception as e:  # noqa: BLE001  (permisos, red…)
        raise HTTPException(502, f"Gmail no ha aceptado el borrador: {e}") from e
