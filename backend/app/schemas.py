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
    email: str | None = None
    phone: str | None = None
    location: str | None = Field(None, description="Ciudad/país de residencia")
    links: list[str] = Field(default_factory=list, description="LinkedIn, GitHub, portfolio…")
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
    clear_interview: bool = False


# ── Entrevistas y seguimiento (0.6.0) ──────────────────────────


class PrepQuestion(BaseModel):
    question: str
    why: str = Field(description="Por qué es probable que la pregunten en esta entrevista")
    answer_outline: str = Field(description="Esquema de respuesta (STAR) usando SOLO experiencia real del CV")


class InterviewPrepOut(BaseModel):
    company_summary: str = Field(description="Qué hace la empresa y el equipo, según la oferta y lo que sepas (avisa si puede estar desactualizado)")
    role_focus: list[str] = Field(description="Lo que la entrevista va a evaluar, según la oferta")
    likely_questions: list[PrepQuestion]
    technical_topics: list[str] = Field(description="Temas técnicos concretos que conviene repasar")
    questions_to_ask: list[str] = Field(description="Preguntas inteligentes para hacer al entrevistador")
    weak_spots: list[str] = Field(description="Brechas del perfil frente a la oferta y cómo abordarlas con honestidad")
    checklist: list[str] = Field(description="Logística y preparación práctica antes de la entrevista")


class MessageDraft(BaseModel):
    subject: str
    body: str


class MessageIn(BaseModel):
    kind: Literal["seguimiento", "agradecimiento"]


# ── Simulacro de entrevista (0.7.0) ────────────────────────────


class StarCheck(BaseModel):
    situation: bool = Field(description="Sitúa el contexto")
    task: bool = Field(description="Explica su responsabilidad o el reto")
    action: bool = Field(description="Detalla lo que hizo él/ella (no el equipo)")
    result: bool = Field(description="Da un resultado concreto, idealmente medible")


class MockFeedback(BaseModel):
    score: int = Field(ge=1, le=5, description="1 = floja, 3 = correcta, 5 = excelente")
    star: StarCheck | None = Field(None, description="Solo en preguntas de comportamiento/experiencia; null en técnicas")
    strengths: list[str] = Field(description="1-3 cosas que hizo bien")
    improve: list[str] = Field(description="1-3 mejoras concretas")
    better_answer: str = Field(description="Versión mejorada, breve, usando SOLO hechos de su respuesta y de su CV")


class MockStep(BaseModel):
    feedback: MockFeedback | None = Field(None, description="Evaluación de la última respuesta (null al empezar)")
    next_question: str | None = Field(None, description="Siguiente pregunta; null si la entrevista termina")
    question_kind: Literal["comportamiento", "técnica", "motivación", "repregunta"] | None = None
    summary: str | None = Field(None, description="Solo al terminar: valoración global y 3 prioridades para mejorar")


class MockTurn(BaseModel):
    question: str
    answer: str = Field(max_length=6000)
    feedback: MockFeedback | None = None


class MockIn(BaseModel):
    history: list[MockTurn] = Field(default_factory=list, max_length=20)
    current_question: str | None = None
    answer: str | None = Field(None, max_length=6000)
    finish: bool = False
    total: int = Field(6, ge=3, le=12)


class EmailIn(BaseModel):
    message_id: str
    sender: str
    subject: str
    body: str
    received_at: datetime | None = None
    thread_id: str | None = None
    rfc_message_id: str | None = None


# ── Ofertas y negociación (0.7.0) ──────────────────────────────


class OfferDetails(BaseModel):
    base_salary: float | None = Field(None, ge=0, description="Salario fijo bruto (anual o mensual según period)")
    period: Literal["anual", "mensual"] = "anual"
    thirteenth: bool = Field(False, description="Aguinaldo / 13.er salario (en Costa Rica es obligatorio)")
    variable: float | None = Field(None, ge=0, description="Variable/bonus anual bruto esperado")
    currency: str = "EUR"
    equity: str | None = None
    modality: str | None = None
    vacation_days: int | None = Field(None, ge=0, le=60)
    start_date: str | None = None
    deadline: str | None = None
    benefits: str | None = None
    notes: str | None = None


class NegotiationAsk(BaseModel):
    item: str = Field(description="Qué se pide (salario, variable, teletrabajo, fecha, formación…)")
    ask: str = Field(description="La petición concreta")
    rationale: str = Field(description="Argumento basado en el CV, la oferta o el mercado (sin inventar datos)")


class NegotiationOut(BaseModel):
    assessment: str = Field(description="Valoración honesta de la oferta frente al puesto, el perfil y el mercado")
    leverage: list[str] = Field(description="Puntos fuertes reales del candidato para negociar")
    asks: list[NegotiationAsk]
    risks: list[str] = Field(description="Riesgos y cómo no tensar la relación")
    call_script: list[str] = Field(description="Guion breve si la negociación es por teléfono")
    email: MessageDraft


class NegotiateIn(BaseModel):
    target: str | None = Field(None, max_length=200, description="Lo que te gustaría conseguir")
    priorities: list[str] = Field(default_factory=list, max_length=8)


class OfferScore(BaseModel):
    application_id: int
    pros: list[str]
    cons: list[str]
    score: int = Field(ge=1, le=10)


class OfferComparison(BaseModel):
    offers: list[OfferScore]
    recommendation: str
    questions_to_clarify: list[str]


