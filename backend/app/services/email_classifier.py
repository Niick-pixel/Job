"""Clasificación de correos de empresas y vinculación con candidaturas."""
from datetime import date

from ..models import ApplicationStatus
from ..schemas import EmailClassification, EmailIn
from .llm import LLMClient

EMAIL_SYSTEM = """Clasificas correos relacionados con procesos de selección.
- entrevista: invitan a una llamada/entrevista/prueba técnica o piden disponibilidad para ello.
- rechazo: comunican que no siguen adelante (aunque sea con fórmulas amables).
- confirmacion_recepcion: acuse automático de candidatura recibida.
- oferta: oferta formal de empleo.
- solicitud_info: piden documentación o datos adicionales.
- otro: newsletters, alertas de empleo, spam.
Extrae la fecha/hora de entrevista si se propone una concreta (interpreta fechas relativas usando la fecha de hoy)."""

# Qué estado del Kanban implica cada categoría (None = no mover la tarjeta)
CATEGORY_TO_STATUS: dict[str, ApplicationStatus | None] = {
    "entrevista": ApplicationStatus.INTERVIEW,
    "oferta": ApplicationStatus.OFFER,
    "rechazo": ApplicationStatus.REJECTED,
    "confirmacion_recepcion": ApplicationStatus.APPLIED,
    "solicitud_info": None,
    "otro": None,
}


def classify_email(llm: LLMClient, email: EmailIn, today: date | None = None) -> EmailClassification:
    today = today or date.today()
    prompt = (
        f"Fecha de hoy: {today.isoformat()}\n\n"
        f"De: {email.sender}\nAsunto: {email.subject}\n\n<cuerpo>\n{email.body[:20_000]}\n</cuerpo>"
    )
    return llm.structured(system=EMAIL_SYSTEM, prompt=prompt, schema=EmailClassification, max_tokens=4000)
