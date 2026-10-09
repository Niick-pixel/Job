"""Entrevistas y seguimiento: calendario (.ics), dossier de preparación y correos de seguimiento.

Fechas: las que no llevan zona horaria son hora local del usuario (lo que escribió o lo que decía el
correo). En el .ics se emiten como hora «flotante», que Calendario interpreta en la zona del Mac.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr

from ..schemas import (CVExtraction, InterviewPrepOut, JobExtraction, MessageDraft, MockStep, MockTurn, NegotiationOut,
                       OfferComparison, OfferDetails)
from .llm import LLMClient

# ── Calendario ──────────────────────────────────────────────────


def _ics_escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545: líneas de máx. 75 octetos; las continuaciones empiezan por un espacio."""
    out, current = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(current) + len(b) > (75 if not out else 74):
            out.append(current.decode("utf-8"))
            current = b""
        current += b
    out.append(current.decode("utf-8"))
    return "\r\n ".join(out)


def _ics_time(dt: datetime) -> str:
    if dt.tzinfo is None:
        return dt.strftime("%Y%m%dT%H%M%S")  # hora local flotante
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(*, uid: str, start: datetime, summary: str, description: str = "", url: str | None = None,
              duration_minutes: int = 60, alarm_minutes: int = 60, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    end = start + timedelta(minutes=duration_minutes)
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JobTracker AI//ES", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_ics_time(now)}",
        f"DTSTART:{_ics_time(start)}",
        f"DTEND:{_ics_time(end)}",
        f"SUMMARY:{_ics_escape(summary)}",
        f"DESCRIPTION:{_ics_escape(description)}",
    ]
    if url:
        lines.append(f"URL:{url}")
    lines += [
        "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_escape(summary)}", f"TRIGGER:-PT{alarm_minutes}M", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR",
    ]
    return "\r\n".join(_fold(ln) for ln in lines) + "\r\n"


# ── Contacto ────────────────────────────────────────────────────

_NO_REPLY = re.compile(r"no-?reply|do-?not-?reply|notifications?@|mailer", re.I)


def contact_from_senders(senders: list[str]) -> str | None:
    """El remitente humano más reciente de la empresa (no los «no-reply»)."""
    for sender in senders:
        _, addr = parseaddr(sender)
        if addr and "@" in addr and not _NO_REPLY.search(addr):
            return addr
    return None


# ── IA: dossier y correos ───────────────────────────────────────

PREP_SYSTEM = """Preparas a un candidato para una entrevista de trabajo concreta.
Reglas:
- Basa las respuestas sugeridas SOLO en experiencia real del CV. Si el CV no tiene un ejemplo para
  una pregunta, dilo y sugiere cómo responder con honestidad (experiencia transferible, aprendizaje).
- Sobre la empresa usa la oferta y lo que sepas; si no estás seguro, dilo y recomienda verificarlo.
- Sé concreto y práctico: 6-10 preguntas probables (técnicas y de comportamiento), 4-8 temas técnicos,
  4-6 preguntas para el entrevistador.
- Escribe en el idioma de la oferta."""

MESSAGE_SYSTEM = """Redactas correos breves y profesionales de un candidato a una empresa.
Reglas:
- 80-140 palabras, tono cordial y directo, sin servilismo ni frases hechas.
- No inventes nada: usa solo datos del CV, de la oferta y del contexto que se te da.
- Termina con el nombre del candidato. Escribe en el idioma de la oferta."""

MESSAGE_KIND = {
    "seguimiento": "Correo de seguimiento: el candidato aplicó hace {days} días y no ha recibido respuesta. "
                   "Reafirma el interés con un dato concreto de su perfil que encaje con el puesto y pregunta por el estado del proceso.",
    "agradecimiento": "Nota de agradecimiento tras la entrevista ({when}). Agradece el tiempo, menciona un punto "
                      "concreto del puesto que le motiva y reafirma el interés.",
}


def prepare_interview(llm: LLMClient, cv: CVExtraction, job: JobExtraction | None, job_text: str) -> InterviewPrepOut:
    offer = job.model_dump_json(indent=1) if job else job_text[:20_000]
    return llm.structured(
        system=PREP_SYSTEM,
        prompt=f"<oferta>\n{offer}\n</oferta>\n\n<cv>\n{cv.model_dump_json(indent=1)}\n</cv>\n\nPrepara el dossier de la entrevista.",
        schema=InterviewPrepOut, max_tokens=12_000,
    )


