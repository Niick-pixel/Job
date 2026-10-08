import re

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..config import get_settings
from ..database import get_session
from ..models import Application, EmailEvent, Job
from ..schemas import EmailClassification, EmailIn
from ..services.email_classifier import CATEGORY_TO_STATUS, classify_email
from ..services.email_sources import fetch_emails
from ..services.llm import LLMClient, LLMError, get_llm
from ..services.notify import notify
from ..services.sources import is_job_alert
from ..timeutil import to_utc
from .applications import apply_status

router = APIRouter(prefix="/api/emails", tags=["Correos"])


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def find_application(db: Session, email: EmailIn, cls: EmailClassification) -> Application | None:
    """Vincula el correo con una candidatura por nombre de empresa (o dominio del remitente)."""
    domain = email.sender.split("@")[-1].split(".")[0] if "@" in email.sender else ""
    hints = [h for h in (_norm(cls.company), _norm(domain)) if len(h) >= 3]
    for job in db.exec(select(Job)).all():
        company = _norm(job.company)
        if company and any(h in company or company in h for h in hints):
            return db.exec(select(Application).where(Application.job_id == job.id)).first()
    return None


def process_email(db: Session, llm: LLMClient, email: EmailIn) -> EmailEvent:
    existing = db.exec(select(EmailEvent).where(EmailEvent.message_id == email.message_id)).first()
    if existing:
        return existing

    cls = classify_email(llm, email)
    app = find_application(db, email, cls)
    target = CATEGORY_TO_STATUS.get(cls.category)
    if app and target and cls.confidence >= 0.6:
        apply_status(app, target)
        if cls.interview_datetime:
            app.interview_at = to_utc(cls.interview_datetime)
        db.add(app)
    if cls.category == "entrevista" and cls.confidence >= 0.6:
        when = cls.interview_datetime.strftime(" · %d/%m %H:%M") if cls.interview_datetime else ""
        notify("🎤 Entrevista detectada", f"{cls.company or email.sender}{when} · prepárala desde la app")

    event = EmailEvent(
        message_id=email.message_id,
        sender=email.sender,
        subject=email.subject,
        received_at=email.received_at,
        category=cls.category,
        confidence=cls.confidence,
        application_id=app.id if app else None,
        analysis=cls.model_dump(mode="json"),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.post("/classify", response_model=EmailEvent)
def classify(email: EmailIn, db: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)):
    try:
        return process_email(db, llm, email)
    except LLMError as e:
        raise HTTPException(502, str(e)) from e


@router.post("/sync", response_model=list[EmailEvent])
def sync(db: Session = Depends(get_session), llm: LLMClient = Depends(get_llm)):
    """Lee la bandeja (simulada o Gmail) y procesa los correos nuevos."""
    try:
        # Las alertas de empleo las procesa el agente (son ofertas nuevas, no respuestas)
        return [process_email(db, llm, e) for e in fetch_emails(get_settings()) if not is_job_alert(e)]
    except LLMError as e:
        raise HTTPException(502, str(e)) from e


@router.get("", response_model=list[EmailEvent])
def list_events(db: Session = Depends(get_session)):
    return db.exec(select(EmailEvent).where(EmailEvent.category != "alerta_empleo")
                   .order_by(EmailEvent.created_at.desc())).all()


@router.get("/alerts", response_model=list[EmailEvent])
def interview_alerts(db: Session = Depends(get_session)):
    """Invitaciones a entrevista detectadas: el frontend las muestra como alerta."""
    return db.exec(
        select(EmailEvent).where(EmailEvent.category.in_(["entrevista", "oferta"])).order_by(EmailEvent.created_at.desc())
    ).all()
