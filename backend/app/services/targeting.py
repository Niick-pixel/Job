"""Afinar la búsqueda: perfil ideal, votos 👍/👎, ronda de calibración y búsquedas generadas por IA.

Sin esto el agente solo sabe lo que PUEDES hacer (tu CV). Con esto sabe lo que QUIERES:
- el perfil ideal (puestos, nivel, salario, modalidad, imprescindibles y lo que lo descarta),
- ejemplos de ofertas que te gustaron y que no (likes, aprobaciones, descartes con motivo),
y ambos entran en la criba y en el análisis final.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from ..config import Settings
from ..models import Feedback, Job, PipelineStatus
from ..schemas import CalibrationOut, CVExtraction, IdealProfile, QueriesProposal, SearchPreferences
from .llm import LLMClient
from .region import country_info

POSITIVE = ("aprobada", "like")
NEGATIVE = ("descartada", "dislike")


def ideal_text(prefs: SearchPreferences) -> str:
    """El perfil ideal en texto para los prompts (vacío si no hay nada)."""
    i = prefs.ideal
    if i.is_empty():
        return ""
    parts = []
    add = lambda label, xs: parts.append(f"- {label}: {', '.join(xs)}") if xs else None  # noqa: E731
    add("Puestos que busca", i.roles_wanted)
    add("Puestos que NO quiere", i.roles_avoid)
    add("Nivel", i.seniority)
    if i.min_monthly_salary:
        parts.append(f"- Salario mínimo: {i.min_monthly_salary:,.0f} {i.salary_currency} brutos al mes")
    add("Modalidad aceptada", i.modalities)
    add("Sectores que le gustan", i.industries_like)
    add("Sectores que evita", i.industries_avoid)
    add("Imprescindible", i.must_haves)
    add("Lo descarta", i.deal_breakers)
    if i.notes.strip():
        parts.append(f"- En sus palabras: {i.notes.strip()}")
    return "\n".join(parts)


def feedback_examples(db: Session, n_pos: int = 20, n_neg: int = 30) -> str:
    """Ofertas que le gustaron y que no, con motivo: la mejor señal de lo que quiere."""
    rows = db.exec(select(Feedback).order_by(Feedback.created_at.desc()).limit(300)).all()
    pos = [f for f in rows if f.decision in POSITIVE][:n_pos]
    neg = [f for f in rows if f.decision in NEGATIVE][:n_neg]
    line = lambda f: f"- {f.title} @ {f.company or '?'}" + (f" — {f.reason}" if f.reason else "")  # noqa: E731
    out = []
    if pos:
        out.append("LE INTERESAN (busca más como estas):\n" + "\n".join(line(f) for f in pos))
    if neg:
        out.append("NO LE INTERESAN:\n" + "\n".join(line(f) for f in neg))
    return "\n\n".join(out) or "(todavía ninguna)"


def record_vote(db: Session, job: Job, vote: str, reason: str | None = None) -> Feedback:
    """👍/👎 sobre cualquier oferta (también las descartadas). El último voto por oferta es el que vale."""
    for old in db.exec(select(Feedback).where(Feedback.job_id == job.id, Feedback.decision.in_(("like", "dislike")))).all():
        db.delete(old)
    fb = Feedback(job_id=job.id, decision=vote, reason=reason, title=job.title, company=job.company)
    db.add(fb)
    db.commit()
    return fb


def job_votes(db: Session, job_ids: list[int]) -> dict[int, str]:
    if not job_ids:
        return {}
    rows = db.exec(select(Feedback).where(Feedback.job_id.in_(job_ids), Feedback.decision.in_(("like", "dislike")))).all()
    return {f.job_id: f.decision for f in rows}


# ── Calibración ─────────────────────────────────────────────────


def calibration_sample(db: Session, n: int = 15, seed: int | None = None) -> list[Job]:
    """Ofertas variadas para votar: de distintas fuentes y de todo el rango de puntuaciones, también
    algunas que el agente descartó (para ver si se equivocó). Sin las ya votadas."""
    rng = random.Random(seed)
    voted = {f.job_id for f in db.exec(select(Feedback).where(Feedback.job_id.is_not(None))).all()}
    since = datetime.now(timezone.utc) - timedelta(days=60)
    pool = [j for j in db.exec(select(Job).where(Job.pipeline_status != PipelineStatus.MANUAL.value,
                                                 Job.created_at >= since)).all()
            if j.id not in voted and len(j.raw_text or "") > 80]
    scored = lambda j: (j.triage or {}).get("match_score") or (j.triage or {}).get("score")  # noqa: E731
    buckets = {
        "alto": [j for j in pool if (scored(j) or 0) >= 70],
        "medio": [j for j in pool if 45 <= (scored(j) or 0) < 70],
        "bajo": [j for j in pool if scored(j) is not None and scored(j) < 45],
        # filtradas por algo que no sea la ubicación ni la antigüedad (esas suelen estar bien filtradas)
        "filtrada": [j for j in pool if j.pipeline_status == PipelineStatus.FILTERED.value
                     and not str((j.triage or {}).get("filter_reason", "")).startswith(("ubicación", "publicada", "remota"))],
        "sin_puntuar": [j for j in pool if scored(j) is None and j.pipeline_status == PipelineStatus.CANDIDATE.value],
    }
    quota = {"alto": 5, "medio": 4, "bajo": 2, "filtrada": 2, "sin_puntuar": 2}
    picked: list[Job] = []
    for name, k in quota.items():
        items = buckets[name][:]
        rng.shuffle(items)
        # una por fuente primero, para que haya variedad
        items.sort(key=lambda j: sum(1 for p in picked if p.source == j.source))
        picked += [j for j in items if j not in picked][:k]
    boring = lambda j: j.pipeline_status == PipelineStatus.FILTERED.value and str(  # noqa: E731
        (j.triage or {}).get("filter_reason", "")).startswith(("ubicación", "publicada", "remota"))
    rest = [j for j in pool if j not in picked and not boring(j)]
    rng.shuffle(rest)
    picked += rest[: max(0, n - len(picked))]
    return picked[:n]


CALIBRATE_SYSTEM = """Ayudas a un candidato a definir qué trabajo busca de verdad, a partir de las ofertas que ha
votado (👍 le interesa / 👎 no le interesa) y de su CV.
- Deduce patrones: puestos, nivel, tipo de empresa o sector, modalidad, salario, tecnologías, idioma.
- Sé concreto y prudente: no inventes preferencias que los votos no respalden. Si algo no está claro, déjalo vacío.
- Mantén lo que ya tenía en su perfil ideal salvo que los votos lo contradigan claramente.
- Propón también búsquedas cortas para los portales (en el idioma que se indica en cada campo)."""


def calibrate(llm: LLMClient, settings: Settings, cv: CVExtraction, prefs: SearchPreferences,
              voted: list[tuple[Job, str, str | None]], notes: str = "") -> CalibrationOut:
    lines = []
    for job, vote, reason in voted:
        mark = {"like": "👍", "dislike": "👎"}.get(vote)
        if not mark:
            continue
        lines.append(f"{mark} {job.title} — {job.company or '?'} — {job.location or '?'} ({job.source})"
                     + (f" · motivo: {reason}" if reason else "") + f"\n   {(job.raw_text or '')[:500]}")
    country = (country_info(prefs.country) or {}).get("name")
    prompt = (
        f"<cv>\n{cv.model_dump_json(include={'headline', 'summary', 'seniority', 'years_experience', 'hard_skills', 'experience', 'location'})}\n</cv>\n"
        f"<perfil_ideal_actual>\n{prefs.ideal.model_dump_json()}\n</perfil_ideal_actual>\n"
        + (f"<pais>{country}</pais>\n" if country else "")
        + f"<votos>\n" + "\n".join(lines) + "\n</votos>\n"
        + (f"<comentarios_del_candidato>\n{notes}\n</comentarios_del_candidato>\n" if notes.strip() else "")
        + "\nActualiza su perfil ideal y propón búsquedas."
    )
    return llm.structured(system=CALIBRATE_SYSTEM, prompt=prompt, schema=CalibrationOut, max_tokens=6000)


QUERIES_SYSTEM = """Propones búsquedas para los portales de empleo de un candidato, a partir de su CV y de lo que busca.
Búsquedas cortas (1-3 palabras), las que usaría un reclutador: títulos y sinónimos reales del mercado,
no frases largas. Evita términos que traigan puestos que el candidato no quiere."""


def suggest_queries(llm: LLMClient, settings: Settings, cv: CVExtraction, prefs: SearchPreferences) -> QueriesProposal:
    country = (country_info(prefs.country) or {}).get("name") or "su país"
    prompt = (f"<cv>\n{cv.model_dump_json(include={'headline', 'summary', 'hard_skills', 'seniority'})}\n</cv>\n"
              f"<lo_que_busca>\n{ideal_text(prefs) or '(sin definir: dedúcelo del CV)'}\n</lo_que_busca>\n"
              f"<busquedas_actuales>\n{prefs.sources.model_dump_json(include={'getonbrd_queries', 'remotive_queries', 'adzuna_queries'})}\n</busquedas_actuales>\n"
              f"País: {country}. Propón las búsquedas.")
    return llm.structured(system=QUERIES_SYSTEM, prompt=prompt, schema=QueriesProposal,
                          model=settings.llm_fast_model, effort="low", max_tokens=2000)


def apply_queries(prefs: SearchPreferences, q: QueriesProposal) -> SearchPreferences:
    prefs = prefs.model_copy(deep=True)
    clean = lambda xs, n: list(dict.fromkeys(x.strip() for x in xs if x.strip()))[:n]  # noqa: E731
    if q.getonbrd:
        prefs.sources.getonbrd_queries = clean(q.getonbrd, 4)
    if q.remotive:
        prefs.sources.remotive_queries = clean(q.remotive, 3)
    if q.adzuna and prefs.sources.adzuna_queries is not None:
        prefs.sources.adzuna_queries = clean(q.adzuna, 3) if prefs.sources.adzuna_queries or prefs.country in (None, "MX", "BR", "ES") else []
    return prefs


def merge_ideal(current: IdealProfile, proposed: IdealProfile) -> IdealProfile:
    """El perfil propuesto manda, pero lo que el usuario escribió a mano en notas se conserva."""
    merged = proposed.model_copy()
    if current.notes.strip() and current.notes.strip() not in merged.notes:
        merged.notes = (current.notes.strip() + ("\n" + merged.notes if merged.notes.strip() else "")).strip()
    return merged


# ── Análisis final con un modelo mejor (con tope diario) ───────


def deep_model_for_today(db: Session, prefs: SearchPreferences, now: datetime | None = None) -> str | None:
    """Modelo para el análisis final de la próxima oferta: el elegido, hasta el tope diario; luego, el normal."""
    from ..models import LLMUsage

    if not prefs.deep_model or prefs.deep_daily_cap <= 0:
        return None
    now = now or datetime.now(timezone.utc)
    start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    used = len(db.exec(select(LLMUsage.id).where(LLMUsage.model == prefs.deep_model, LLMUsage.purpose == "Análisis de ofertas",
                                                 LLMUsage.created_at >= start)).all())
    return prefs.deep_model if used < prefs.deep_daily_cap else None