def draft_message(llm: LLMClient, kind: str, cv: CVExtraction, job_title: str, company: str | None,
                  days: int | None = None, when: str | None = None, notes: str | None = None,
                  market: str = "") -> MessageDraft:
    instruction = MESSAGE_KIND[kind].format(days=days or "varios", when=when or "reciente")
    context = f"Puesto: {job_title}\nEmpresa: {company or '—'}\n" + (f"Notas del candidato: {notes}\n" if notes else "") \
        + (f"Costumbres del país: {market}\n" if market else "")
    return llm.structured(
        system=MESSAGE_SYSTEM,
        prompt=f"{instruction}\n\n<contexto>\n{context}</contexto>\n\n<cv_resumen>\n{cv.full_name or ''}\n{cv.summary}\n</cv_resumen>",
        schema=MessageDraft, effort="low", max_tokens=3000,
    )


# ── Simulacro de entrevista ─────────────────────────────────────

MOCK_SYSTEM = """Eres un entrevistador profesional que hace un simulacro de entrevista para un puesto concreto,
y a la vez un coach que evalúa cada respuesta.
Reglas:
- Una pregunta cada vez, como en una entrevista real. Mezcla comportamiento (método STAR), técnica del
  puesto y motivación. Si la última respuesta fue vaga, puedes hacer UNA repregunta para profundizar.
- Evalúa con exigencia pero con tacto. En preguntas de comportamiento revisa STAR (situación, tarea,
  acción propia, resultado concreto). En técnicas, corrección y claridad.
- La «respuesta mejorada» usa SOLO hechos de la respuesta del candidato y de su CV: no inventes cifras,
  empresas ni logros. Si falta un dato (p. ej. un resultado medible), indícalo entre corchetes: [cifra].
- Escribe en el idioma de la oferta. Sé breve: es un ejercicio práctico."""


def mock_step(llm: LLMClient, cv: CVExtraction, job_title: str, company: str | None, job_text: str,
              prep: dict | None, history: list[MockTurn], current_question: str | None, answer: str | None,
              total: int, finish: bool) -> MockStep:
    done = len(history) + (1 if answer else 0)
    if finish or done >= total:
        instruction = ("Evalúa la última respuesta (si la hay) y TERMINA la entrevista: next_question = null y "
                       "escribe summary con una valoración global y las 3 prioridades para mejorar.")
    elif current_question and answer:
        instruction = (f"Evalúa la última respuesta y haz la pregunta {done + 1} de {total}. "
                       "No repitas preguntas ya hechas.")
    else:
        instruction = f"Empieza la entrevista: saluda en una frase y haz la pregunta 1 de {total} (feedback = null)."
    likely = "\n".join(f"- {q['question']}" for q in (prep or {}).get("likely_questions", [])[:10])
    past = "\n\n".join(f"P{i + 1}: {t.question}\nR: {t.answer}" for i, t in enumerate(history))
    prompt = (
        f"<puesto>{job_title} en {company or 'la empresa'}</puesto>\n<oferta>\n{job_text[:6000]}\n</oferta>\n"
        f"<cv>\n{cv.model_dump_json(include={'full_name', 'headline', 'summary', 'experience', 'hard_skills'})}\n</cv>\n"
        + (f"<preguntas_probables>\n{likely}\n</preguntas_probables>\n" if likely else "")
        + (f"<entrevista_hasta_ahora>\n{past}\n</entrevista_hasta_ahora>\n" if past else "")
        + (f"<ultima_pregunta>{current_question}</ultima_pregunta>\n<ultima_respuesta>\n{answer}\n</ultima_respuesta>\n"
           if current_question and answer else "")
        + f"\n{instruction}"
    )
    step = llm.structured(system=MOCK_SYSTEM, prompt=prompt, schema=MockStep, max_tokens=6000, effort="low",
                          cache_system=True)
    if finish or done >= total:
        step.next_question = None
    return step


# ── Ofertas: negociación y comparación ─────────────────────────

