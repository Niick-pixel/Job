"""«¿Por qué no vi esta oferta?»: sigue una oferta por el recorrido del agente y dice dónde se quedó.

1. ¿Ya la conoce? → en qué paso está y por qué (filtro, puntuación, en tu Bandeja…).
2. Si no: ¿alguna de tus fuentes cubre esa web? (si no, cómo añadirla)
3. Simulación: lee la oferta, aplica tus filtros y la criba de la IA, y dice qué habría pasado.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx
from sqlmodel import Session, select

from ..config import Settings, get_settings
from ..models import Job, PipelineStatus
from ..schemas import SearchPreferences
from .llm import LLMClient

ALERT_ONLY = {"linkedin.com": "LinkedIn", "computrabajo.com": "Computrabajo", "indeed.com": "Indeed",
              "elempleo.com": "elempleo", "empleos.net": "Empleos.net", "bumeran": "Bumeran", "infojobs.net": "InfoJobs",
              "glassdoor": "Glassdoor", "occ.com.mx": "OCC"}

STAGE_TEXT = {
    PipelineStatus.FILTERED.value: "La descartó un filtro automático",
    PipelineStatus.LOW_SCORE.value: "La IA la puntuó por debajo de tu umbral",
    PipelineStatus.CANDIDATE.value: "Pasó la criba y está en cola para el análisis completo",
    PipelineStatus.IN_INBOX.value: "Está en tu Bandeja, lista para revisar",
    PipelineStatus.APPROVED.value: "La aprobaste: está en tu Kanban",
    PipelineStatus.DISCARDED.value: "La descartaste tú",
    PipelineStatus.MANUAL.value: "La añadiste tú a mano",
}


def _norm_url(url: str) -> str:
    u = urlparse(url.strip())
    return f"{u.netloc.lower().removeprefix('www.')}{u.path.rstrip('/')}"


def find_job(db: Session, url: str) -> Job | None:
    key = _norm_url(url)
    if not key:
        return None
    for j in db.exec(select(Job).where(Job.source_url.is_not(None) | Job.apply_url.is_not(None))).all():
        for u in (j.source_url, j.apply_url):
            if u and (_norm_url(u) == key or (len(key) > 20 and (key in _norm_url(u) or _norm_url(u) in key))):
                return j
    return None


def coverage(url: str, prefs: SearchPreferences) -> dict:
    """¿Alguna de las fuentes configuradas cubre esta web?"""
    from .discovery import parse_url

    host = urlparse(url).netloc.lower()
    for dom, name in ALERT_ONLY.items():
        if dom in host:
            return {"status": "warn", "detail": f"{name} no tiene API pública: sus ofertas solo llegan por las alertas de "
                    f"empleo en tu correo (conecta Gmail y crea alertas en {name}) o con el botón «Guardar en JobTracker».",
                    "action": {"type": "route", "route": "ajustes", "label": "Conectar Gmail"}}
    found = parse_url(url)
    if not found:
        return {"status": "warn", "detail": "Ninguna de tus fuentes cubre esta web. Puedes guardarla con el botón del "
                "navegador o añadir la oferta a mano (abajo).", "action": None}
    provider, slug = found
    configured = getattr(prefs.sources, provider, [])
    if provider == "workday":
        ok = any(slug.lower().rstrip("/") in u.lower() for u in configured)
    else:
        ok = slug.lower() in {c.lower() for c in configured}
    if ok:
        return {"status": "ok", "detail": f"La cubre tu fuente {provider} · {slug}", "action": None}
    return {"status": "error", "detail": f"Es de {provider.capitalize()} ({slug}), pero esa empresa no está en tus fuentes.",
            "action": {"type": "add_source", "provider": provider, "slug": slug, "label": "Añadir esta empresa"}}


def trace(db: Session, llm: LLMClient, client: httpx.Client, prefs: SearchPreferences, url: str | None,
          text: str | None, settings: Settings | None = None) -> dict:
    from ..schemas import CVExtraction
    from ..models import CVProfile
    from .agent import _triage_system, hard_filter, triage_jobs
    from .job_ingest import analyze_job
    from .sources import RawJob, page_text
    from .targeting import feedback_examples

    settings = settings or get_settings()
    steps: list[dict] = []
    if url:
        job = find_job(db, url)
        if job:
            t = job.triage or {}
            reason = t.get("filter_reason") or t.get("reason")
            score = t.get("match_score") or t.get("score")
            steps.append({"stage": "Encontrada", "status": "ok",
                          "detail": f"El agente ya la conoce (fuente: {job.source}, vista el {job.created_at:%d/%m})."})
            status = "ok" if job.pipeline_status in (PipelineStatus.IN_INBOX.value, PipelineStatus.APPROVED.value,
                                                     PipelineStatus.CANDIDATE.value) else "error"
            detail = STAGE_TEXT.get(job.pipeline_status, job.pipeline_status)
            if reason:
                detail += f": {reason}"
            if score is not None and job.pipeline_status == PipelineStatus.LOW_SCORE.value:
                detail += f" (puntuación {round(score)}; tu umbral es {prefs.triage_threshold} en la criba y {prefs.prepare_threshold} para preparar)"
            steps.append({"stage": "Dónde se quedó", "status": status, "detail": detail})
            return {"known": True, "job_id": job.id, "steps": steps, "verdict": detail,
                    "can_prepare": job.pipeline_status in (PipelineStatus.FILTERED.value, PipelineStatus.LOW_SCORE.value,
                                                           PipelineStatus.CANDIDATE.value)}
        cov = coverage(url, prefs)
        steps.append({"stage": "¿Tus fuentes la cubren?", **cov})

    body = (text or "").strip()
    if not body and url:
        body = page_text(client, url)
        if len(body) < 200:
            steps.append({"stage": "Leer la oferta", "status": "error",
                          "detail": "No pude leer la página (puede pedir iniciar sesión). Pega el texto de la oferta y vuelve a probar."})
            return {"known": False, "steps": steps, "verdict": "No se pudo leer la oferta", "can_prepare": False}
    if not body:
        return {"known": False, "steps": steps, "verdict": "Pega un enlace o el texto de la oferta", "can_prepare": False}
    steps.append({"stage": "Leer la oferta", "status": "ok", "detail": f"Leída ({len(body):,} caracteres)".replace(",", ".")})

    details = analyze_job(llm, body[:20_000])
    raw = RawJob(source="trace", external_id="trace", title=details.title, company=details.company,
                 location=details.location, url=url, description=body,
                 posted_date=details.posted_date, remote=details.modality == "remoto")
    reason = hard_filter(raw, prefs)
    if reason:
        steps.append({"stage": "Tus filtros", "status": "error", "detail": f"La habría descartado: {reason}.",
                      "hint": _filter_hint(reason)})
        return {"known": False, "steps": steps, "verdict": f"Tus filtros la descartarían: {reason}",
                "title": details.title, "company": details.company, "can_prepare": True, "text": body[:20_000]}
    steps.append({"stage": "Tus filtros", "status": "ok", "detail": "Pasa tus filtros (ubicación, antigüedad, exclusiones…)."})

    cv_row = db.exec(select(CVProfile).order_by(CVProfile.created_at.desc())).first()
    if not cv_row:
        return {"known": False, "steps": steps, "verdict": "Sube tu CV para simular la criba", "can_prepare": False}
    fake = Job(id=-1, title=details.title, company=details.company, location=details.location, raw_text=body)
    system = _triage_system(CVExtraction.model_validate(cv_row.profile), prefs, feedback_examples(db))
    score, why = triage_jobs(llm, settings, system, [fake]).get(-1, (0, "sin respuesta"))
    ok = score >= prefs.triage_threshold
    steps.append({"stage": "Criba de la IA", "status": "ok" if ok else "error",
                  "detail": f"Puntuación {score} (umbral {prefs.triage_threshold}): {why}",
                  "hint": None if ok else "Si te parece un error, vótala 👍 al añadirla: el agente aprende de tus votos."})
    verdict = ("Habría pasado la criba: probablemente no la viste porque ninguna fuente la trajo." if ok and url
               else "Habría pasado la criba." if ok else f"La IA la habría descartado ({score}): {why}")
    return {"known": False, "steps": steps, "verdict": verdict, "title": details.title, "company": details.company,
            "can_prepare": True, "text": body[:20_000], "score": score}


def _filter_hint(reason: str) -> str | None:
    if reason.startswith("ubicación"):
        return "Añade esa ciudad en «Ubicaciones» o activa «Acepto remoto»."
    if reason.startswith("publicada hace"):
        return "Sube «Antigüedad máxima (días)» en Agente."
    if reason.startswith("contiene"):
        return "Quita esa palabra de «Excluir si contiene»."
    if reason.startswith("es un puesto que no buscas"):
        return "Revisa «Puestos que NO quieres» en tu perfil ideal."
    if reason.startswith("remota, pero"):
        return "Es remota solo para otra región: normalmente no podrías aplicar."
    if reason.startswith("salario"):
        return "Baja el salario mínimo si te interesa igualmente."
    if re.search(r"lista negra", reason):
        return "Quita la empresa de «Empresas a evitar»."
    return None