class GmailDraftIn(BaseModel):
    to: str = Field(max_length=300)
    subject: str = Field(max_length=300)
    body: str = Field(max_length=20_000)


# ── Agente de búsqueda (Fase 1) ────────────────────────────────


class SourcesConfig(BaseModel):
    greenhouse: list[str] = Field(default_factory=list, description="board tokens: boards.greenhouse.io/<token>")
    lever: list[str] = Field(default_factory=list, description="empresas: jobs.lever.co/<empresa>")
    ashby: list[str] = Field(default_factory=list, description="organizaciones: jobs.ashbyhq.com/<org>")
    remotive_queries: list[str] = Field(default_factory=list, description="búsquedas en Remotive (remoto)")
    adzuna_queries: list[str] = Field(default_factory=list, description="búsquedas en Adzuna (requiere API key)")
    adzuna_country: str = "es"
    email_alerts: bool = True
    # Latinoamérica / Costa Rica (0.8.0)
    workday: list[str] = Field(default_factory=list, description="URLs de webs de empleo Workday: empresa.wd1.myworkdayjobs.com/Sitio")
    smartrecruiters: list[str] = Field(default_factory=list, description="empresas en SmartRecruiters (filtradas por tu país)")
    recruitee: list[str] = Field(default_factory=list, description="empresas: <empresa>.recruitee.com")
    breezy: list[str] = Field(default_factory=list, description="empresas: <empresa>.breezy.hr")
    workable: list[str] = Field(default_factory=list, description="cuentas: apply.workable.com/<cuenta>")
    getonbrd_queries: list[str] = Field(default_factory=list, description="búsquedas en Get on Board (tecnología, LatAm)")
    himalayas: bool = False
    amazon: bool = False


class SearchPreferences(BaseModel):
    enabled: bool = True
    target_titles: list[str] = Field(default_factory=list, description="El título debe contener alguno (vacío = todos)")
    exclude_keywords: list[str] = Field(default_factory=list, description="Descarta si el título/texto contiene alguno")
    locations: list[str] = Field(default_factory=list, description="Ciudades/países aceptados (vacío = todos)")
    remote_ok: bool = True
    remote_only: bool = False
    min_salary: int | None = Field(None, description="Salario anual mínimo; solo filtra si la oferta lo indica")
    blacklist_companies: list[str] = Field(default_factory=list)
    max_age_days: int = 30
    triage_threshold: int = 65
    deep_match_top_n: int = 10
    prepare_threshold: int = 75
    max_triage_per_run: int = 150
    digest_enabled: bool = True
    digest_hour: int = Field(9, ge=0, le=23, description="Hora local del resumen diario")
    interview_reminders: bool = True
    country: str | None = Field(None, description="ISO de 2 letras de tu país (p. ej. CR): filtra remotos y adapta salarios")
    region_checked: bool = False  # 0.8.0: se dedujo una vez el país del CV en instalaciones ya configuradas
    monthly_budget_usd: float | None = Field(None, ge=0, le=1000,
                                             description="Tope de gasto en IA al mes: al alcanzarlo el agente se pausa")
    sources: SourcesConfig = Field(default_factory=SourcesConfig)


class PreferencesProposal(BaseModel):
    """Configuración inicial que la IA deduce del CV (el usuario puede editarla después)."""
    locations: list[str] = Field(description="Ciudad y país del candidato, en español e inglés (p. ej. Madrid, España, Spain)")
    remote_ok: bool
    exclude_keywords: list[str] = Field(description="Exclusiones obvias por seniority (p. ej. prácticas, internship)")
    remotive_queries: list[str] = Field(description="1-3 búsquedas cortas en inglés para un portal remoto, p. ej. 'python backend'")
    adzuna_queries: list[str] = Field(description="1-3 búsquedas cortas de puesto en el idioma del país del candidato")
    adzuna_country: str = Field(description="Código ISO de 2 letras del país del candidato en minúscula, p. ej. 'es'")
    country: str | None = Field(None, description="Código ISO de 2 letras del país de residencia del candidato en MAYÚSCULA, p. ej. 'CR'")
    getonbrd_queries: list[str] = Field(default_factory=list,
                                        description="Si su perfil es tecnológico: 1-3 búsquedas cortas en inglés, p. ej. 'python'; si no, vacío")


class TriageItem(BaseModel):
    ref: int = Field(description="Número de la oferta en la lista recibida")
    score: int = Field(description="Encaje 0-100")
    reason: str = Field(description="Una frase: por qué encaja o no")


class TriageBatch(BaseModel):
    items: list[TriageItem]


class AlertJob(BaseModel):
    title: str
    company: str | None
    location: str | None
    url: str | None
    snippet: str | None = Field(None, description="Texto de la oferta que aparezca en el correo")


class AlertExtraction(BaseModel):
    jobs: list[AlertJob]


# ── Candidaturas preparadas (Fase 2) ───────────────────────────


class TailoredAnswer(BaseModel):
    key: str
    question: str
    answer: str = Field(description="Respuesta adaptada a la oferta, basada SOLO en la respuesta base del usuario")


class TailoredAnswers(BaseModel):
    answers: list[TailoredAnswer]


class PackageDecision(BaseModel):
    decision: Literal["aprobada", "descartada", "enviada"]
    reason: str | None = None
    cover_letter: str | None = None


class AnswerIn(BaseModel):
    key: str
    question: str
    answer: str = ""