NEGOTIATION_SYSTEM = """Eres un asesor de carrera que ayuda a negociar una oferta de trabajo con honestidad y buen tono.
Reglas:
- No inventes ofertas de otras empresas, cifras de mercado exactas ni logros. Si das un rango de mercado,
  dilo como estimación aproximada y recomienda contrastarlo (p. ej. con portales salariales o personas del sector).
- Apóyate en hechos del CV y de la oferta. Prioriza 2-4 peticiones realistas; no todo es salario
  (teletrabajo, fecha de incorporación, formación, revisión salarial a 6 meses…).
- El correo: cordial, agradecido, concreto, 120-180 palabras, firmado con el nombre del candidato.
- Escribe en el idioma de la oferta."""

COMPARE_SYSTEM = """Comparas ofertas de trabajo de un candidato de forma clara y honesta.
Considera dinero total (fijo + variable), modalidad, crecimiento, encaje con su perfil y sus prioridades,
estabilidad y lo que falte por aclarar. No inventes datos que no estén en las ofertas; si falta algo, dilo."""


def offer_annual(offer: dict) -> float | None:
    """Total bruto anual: fijo (×12 si es mensual, +1 mes de aguinaldo si lo hay) + variable."""
    o = OfferDetails.model_validate(offer or {})
    base = o.base_salary or 0
    if o.period == "mensual":
        base = base * (13 if o.thirteenth else 12)
    total = base + (o.variable or 0)
    return total or None


def offer_text(offer: dict) -> str:
    o = OfferDetails.model_validate(offer or {})
    total = offer_annual(offer) or 0
    lines = [f"Fijo: {o.base_salary:,.0f} {o.currency} brutos {'al mes' if o.period == 'mensual' else 'al año'}"
             + (" + aguinaldo (un salario extra al año)" if o.thirteenth else "") if o.base_salary else None,
             f"Variable: {o.variable:,.0f} {o.currency}" if o.variable else None,
             f"Total anual estimado: {total:,.0f} {o.currency}" if total else None,
             f"Equity: {o.equity}" if o.equity else None, f"Modalidad: {o.modality}" if o.modality else None,
             f"Vacaciones: {o.vacation_days} días" if o.vacation_days else None,
             f"Incorporación: {o.start_date}" if o.start_date else None,
             f"Plazo para responder: {o.deadline}" if o.deadline else None,
             f"Beneficios: {o.benefits}" if o.benefits else None, f"Notas: {o.notes}" if o.notes else None]
    return "\n".join(x for x in lines if x) or "Sin condiciones apuntadas"


def negotiate(llm: LLMClient, cv: CVExtraction, job_title: str, company: str | None, job_text: str, offer: dict,
              target: str | None, priorities: list[str], market: str = "") -> NegotiationOut:
    prompt = ((f"<mercado>\n{market}\n</mercado>\n" if market else "") +f"<puesto>{job_title} en {company or 'la empresa'}</puesto>\n<oferta_publicada>\n{job_text[:5000]}\n</oferta_publicada>\n"
              f"<condiciones_ofrecidas>\n{offer_text(offer)}\n</condiciones_ofrecidas>\n"
              f"<cv>\n{cv.model_dump_json(include={'full_name', 'headline', 'years_experience', 'seniority', 'summary', 'experience', 'hard_skills', 'location'})}\n</cv>\n"
              + (f"<objetivo_del_candidato>{target}</objetivo_del_candidato>\n" if target else "")
              + (f"<prioridades>{', '.join(priorities)}</prioridades>\n" if priorities else "")
              + "\nPrepara la negociación.")
    return llm.structured(system=NEGOTIATION_SYSTEM, prompt=prompt, schema=NegotiationOut, max_tokens=8000)


def compare_offers(llm: LLMClient, cv: CVExtraction, offers: list[dict], priorities: list[str],
                   market: str = "") -> OfferComparison:
    blocks = "\n\n".join(f"<oferta application_id=\"{o['application_id']}\">\n{o['title']} en {o['company'] or '—'}\n"
                          f"{offer_text(o['offer'])}\n</oferta>" for o in offers)
    prompt = ((f"<mercado>\n{market}\n</mercado>\n" if market else "") + f"{blocks}\n\n<perfil>{cv.headline or ''} · {cv.summary}</perfil>\n"
              + (f"<prioridades>{', '.join(priorities)}</prioridades>\n" if priorities else "")
              + "\nCompara las ofertas (una entrada por oferta, con su application_id) y recomienda.")
    return llm.structured(system=COMPARE_SYSTEM, prompt=prompt, schema=OfferComparison, max_tokens=6000)
