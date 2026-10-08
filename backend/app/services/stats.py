"""Resultados de tu búsqueda: embudo, respuesta por fuente y por versión de CV, y tiempos de respuesta.

También alimenta al agente: las fuentes que más respuestas te consiguen pesan un poco más al elegir qué
ofertas analizar a fondo (solo cuando hay datos suficientes, y con un efecto acotado).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlmodel import Session, select

from ..models import (Application, ApplicationPackage, ApplicationStatus, CVProfile, EmailEvent, Feedback, Job,
                      PipelineStatus)

MIN_APPLIED = 5        # aplicaciones por fuente antes de sacar conclusiones
MAX_EFFECT = 0.10      # ±10 % como mucho en la prioridad del agente
SOURCE_LABEL = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "remotive": "Remotive",
                "adzuna": "Adzuna", "email": "Alertas por correo", "manual": "Añadidas por ti"}


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _outcomes(db: Session) -> list[dict]:
    """Una fila por candidatura con lo que ha pasado."""
    emails = defaultdict(list)
    for e in db.exec(select(EmailEvent).where(EmailEvent.application_id.is_not(None))).all():
        emails[e.application_id].append(e)
    pkgs = {p.job_id: p for p in db.exec(select(ApplicationPackage)).all()}
    rows = []
    for app in db.exec(select(Application)).all():
        job = db.get(Job, app.job_id)
        if not job:
            continue
        mails = emails[app.id]
        cats = {e.category for e in mails}
        replies = [e for e in mails if e.category != "confirmacion_recepcion"]
        applied = _aware(app.applied_at)
        first_reply = min((_aware(e.received_at) or _aware(e.created_at) for e in replies), default=None)
        status = app.status
        rows.append({
            "source": job.source or "manual",
            "cv_id": pkgs[job.id].cv_id if job.id in pkgs else None,
            "applied": applied is not None or status != ApplicationStatus.TO_APPLY,
            "applied_at": applied,
            "response": bool(replies) or status in (ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER, ApplicationStatus.REJECTED),
            "interview": status in (ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER) or app.interview_at is not None
                         or "entrevista" in cats,
            "offer": status == ApplicationStatus.OFFER or "oferta" in cats,
            "rejected": status == ApplicationStatus.REJECTED or "rechazo" in cats,
            "reply_days": (first_reply - applied).days if applied and first_reply and first_reply >= applied else None,
        })
    return rows


def _group(rows: list[dict], key, label) -> list[dict]:
    groups = defaultdict(list)
    for r in rows:
        if r["applied"]:
            groups[key(r)].append(r)
    out = []
    for k, items in groups.items():
        n = len(items)
        out.append({"key": k, "label": label(k), "applied": n,
                    "responses": sum(r["response"] for r in items), "interviews": sum(r["interview"] for r in items),
                    "response_rate": round(100 * sum(r["response"] for r in items) / n),
                    "interview_rate": round(100 * sum(r["interview"] for r in items) / n),
                    "enough": n >= MIN_APPLIED})
    return sorted(out, key=lambda g: (-g["applied"], g["label"]))


def build_stats(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    rows = _outcomes(db)
    applied = [r for r in rows if r["applied"]]
    cvs = {c.id: c for c in db.exec(select(CVProfile)).all()}

    def cv_label(cv_id):
        c = cvs.get(cv_id)
        return f"{c.filename} · {c.created_at:%d/%m/%Y}" if c else "Sin CV adaptado (a mano)"

    days = [r["reply_days"] for r in applied if r["reply_days"] is not None]
    # Actividad: candidaturas enviadas por semana (últimas 12)
    start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(weeks=11)
    weeks = [start + timedelta(weeks=i) for i in range(12)]
    per_week = Counter()
    for r in applied:
        if r["applied_at"] and r["applied_at"] >= start:
            per_week[(r["applied_at"] - start).days // 7] += 1

    pipeline = Counter(j.pipeline_status for j in db.exec(select(Job)).all())
    reasons = Counter((f.reason or "").strip() for f in db.exec(select(Feedback).where(Feedback.decision == "descartada")).all())
    reasons.pop("", None)
    return {
        "funnel": {
            "tracked": len(rows), "applied": len(applied),
            "responses": sum(r["response"] for r in applied), "interviews": sum(r["interview"] for r in applied),
            "offers": sum(r["offer"] for r in applied), "rejected": sum(r["rejected"] for r in applied),
        },
        "by_source": _group(rows, lambda r: r["source"], lambda k: SOURCE_LABEL.get(k, k)),
        "by_cv": _group(rows, lambda r: r["cv_id"], cv_label),
        "reply_days": {"median": median(days) if days else None, "count": len(days),
                       "max": max(days) if days else None},
        "weekly": [{"week": w.date().isoformat(), "applied": per_week[i]} for i, w in enumerate(weeks)],
        "agent": {
            "discovered": sum(pipeline.values()) - pipeline.get(PipelineStatus.MANUAL.value, 0),
            "filtered": pipeline.get(PipelineStatus.FILTERED.value, 0),
            "low_score": pipeline.get(PipelineStatus.LOW_SCORE.value, 0),
            "in_inbox": pipeline.get(PipelineStatus.IN_INBOX.value, 0),
            "approved": pipeline.get(PipelineStatus.APPROVED.value, 0),
            "discarded": pipeline.get(PipelineStatus.DISCARDED.value, 0),
            "top_discard_reasons": [{"reason": r, "count": n} for r, n in reasons.most_common(5)],
        },
        "source_weights": source_weights(db, rows),
    }


def source_weights(db: Session, rows: list[dict] | None = None) -> dict[str, float]:
    """Multiplicador por fuente (0,90-1,10) según su tasa de respuesta frente a la media.
    Solo para fuentes con al menos MIN_APPLIED candidaturas enviadas."""
    rows = rows if rows is not None else _outcomes(db)
    applied = [r for r in rows if r["applied"]]
    if len(applied) < 2 * MIN_APPLIED:
        return {}
    overall = sum(r["response"] for r in applied) / len(applied)
    weights = {}
    for g in _group(rows, lambda r: r["source"], str):
        if not g["enough"]:
            continue
        rate = g["responses"] / g["applied"]
        diff = (rate - overall) / max(overall, 0.05)
        weights[g["key"]] = round(1 + max(-MAX_EFFECT, min(MAX_EFFECT, diff * MAX_EFFECT)), 3)
    return weights
