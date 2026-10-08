"""Tablas de la base de datos."""
from datetime import date, datetime, timezone
from enum import Enum

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ApplicationStatus(str, Enum):
    TO_APPLY = "por_aplicar"
    APPLIED = "aplicado"
    INTERVIEW = "entrevista"
    REJECTED = "rechazado"


class PipelineStatus(str, Enum):
    """Recorrido de una oferta descubierta por el agente (las añadidas a mano son MANUAL)."""
    MANUAL = "manual"
    FILTERED = "filtrada"          # no pasa los filtros duros (salario, ubicación, lista negra…)
    LOW_SCORE = "criba_baja"       # la criba rápida con IA la puntúa por debajo del umbral
    CANDIDATE = "candidata"        # pasa la criba; pendiente de análisis completo
    IN_INBOX = "en_bandeja"        # candidatura preparada, esperando tu aprobación
    APPROVED = "aprobada"
    DISCARDED = "descartada"


class CVProfile(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    filename: str
    raw_text: str
    full_name: str | None = None
    headline: str | None = None
    years_experience: float | None = None
    # Perfil estructurado completo devuelto por la IA (ver schemas.CVExtraction)
    profile: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


class Job(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    company: str | None = None
    location: str | None = None
    source_url: str | None = None
    raw_text: str
    posted_date: date | None = None
    applicants_count: int | None = None
    details: dict = Field(default_factory=dict, sa_column=Column(JSON))
    urgency: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # Descubrimiento automático
    source: str = "manual"                       # manual | greenhouse | lever | ashby | remotive | adzuna | email
    external_id: str | None = Field(default=None, index=True)
    fingerprint: str | None = Field(default=None, index=True)  # empresa+título+ubicación normalizados
    apply_url: str | None = None
    pipeline_status: str = PipelineStatus.MANUAL.value
    triage: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


class MatchResult(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    cv_id: int = Field(foreign_key="cvprofile.id")
    job_id: int = Field(foreign_key="job.id")
    score: float
    result: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


class Application(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", unique=True)
    status: ApplicationStatus = ApplicationStatus.TO_APPLY
    notes: str | None = None
    applied_at: datetime | None = None
    # Las fechas «sin zona» son hora local del usuario (lo que escribe o lo que dice el correo)
    interview_at: datetime | None = None
    follow_up_at: datetime | None = None  # último seguimiento enviado
    updated_at: datetime = Field(default_factory=_now)


class InterviewPrep(SQLModel, table=True):
    """Dossier de preparación de una entrevista (generado por la IA)."""
    id: int | None = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="application.id", unique=True)
    content: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


class EmailEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    message_id: str = Field(unique=True, index=True)
    sender: str
    subject: str
    received_at: datetime | None = None
    category: str
    confidence: float
    application_id: int | None = Field(default=None, foreign_key="application.id")
    analysis: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


class SearchPreferencesRow(SQLModel, table=True):
    """Fila única con las preferencias de búsqueda (ver schemas.SearchPreferences)."""
    id: int | None = Field(default=1, primary_key=True)
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=_now)


class AgentRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    trigger: str = "manual"  # manual | schedule
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None
    status: str = "running"  # running | ok | error
    stats: dict = Field(default_factory=dict, sa_column=Column(JSON))
    error: str | None = None


class ApplicationPackage(SQLModel, table=True):
    """Candidatura lista para revisar: CV adaptado, carta y respuestas."""
    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", unique=True)
    cv_id: int = Field(foreign_key="cvprofile.id")
    status: str = "pendiente"  # pendiente | aprobada | descartada | enviada
    headline: str | None = None
    cover_letter: str = ""
    bullets: list = Field(default_factory=list, sa_column=Column(JSON))
    answers: list = Field(default_factory=list, sa_column=Column(JSON))
    honesty_warnings: list = Field(default_factory=list, sa_column=Column(JSON))
    cv_pdf_path: str | None = None
    created_at: datetime = Field(default_factory=_now)
    decided_at: datetime | None = None
    decision_reason: str | None = None


class AnswerBankEntry(SQLModel, table=True):
    """Respuestas del usuario a preguntas de filtro habituales; la IA solo las adapta."""
    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(unique=True, index=True)
    question: str
    answer: str = ""
    updated_at: datetime = Field(default_factory=_now)


class Feedback(SQLModel, table=True):
    """Decisiones del usuario en la bandeja: enseñan a la criba qué le interesa."""
    id: int | None = Field(default=None, primary_key=True)
    job_id: int | None = Field(default=None, foreign_key="job.id")
    decision: str  # aprobada | descartada
    reason: str | None = None
    title: str = ""
    company: str | None = None
    created_at: datetime = Field(default_factory=_now)
