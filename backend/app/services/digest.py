"""Resumen diario: lo que merece tu atención hoy.

Se muestra como tarjeta «Hoy» en la Bandeja y como notificación de macOS a la hora elegida.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from ..models import Application, ApplicationPackage, ApplicationStatus, EmailEvent, Job

STALE_DAYS = 7


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite devuelve fechas sin zona horaria: se guardan siempre en UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def build_digest(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)

    pending = db.exec(select(ApplicationPackage).where(ApplicationPackage.status == "pendiente")).all()
    new_today = [p for p in pending if (_aware(p.created_at) or now) >= yesterday]
    approved = db.exec(select(ApplicationPackage).where(ApplicationPackage.status == "aprobada")).all()

    interviews, stale = [], []
    for app in db.exec(select(Application)).all():
        job = db.get(Job, app.job_id)
        at = _aware(app.interview_at)
        if app.status == ApplicationStatus.INTERVIEW and at and now - timedelta(hours=2) <= at <= now + timedelta(hours=48):
            interviews.append({"application_id": app.id, "title": job.title, "company": job.company, "at": at.isoformat()})
        applied = _aware(app.applied_at)
        followed = _aware(app.follow_up_at)
        recently_followed = followed and followed > now - timedelta(days=STALE_DAYS)
        if app.status == ApplicationStatus.APPLIED and applied and applied <= now - timedelta(days=STALE_DAYS) \
                and not recently_followed:
            replied = db.exec(select(EmailEvent.id).where(EmailEvent.application_id == app.id,
                                                          EmailEvent.category != "confirmacion_recepcion")).first()
            if not replied:
                stale.append({"application_id": app.id, "title": job.title, "company": job.company,
                              "days": (now - applied).days})

    interviews.sort(key=lambda x: x["at"])
    stale.sort(key=lambda x: -x["days"])
    return {
        "generated_at": now.isoformat(),
        "pending": len(pending), "new_today": len(new_today),
        "approved_unsent": len(approved),
        "interviews": interviews, "stale": stale,
    }


def digest_message(d: dict) -> tuple[str, str] | None:
    """Título y texto de la notificación, o None si no hay nada que contar."""
    parts = []
    if d["interviews"]:
        first = d["interviews"][0]
        parts.append(f"🎤 {len(d['interviews'])} entrevista(s) pronto · {first['company'] or first['title']}")
    if d["new_today"]:
        parts.append(f"📥 {d['new_today']} candidatura(s) nueva(s) para revisar")
    elif d["pending"]:
        parts.append(f"📥 {d['pending']} candidatura(s) pendiente(s) en la Bandeja")
    if d["approved_unsent"]:
        parts.append(f"📤 {d['approved_unsent']} aprobada(s) sin enviar")
    if d["stale"]:
        parts.append(f"⏳ {len(d['stale'])} sin respuesta desde hace más de {STALE_DAYS} días")
    if not parts:
        return None
    return "JobTracker AI · Hoy", " · ".join(parts)


# ── Aviso la víspera de cada entrevista ─────────────────────────

EVE_HOUR = 18  # a partir de esta hora local se avisa de las entrevistas de mañana


def due_reminders(db: Session, now_local: datetime, sent: set[str]) -> list[dict]:
    """Entrevistas de mañana (a partir de las 18:00) o de hoy aún no avisadas. now_local: hora local con zona."""
    out = []
    for app in db.exec(select(Application).where(Application.status == ApplicationStatus.INTERVIEW)).all():
        at = _aware(app.interview_at)
        if not at or at <= now_local:
            continue
        local = at.astimezone(now_local.tzinfo)
        days = (local.date() - now_local.date()).days
        key = f"{app.id}:{at.isoformat()}"
        if key in sent or not (days == 0 or (days == 1 and now_local.hour >= EVE_HOUR)):
            continue
        job = db.get(Job, app.job_id)
        out.append({"key": key, "application_id": app.id, "company": job.company or job.title,
                    "title": job.title, "when": local.strftime("%H:%M"), "today": days == 0})
    return out


def reminder_message(r: dict) -> tuple[str, str]:
    day = "Hoy" if r["today"] else "Mañana"
    return f"🎤 {day} a las {r['when']}: entrevista", f"{r['company']} · {r['title']} — repasa el dossier en la ficha"
