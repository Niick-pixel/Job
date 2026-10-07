"""Esquemas Pydantic: salidas estructuradas de la IA y contratos de la API."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from .models import ApplicationStatus

# ── Salidas estructuradas de la IA ──────────────────────────────


class Experience(BaseModel):
    role: str
    company: str
    start: str | None = Field(None, description="Fecha de inicio tal como aparece (ej. '2021-03' o 'Mar 2021')")
    end: str | None = Field(None, description="Fecha de fin o 'Actualidad'")
    highlights: list[str] = Field(default_factory=list, description="Viñetas/logros tal como están en el CV")
    technologies: list[str] = Field(default_factory=list)


class CVExtraction(BaseModel):
    full_name: str | None
    headline: str | None = Field(None, description="Titular profesional en una línea")
    years_experience: float | None = Field(None, description="Años totales de experiencia profesional")
    seniority: Literal["junior", "mid", "senior", "lead", "unknown"]
    hard_skills: list[str] = Field(description="Habilidades técnicas, normalizadas (ej. 'Python', 'SQL')")
    soft_skills: list[str]
    technologies: list[str] = Field(description="Herramientas, frameworks, plataformas")
    languages: list[str] = Field(description="Idiomas con nivel, ej. 'Inglés (C1)'")
    education: list[str]
    certifications: list[str]
    experience: list[Experience]
    summary: str = Field(description="Resumen del perfil en 2-3 frases")


class JobExtraction(BaseModel):
    title: str
    company: str | None
    location: str | None
    modality: Literal["remoto", "híbrido", "presencial", "desconocido"]
    seniority: Literal["junior", "mid", "senior", "lead", "unknown"]
    required_skills: list[str] = Field(description="Requisitos obligatorios, normalizados")
    nice_to_have_skills: list[str]
    keywords: list[str] = Field(description="Palabras clave ATS más importantes de la oferta")
    responsibilities: list[str]
    salary_range: str | None
    posted_date: date | None = Field(None, description="Fecha de publicación si aparece explícita o deducible (ISO)")
    posted_relative: str | None = Field(None, description="Texto relativo de publicación si aparece, ej. 'hace 3 días'")
    applicants_count: int | None = Field(None, description="Número de candidatos si la oferta lo indica")


class MatchAnalysis(BaseModel):
    score: int = Field(description="Compatibilidad global 0-100")
    verdict: Literal["excelente", "bueno", "parcial", "bajo"]
    strengths: list[str] = Field(description="Puntos fuertes concretos del candidato para esta oferta")
    gaps: list[str] = Field(description="Requisitos que faltan o son débiles")
    improvement_tips: list[str] = Field(description="Acciones concretas para cerrar las brechas")
    matched_keywords: list[str]
    missing_keywords: list[str]
    summary: str


class BulletSuggestion(BaseModel):
    original: str
    improved: str
    keywords_added: list[str]
    reason: str


class OptimizationResult(BaseModel):
    bullet_suggestions: list[BulletSuggestion]
    suggested_headline: str
    cover_letter: str
    honesty_warnings: list[str] = Field(
        description="Keywords que NO conviene añadir porque el CV no aporta evidencia"
    )


class EmailClassification(BaseModel):
    category: Literal["entrevista", "rechazo", "confirmacion_recepcion", "oferta", "solicitud_info", "otro"]
    confidence: float = Field(description="0-1")
    company: str | None
    job_title: str | None
    interview_datetime: datetime | None = Field(None, description="Fecha/hora propuesta si es entrevista")
    action_required: str | None = Field(None, description="Qué debe hacer el usuario, si algo")
    summary: str


# ── Contratos de la API ─────────────────────────────────────────


class Urgency(BaseModel):
    level: Literal["ideal", "buena", "competida", "tardía", "probablemente_cerrada", "desconocida"]
    days_since_posted: int | None
    score: int = Field(description="0-100: cuanto más alto, más merece la pena aplicar YA")
    message: str


class JobCreate(BaseModel):
    text: str | None = None
    url: str | None = None
    posted_date: date | None = None
    applicants_count: int | None = None


class JobRead(BaseModel):
    id: int
    title: str
    company: str | None
    location: str | None
    source_url: str | None
    posted_date: date | None
    details: dict
    urgency: dict


class MatchRead(BaseModel):
    id: int
    cv_id: int
    job_id: int
    score: float
    llm_score: int
    skills_coverage: float
    analysis: MatchAnalysis


class ApplicationRead(BaseModel):
    id: int
    job_id: int
    status: ApplicationStatus
    notes: str | None
    applied_at: datetime | None
    interview_at: datetime | None
    job_title: str
    company: str | None
    match_score: float | None = None
    urgency_level: str | None = None


class ApplicationUpdate(BaseModel):
    status: ApplicationStatus | None = None
    notes: str | None = None
    interview_at: datetime | None = None


class EmailIn(BaseModel):
    message_id: str
    sender: str
    subject: str
    body: str
    received_at: datetime | None = None
