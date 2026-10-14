"""Informe de ajuste: sugerencias concretas para afinar la búsqueda, cada una aplicable con un clic.

Se calcula con tus datos (sin IA, gratis): fuentes que solo traen ruido, empresas que descartas una y otra
vez, filtros que se comen demasiado, ofertas que te gustaron pero el agente puntuó bajo…
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from ..models import Feedback, Job, PipelineStatus
from ..schemas import SearchPreferences
from .targeting import NEGATIVE, POSITIVE

LIST_SOURCES = ("greenhouse", "lever", "ashby", "smartrecruiters", "recruitee", "breezy", "workable", "workday")
NOISE_MIN = 25


def source_key(job: Job) -> tuple[str, str | None]:
    """(proveedor, empresa) de una oferta; empresa None para fuentes que no son por empresa."""
    parts = (job.external_id or "").split(":")
    if job.source in LIST_SOURCES and len(parts) >= 3:
        return job.source, parts[1]
    return job.source, None


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def suggestions(db: Session, prefs: SearchPreferences, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=30)
    jobs = [j for j in db.exec(select(Job).where(Job.pipeline_status != PipelineStatus.MANUAL.value)).all()
            if (_aware(j.created_at) or now) >= since]
    fb = db.exec(select(Feedback).order_by(Feedback.created_at.desc()).limit(500)).all()
    pos_jobs = {f.job_id for f in fb if f.decision in POSITIVE and f.job_id}
    out: list[dict] = []

    # 0. Sin perfil ideal: lo primero
    if prefs.ideal.is_empty():
        out.append({"id": "calibrate", "kind": "perfil", "priority": 0,
                    "text": "Aún no le has dicho al agente qué buscas: haz la ronda de calibración (2 minutos).",
                    "action": {"type": "calibrate", "label": "Calibrar"}})

    # 1. Fuentes que solo traen ruido
    groups = defaultdict(list)
    for j in jobs:
        groups[source_key(j)].append(j)
    for (provider, slug), items in groups.items():
        if len(items) < NOISE_MIN or provider in ("manual", "email", "trace"):
            continue
        good = [j for j in items if j.id in pos_jobs or j.pipeline_status in (PipelineStatus.IN_INBOX.value, PipelineStatus.APPROVED.value)]
        noise = sum(j.pipeline_status in (PipelineStatus.FILTERED.value, PipelineStatus.LOW_SCORE.value) for j in items) / len(items)
        if not good and noise >= 0.9:
            name = f"{provider} · {slug}" if slug else provider
            out.append({"id": f"pause:{provider}:{slug or ''}", "kind": "fuente", "priority": 2,
                        "text": f"{name}: {len(items)} ofertas en 30 días y ninguna te ha servido ({noise:.0%} descartadas). ¿La pausamos?",
                        "action": {"type": "pause_source", "provider": provider, "slug": slug, "label": "Pausar fuente"}})

    # 2. Empresas que descartas una y otra vez
    neg_companies = Counter((f.company or "").strip() for f in fb if f.decision in NEGATIVE and f.company)
    for company, n in neg_companies.most_common(3):
        if n >= 3 and company.lower() not in {c.lower() for c in prefs.blacklist_companies}:
            out.append({"id": f"blacklist:{company}", "kind": "empresa", "priority": 3,
                        "text": f"Has descartado {n} ofertas de {company}. ¿Dejamos de mostrártela?",
                        "action": {"type": "blacklist", "company": company, "label": "No mostrar más"}})

    # 3. Motivos de descarte repetidos → ajustar el perfil
    reasons = Counter((f.reason or "").strip().lower() for f in fb[:200] if f.decision in NEGATIVE and f.reason)
    if reasons.get("sueldo bajo", 0) >= 3 and not prefs.ideal.min_monthly_salary:
        out.append({"id": "salary", "kind": "perfil", "priority": 1,
                    "text": f"Descartaste {reasons['sueldo bajo']} ofertas por sueldo bajo: indica tu salario mínimo y el agente las evitará.",
                    "action": {"type": "edit_ideal", "label": "Poner salario mínimo"}})
    for reason, label in (("demasiado junior", "nivel"), ("demasiado senior", "nivel"), ("ubicación o modalidad", "modalidad")):
        if reasons.get(reason, 0) >= 3:
            out.append({"id": f"reason:{reason}", "kind": "perfil", "priority": 2,
                        "text": f"Descartaste {reasons[reason]} ofertas por «{reason}»: ajusta el {label} en tu perfil ideal.",
                        "action": {"type": "edit_ideal", "label": "Ajustar perfil"}})

    # 4. Te gustaron ofertas que el agente puntuó bajo → umbral demasiado alto
    liked_low = [j for j in jobs if j.id in pos_jobs and j.pipeline_status == PipelineStatus.LOW_SCORE.value
                 and (j.triage or {}).get("score") is not None]
    if len(liked_low) >= 2 and prefs.triage_threshold > 45:
        new = max(45, min(int((j.triage or {})["score"]) for j in liked_low) - 2, prefs.triage_threshold - 10)
        out.append({"id": "threshold", "kind": "criba", "priority": 1,
                    "text": f"Te gustaron {len(liked_low)} ofertas que la criba puntuó bajo. ¿Bajamos el umbral de {prefs.triage_threshold} a {new}?",
                    "action": {"type": "threshold", "value": new, "label": f"Bajar a {new}"}})

    # 5. Filtros que se comen demasiado
    filtered = [j for j in jobs if j.pipeline_status == PipelineStatus.FILTERED.value]
    by_loc = [j for j in filtered if str((j.triage or {}).get("filter_reason", "")).startswith("ubicación")]
    if len(jobs) >= 40 and len(by_loc) / len(jobs) >= 0.5:
        places = Counter((j.location or "").split(",")[0].strip() for j in by_loc).most_common(3)
        out.append({"id": "locations", "kind": "filtro", "priority": 2,
                    "text": f"El filtro de ubicación descarta {len(by_loc)} de {len(jobs)} ofertas (sobre todo {', '.join(p for p, _ in places if p)}). "
                            "Revisa tus ubicaciones o activa «Acepto remoto».",
                    "action": {"type": "route", "route": "agente", "label": "Revisar filtros"}})

    # 6. Lo que te gusta y no está en tus búsquedas
    liked_titles = [f.title for f in fb if f.decision in POSITIVE][:30]
    if len(liked_titles) >= 3:
        words = Counter(w for t in liked_titles for w in {w.lower() for w in t.replace("/", " ").split() if len(w) > 3})
        queries = " ".join(prefs.sources.getonbrd_queries + prefs.sources.remotive_queries).lower()
        top = [w for w, n in words.most_common(5) if n >= 2 and w not in queries][:2]
        if top:
            out.append({"id": "queries", "kind": "búsquedas", "priority": 3,
                        "text": f"Te gustan ofertas con «{'», «'.join(top)}», pero no lo buscas. ¿Regeneramos las búsquedas con IA?",
                        "action": {"type": "suggest_queries", "label": "Generar búsquedas"}})

    return sorted(out, key=lambda s: s["priority"])


def apply(prefs: SearchPreferences, suggestion: dict) -> SearchPreferences:
    """Aplica una sugerencia automática (las que necesitan tu decisión se resuelven en la interfaz)."""
    prefs = prefs.model_copy(deep=True)
    a = suggestion["action"]
    if a["type"] == "pause_source":
        provider, slug = a["provider"], a.get("slug")
        if slug is not None and isinstance(getattr(prefs.sources, provider, None), list):
            setattr(prefs.sources, provider, [x for x in getattr(prefs.sources, provider)
                                              if x.lower() != slug.lower() and slug.lower() not in x.lower()])
        elif provider == "getonbrd":
            prefs.sources.getonbrd_queries = []
        elif provider == "remotive":
            prefs.sources.remotive_queries = []
        elif provider == "adzuna":
            prefs.sources.adzuna_queries = []
        elif hasattr(prefs.sources, provider) and isinstance(getattr(prefs.sources, provider), bool):
            setattr(prefs.sources, provider, False)
    elif a["type"] == "blacklist":
        prefs.blacklist_companies = list(dict.fromkeys(prefs.blacklist_companies + [a["company"]]))
    elif a["type"] == "threshold":
        prefs.triage_threshold = int(a["value"])
    else:
        raise ValueError("Esta sugerencia se aplica desde la interfaz")
    return prefs
