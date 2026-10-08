"""Agente de búsqueda: descubre, filtra, puntúa y prepara candidaturas sin intervención.

Embudo de cada ejecución (de barato a caro):
  1. Fuentes (APIs de ATS/portales + alertas por correo)
  2. Duplicados (id externo y huella empresa+título+ubicación)       → gratis
  3. Filtros duros (antigüedad, lista negra, títulos, ubicación, salario) → gratis
  4. Criba rápida con el modelo rápido, por lotes y con el CV en caché  → céntimos
  5. Análisis completo + compatibilidad solo de las mejores (top N)    → modelo principal
  6. Candidatura preparada (CV en PDF, carta, respuestas) para las que superan el umbral
     → aparecen en la Bandeja para que las apruebes
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from datetime import date, datetime, timezone

import httpx
from sqlmodel import Session, select

from ..config import Settings
from ..models import AgentRun, CVProfile, EmailEvent, Feedback, Job, MatchResult, PipelineStatus, SearchPreferencesRow
from ..schemas import CVExtraction, EmailIn, JobExtraction, PreferencesProposal, SearchPreferences, TriageBatch
from .job_ingest import analyze_job
from .llm import LLMClient, LLMError
from .matcher import evaluate_match
from .notify import notify
from .sources import RawJob, collect, extract_alert_jobs, is_job_alert
from .urgency import assess_urgency

TRIAGE_BATCH = 8

TRIAGE_SYSTEM = """Eres un reclutador que hace una primera criba rápida de ofertas para UN candidato concreto.
Para cada oferta da un score 0-100 de encaje real (rol, seniority, stack, ubicación/modalidad y
las preferencias del candidato) y una frase de motivo. Sé exigente: 80+ solo si encaja de verdad.
Las decisiones anteriores del candidato muestran qué le interesa y qué no: respétalas."""


# ── Preferencias ────────────────────────────────────────────────


def load_preferences(db: Session) -> SearchPreferences:
    row = db.get(SearchPreferencesRow, 1)
    return SearchPreferences.model_validate(row.data) if row else SearchPreferences()


def preferences_configured(db: Session) -> bool:
    return db.get(SearchPreferencesRow, 1) is not None


AUTOCONFIG_SYSTEM = """Propones la configuración inicial de un buscador de empleo a partir del CV del candidato.
Sé conservador: estas reglas descartan ofertas sin pasar por la IA, así que no restrinjas de más.
No propongas títulos de puesto: la criba con IA ya juzga el encaje con el CV completo."""


def autoconfigure_preferences(llm: LLMClient, settings: Settings, cv: CVExtraction,
                              base: SearchPreferences | None = None) -> SearchPreferences:
    """Deduce ubicación, búsquedas y exclusiones del CV para que el agente funcione sin configurar nada."""
    proposal = llm.structured(
        system=AUTOCONFIG_SYSTEM, prompt=f"<cv>\n{cv.model_dump_json(indent=1)}\n</cv>",
        schema=PreferencesProposal, model=settings.llm_fast_model, effort="low", max_tokens=4000,
    )
    prefs = (base or SearchPreferences()).model_copy(deep=True)
    prefs.locations = proposal.locations
    prefs.remote_ok = proposal.remote_ok
    prefs.exclude_keywords = sorted(set(prefs.exclude_keywords) | set(proposal.exclude_keywords))
    prefs.sources.remotive_queries = proposal.remotive_queries[:3]
    prefs.sources.adzuna_queries = proposal.adzuna_queries[:3]
    prefs.sources.adzuna_country = (proposal.adzuna_country or "es").lower()[:2]
    return prefs


def save_preferences(db: Session, prefs: SearchPreferences) -> SearchPreferences:
    row = db.get(SearchPreferencesRow, 1) or SearchPreferencesRow(id=1)
    row.data = prefs.model_dump(mode="json")
    row.updated_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    return prefs


# ── Duplicados y filtros duros ──────────────────────────────────

_COMPANY_SUFFIX = re.compile(r"\b(inc|llc|ltd|gmbh|s\.?l\.?u?|s\.?a\.?|corp|co|group|technologies|labs)\b\.?")


def _norm(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def fingerprint(company: str | None, title: str, location: str | None) -> str:
    comp = _COMPANY_SUFFIX.sub("", _norm(company)).strip()
    city = _norm((location or "").split(",")[0])
    # Lo que va entre paréntesis/corchetes («(Python)», «(m/f/d)») varía entre portales
    title_n = re.sub(r"\b(m f d|h m|f m|m w d)\b", "", _norm(re.sub(r"[(\[].*?[)\]]", " ", title)))
    title_n = re.sub(r"\s+", " ", title_n).strip()
    return f"{comp}|{title_n}|{city}"


def _contains_any(text: str, words: list[str]) -> str | None:
    norm = f" {_norm(text)} "
    for w in words:
        if w.strip() and f" {_norm(w)} " in norm:
            return w
    return None


def hard_filter(job: RawJob, prefs: SearchPreferences, today: date | None = None) -> str | None:
    """Devuelve el motivo de descarte, o None si la oferta pasa."""
    today = today or date.today()
    if job.posted_date and (today - job.posted_date).days > prefs.max_age_days:
        return f"publicada hace {(today - job.posted_date).days} días"
    if job.company and _contains_any(job.company, prefs.blacklist_companies):
        return "empresa en tu lista negra"
    if prefs.target_titles and not _contains_any(job.title, prefs.target_titles):
        return "el título no coincide con tus puestos objetivo"
    if hit := _contains_any(f"{job.title}\n{job.description[:4000]}", prefs.exclude_keywords):
        return f"contiene «{hit}»"
    if prefs.remote_only and job.remote is not True:
        return "no es remota"
    if job.remote is not True or not prefs.remote_ok:
        if prefs.locations and job.location and not _contains_any(job.location, prefs.locations):
            if not (job.remote and prefs.remote_ok):
                return f"ubicación fuera de tus preferencias ({job.location})"
    if prefs.min_salary and job.salary_max and job.salary_max < prefs.min_salary:
        return f"salario máximo {job.salary_max:.0f} < {prefs.min_salary}"
    return None


# ── Criba con IA ────────────────────────────────────────────────


def _triage_system(cv: CVExtraction, prefs: SearchPreferences, feedback: list[Feedback]) -> str:
    """Prefijo estable de la criba (se cachea): instrucciones + perfil + preferencias + decisiones."""
    fb = "\n".join(
        f"- {f.decision.upper()}: {f.title} @ {f.company or '?'}" + (f" — motivo: {f.reason}" if f.reason else "")
        for f in feedback
    ) or "(todavía ninguna)"
    prefs_txt = prefs.model_dump_json(include={"target_titles", "exclude_keywords", "locations", "remote_ok",
                                               "remote_only", "min_salary"})
    return (
        f"{TRIAGE_SYSTEM}\n\n<perfil_candidato>\n{cv.model_dump_json(indent=1)}\n</perfil_candidato>\n\n"
        f"<preferencias>\n{prefs_txt}\n</preferencias>\n\n<decisiones_anteriores>\n{fb}\n</decisiones_anteriores>"
    )


def triage_jobs(llm: LLMClient, settings: Settings, system: str, jobs: list[Job]) -> dict[int, tuple[int, str]]:
    """Puntúa ofertas por lotes con el modelo rápido. Devuelve {job.id: (score, motivo)}."""
    results: dict[int, tuple[int, str]] = {}
    for start in range(0, len(jobs), TRIAGE_BATCH):
        batch = jobs[start:start + TRIAGE_BATCH]
        listing = "\n\n".join(
            f"[{i}] {j.title} — {j.company or '?'} — {j.location or '?'}\n{j.raw_text[:1500]}"
            for i, j in enumerate(batch, 1)
        )
        out = llm.structured(
            system=system, prompt=f"Puntúa estas {len(batch)} ofertas:\n\n{listing}", schema=TriageBatch,
            model=settings.llm_fast_model, effort="low", cache_system=True, max_tokens=8000,
        )
        for item in out.items:
            if 1 <= item.ref <= len(batch):
                results[batch[item.ref - 1].id] = (max(0, min(100, item.score)), item.reason)
    return results


# ── Ejecución completa ──────────────────────────────────────────


def _ingest(db: Session, raw: RawJob, prefs: SearchPreferences, stats: dict) -> Job | None:
    fp = fingerprint(raw.company, raw.title, raw.location)
    if db.exec(select(Job.id).where((Job.external_id == raw.external_id) | (Job.fingerprint == fp))).first():
        stats["duplicadas"] += 1
        return None
    reason = hard_filter(raw, prefs)
    job = Job(
        title=raw.title or "(sin título)", company=raw.company, location=raw.location,
        source_url=raw.url, apply_url=raw.apply_url, raw_text=raw.text, posted_date=raw.posted_date,
        source=raw.source, external_id=raw.external_id, fingerprint=fp,
        urgency=assess_urgency(raw.posted_date).model_dump(),
        pipeline_status=PipelineStatus.FILTERED.value if reason else PipelineStatus.CANDIDATE.value,
        triage={"filter_reason": reason, "remote": raw.remote, "salary": raw.salary_text, **raw.extra},
    )
    db.add(job)
    stats["filtradas" if reason else "nuevas"] += 1
    return None if reason else job


def run_agent(
    db: Session,
    llm: LLMClient,
    settings: Settings,
    *,
    trigger: str = "manual",
    http_client: httpx.Client | None = None,
    email_loader: Callable[[], list[EmailIn]] | None = None,
    prepare: Callable[[Session, LLMClient, Settings, Job, CVProfile], object] | None = None,
) -> AgentRun:
    run = AgentRun(trigger=trigger)
    db.add(run)
    db.commit()
    stats = {"descubiertas": 0, "duplicadas": 0, "filtradas": 0, "nuevas": 0, "criba_baja": 0,
             "analizadas": 0, "preparadas": 0, "fuentes": {}}
    try:
        prefs = load_preferences(db)
        if not prefs.enabled:
            run.status, run.error = "ok", "agente desactivado en preferencias"
            return run
        cv_row = db.exec(select(CVProfile).order_by(CVProfile.created_at.desc())).first()
        if not cv_row:
            raise LLMError("Sube tu CV para que el agente sepa qué buscar")
        cv = CVExtraction.model_validate(cv_row.profile)
        if not preferences_configured(db):  # primera vez: se configura solo a partir del CV
            prefs = save_preferences(db, autoconfigure_preferences(llm, settings, cv))
            stats["autoconfigurado"] = True

        # 1. Fuentes
        raws: list[RawJob] = []
        own_client = http_client is None
        client = http_client or httpx.Client(timeout=20, follow_redirects=True)
        try:
            creds = (settings.adzuna_app_id, settings.adzuna_app_key) if settings.adzuna_app_id and settings.adzuna_app_key else None
            found, report = collect(client, prefs.sources, creds)
            raws.extend(found)
            stats["fuentes"].update(report)
        finally:
            if own_client:
                client.close()
        if prefs.sources.email_alerts and email_loader:
            raws.extend(_collect_alerts(db, llm, settings, email_loader, stats))
        stats["descubiertas"] = len(raws)

        # 2-3. Duplicados + filtros duros (las más recientes primero)
        raws.sort(key=lambda r: r.posted_date or date.min, reverse=True)
        for raw in raws:
            _ingest(db, raw, prefs, stats)
        db.commit()

        # 4. Criba rápida de las candidatas aún sin puntuar
        pending = [j for j in db.exec(select(Job).where(Job.pipeline_status == PipelineStatus.CANDIDATE.value)).all()
                   if "score" not in (j.triage or {})][: prefs.max_triage_per_run]
        if pending:
            feedback = db.exec(select(Feedback).order_by(Feedback.created_at.desc()).limit(30)).all()
            scores = triage_jobs(llm, settings, _triage_system(cv, prefs, feedback), pending)
            for job in pending:
                if job.id not in scores:
                    continue
                score, reason = scores[job.id]
                job.triage = {**job.triage, "score": score, "reason": reason}
                if score < prefs.triage_threshold:
                    job.pipeline_status = PipelineStatus.LOW_SCORE.value
                    stats["criba_baja"] += 1
                db.add(job)
            db.commit()

        # 5. Análisis completo de las mejores (encaje + urgencia)
        candidates = [j for j in db.exec(select(Job).where(Job.pipeline_status == PipelineStatus.CANDIDATE.value)).all()
                      if "score" in (j.triage or {})]
        candidates.sort(key=lambda j: j.triage["score"] * 0.8 + (j.urgency or {}).get("score", 50) * 0.2, reverse=True)
        for job in candidates[: prefs.deep_match_top_n]:
            _deep_analyze(db, llm, settings, job, cv_row, cv, prefs, stats, prepare)
        run.status = "ok"
    except LLMError as e:
        run.status, run.error = "error", str(e)
    finally:
        run.finished_at = datetime.now(timezone.utc)
        run.stats = stats
        db.add(run)
        db.commit()
        db.refresh(run)

    if stats["preparadas"]:
        notify("JobTracker AI", f"{stats['preparadas']} candidatura(s) lista(s) para revisar en la Bandeja")
    return run


def _deep_analyze(db, llm, settings, job: Job, cv_row: CVProfile, cv: CVExtraction,
                  prefs: SearchPreferences, stats: dict, prepare) -> None:
    details = analyze_job(llm, job.raw_text)
    job.details = details.model_dump(mode="json")
    job.title = details.title or job.title
    job.company = details.company or job.company
    job.location = details.location or job.location
    job.posted_date = job.posted_date or details.posted_date
    job.urgency = assess_urgency(job.posted_date, details.applicants_count).model_dump()
    score, coverage, analysis = evaluate_match(llm, cv, details, cv_row.raw_text, settings.match_llm_weight)
    db.add(MatchResult(cv_id=cv_row.id, job_id=job.id, score=score,
                       result={"llm_score": analysis.score, "skills_coverage": coverage, "analysis": analysis.model_dump()}))
    job.triage = {**job.triage, "match_score": score}
    stats["analizadas"] += 1
    if score >= prefs.prepare_threshold and prepare:
        db.add(job)
        db.commit()
        prepare(db, llm, settings, job, cv_row)
        job.pipeline_status = PipelineStatus.IN_INBOX.value
        stats["preparadas"] += 1
    else:
        job.pipeline_status = PipelineStatus.LOW_SCORE.value
        job.triage = {**job.triage, "reason": f"Análisis completo: {score:.0f}% (< {prefs.prepare_threshold})"}
    db.add(job)
    db.commit()


def _collect_alerts(db, llm, settings, email_loader, stats) -> list[RawJob]:
    try:
        emails = [e for e in email_loader() if is_job_alert(e)]
    except Exception as e:  # la bandeja es opcional: un fallo no para el agente
        stats["fuentes"]["email"] = f"error: {e}"
        return []
    jobs: list[RawJob] = []
    for email in emails:
        if db.exec(select(EmailEvent.id).where(EmailEvent.message_id == email.message_id)).first():
            continue
        found = extract_alert_jobs(llm, email, settings.llm_fast_model)
        jobs.extend(found)
        db.add(EmailEvent(message_id=email.message_id, sender=email.sender, subject=email.subject,
                          received_at=email.received_at, category="alerta_empleo", confidence=1.0,
                          analysis={"summary": f"{len(found)} ofertas extraídas de la alerta", "jobs": len(found)}))
    db.commit()
    stats["fuentes"]["email"] = len(jobs)
    return jobs
