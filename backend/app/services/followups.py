"""Borradores de seguimiento automáticos: si una empresa no contesta en 7 días, la app deja el correo
de seguimiento como borrador en Gmail, dentro del hilo de la empresa. Nunca lo envía: tú lo revisas
y lo envías desde Gmail (y luego lo marcas como enviado en la ficha, o la app lo ve al sincronizar)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from ..config import Settings
from ..models import Application, CVProfile, EmailEvent, Job
from ..schemas import CVExtraction, SearchPreferences
from . import email_sources
from .digest import build_digest
from .interviews import contact_from_senders, draft_message
from .llm import LLMClient
from .region import market_context
from .usage import over_budget

MAX_PER_RUN = 3
COOLDOWN = timedelta(days=7)


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def create_followup_drafts(db: Session, llm: LLMClient, settings: Settings, prefs: SearchPreferences,
                           now: datetime | None = None, service=None) -> list[str]:
    """Devuelve las empresas para las que dejó borrador. Silencioso si Gmail no está listo."""
    now = now or datetime.now(timezone.utc)
    if not prefs.auto_followup_drafts or settings.email_mode != "gmail" or over_budget(db, prefs.monthly_budget_usd):
        return []
    cv_row = db.exec(select(CVProfile).order_by(CVProfile.created_at.desc())).first()
    if not cv_row:
        return []
    if service is None:
        try:
            service = email_sources.gmail_service(settings, compose=True, interactive=False)
        except Exception:  # noqa: BLE001  (sin permiso de borradores todavía: se pedirá al crear uno a mano)
            return []
    cv = CVExtraction.model_validate(cv_row.profile)
    done = []
    for item in build_digest(db, now)["stale"]:
        if len(done) >= MAX_PER_RUN:
            break
        app = db.get(Application, item["application_id"])
        if not app or (_aware(app.follow_up_draft_at) and now - _aware(app.follow_up_draft_at) < COOLDOWN):
            continue
        emails = db.exec(select(EmailEvent).where(EmailEvent.application_id == app.id)
                         .order_by(EmailEvent.received_at.desc())).all()
        to = contact_from_senders([e.sender for e in emails])
        if not to:
            continue
        job = db.get(Job, app.job_id)
        draft = draft_message(llm, "seguimiento", cv, job.title, job.company, days=item["days"], notes=app.notes,
                              market=market_context(prefs.country))
        ref = next((e for e in emails if e.thread_id and email_sources.same_address(e.sender, to)), None)
        email_sources.create_draft(settings, to, draft.subject, draft.body, thread_id=ref.thread_id if ref else None,
                                   in_reply_to=ref.rfc_message_id if ref else None,
                                   reply_subject=ref.subject if ref else None, service=service)
        app.follow_up_draft_at = now
        db.add(app)
        db.commit()
        done.append(job.company or job.title)
    return done
