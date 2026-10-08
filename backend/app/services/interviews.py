"""Entrevistas y seguimiento: calendario (.ics), dossier de preparación y correos de seguimiento.

Fechas: las que no llevan zona horaria son hora local del usuario (lo que escribió o lo que decía el
correo). En el .ics se emiten como hora «flotante», que Calendario interpreta en la zona del Mac.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr

from ..schemas import CVExtraction, InterviewPrepOut, JobExtraction, MessageDraft
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
                  days: int | None = None, when: str | None = None, notes: str | None = None) -> MessageDraft:
    instruction = MESSAGE_KIND[kind].format(days=days or "varios", when=when or "reciente")
    context = f"Puesto: {job_title}\nEmpresa: {company or '—'}\n" + (f"Notas del candidato: {notes}\n" if notes else "")
    return llm.structured(
        system=MESSAGE_SYSTEM,
        prompt=f"{instruction}\n\n<contexto>\n{context}</contexto>\n\n<cv_resumen>\n{cv.full_name or ''}\n{cv.summary}\n</cv_resumen>",
        schema=MessageDraft, effort="low", max_tokens=3000,
    )
