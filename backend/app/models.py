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
    interview_at: datetime | None = None
    updated_at: datetime = Field(default_factory=_now)


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
