"""Fase 2: candidaturas listas para enviar (CV en PDF adaptado, carta y respuestas).

Principio de honestidad: la IA reordena, reformula y prioriza lo que ya está en tu CV y en
tus respuestas; nunca añade experiencia, cifras ni respuestas que no hayas dado. Lo que no
puede respaldar va a `honesty_warnings`, y las preguntas sin respuesta base quedan marcadas
como pendientes en vez de inventarse.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer
from sqlmodel import Session, select

from ..config import Settings
from ..models import AnswerBankEntry, ApplicationPackage, CVProfile, Job, MatchResult
from ..schemas import CVExtraction, JobExtraction, OptimizationResult, TailoredAnswers
from .llm import LLMClient
from .optimizer import optimize_application

DEFAULT_QUESTIONS = [
    ("por_que_empresa", "¿Por qué quieres trabajar en nuestra empresa?"),
    ("por_que_puesto", "¿Por qué te interesa este puesto?"),
    ("expectativa_salarial", "¿Cuáles son tus expectativas salariales?"),
    ("disponibilidad", "¿Cuándo podrías incorporarte? / Periodo de preaviso"),
    ("permiso_trabajo", "¿Tienes permiso de trabajo en el país? ¿Necesitas visado?"),
    ("modalidad", "¿Qué modalidad prefieres (remoto, híbrido, presencial)?"),
    ("reubicacion", "¿Estarías dispuesto/a a reubicarte?"),
    ("nivel_ingles", "¿Cuál es tu nivel de inglés?"),
    ("logro_destacado", "Describe un logro profesional del que estés orgulloso/a"),
    ("linkedin", "URL de tu perfil de LinkedIn / portfolio"),
]

ANSWERS_SYSTEM = """Adaptas las respuestas de un candidato a preguntas de filtro para una oferta concreta.
Reglas estrictas:
- Usa SOLO los hechos de la respuesta base del candidato y de su CV. No inventes cifras,
  fechas, motivos ni datos personales.
- Puedes conectar la respuesta con la empresa/puesto usando información de la oferta.
- Respuestas breves (1-4 frases), en el idioma de la oferta.
- Datos objetivos (salario, disponibilidad, permiso de trabajo, URLs): cópialos tal cual."""


def seed_answer_bank(db: Session) -> None:
    existing = set(db.exec(select(AnswerBankEntry.key)).all())
    for key, question in DEFAULT_QUESTIONS:
        if key not in existing:
            db.add(AnswerBankEntry(key=key, question=question))
    db.commit()


def tailor_answers(llm: LLMClient, entries: list[AnswerBankEntry], cv: CVExtraction, job: JobExtraction) -> list[dict]:
    answered = [e for e in entries if e.answer.strip()]
    if not answered:
        return []
    base = "\n".join(f"- key={e.key} | {e.question}\n  Respuesta base: {e.answer}" for e in answered)
    out = llm.structured(
        system=ANSWERS_SYSTEM,
        prompt=(f"<oferta>\n{job.model_dump_json(include={'title', 'company', 'responsibilities', 'keywords'})}\n</oferta>\n\n"
                f"<cv_resumen>{cv.summary}</cv_resumen>\n\n<respuestas_base>\n{base}\n</respuestas_base>"),
        schema=TailoredAnswers, effort="low", max_tokens=6000,
    )
    valid = {e.key for e in answered}
    return [a.model_dump() for a in out.answers if a.key in valid]


# ── PDF ─────────────────────────────────────────────────────────


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def build_tailored_cv(cv: CVExtraction, job: JobExtraction, opt: OptimizationResult) -> dict:
    """Combina el CV con las mejoras: viñetas reescritas y skills de la oferta primero."""
    improved = {_norm(b.original): b.improved for b in opt.bullet_suggestions}
    experience = []
    for exp in cv.experience:
        bullets = [improved.get(_norm(h), h) for h in exp.highlights]
        # las viñetas reescritas (más relevantes para la oferta) van primero
        bullets.sort(key=lambda b: b not in improved.values())
        experience.append({**exp.model_dump(), "highlights": bullets})

    keywords = {_norm(k) for k in job.keywords + job.required_skills + job.nice_to_have_skills}
    skills = list(dict.fromkeys(cv.hard_skills + cv.technologies))
    skills.sort(key=lambda s: _norm(s) not in keywords)
    return {
        "name": cv.full_name or "",
        "headline": opt.suggested_headline or cv.headline or "",
        "contact": [x for x in (cv.email, cv.phone, cv.location, *cv.links) if x],
        "summary": cv.summary,
        "experience": experience,
        "skills": skills,
        "education": cv.education,
        "languages": cv.languages,
        "certifications": cv.certifications,
    }


def render_cv_pdf(data: dict, path: Path) -> Path:
    """Plantilla de una columna, sin tablas ni gráficos: la más fácil de leer para un ATS."""
    path.parent.mkdir(parents=True, exist_ok=True)
    accent = colors.HexColor("#3b4fd8")
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=9.5, leading=13, alignment=TA_LEFT)
    name = ParagraphStyle("name", parent=base, fontName="Helvetica-Bold", fontSize=20, leading=24)
    headline = ParagraphStyle("headline", parent=base, fontSize=11.5, textColor=accent, leading=15)
    small = ParagraphStyle("small", parent=base, fontSize=8.5, textColor=colors.HexColor("#555555"))
    h2 = ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=10.5, textColor=accent,
                        spaceBefore=9, spaceAfter=3)
    role = ParagraphStyle("role", parent=base, fontName="Helvetica-Bold", spaceBefore=4)

    def p(text, style=base):
        return Paragraph(escape(text or ""), style)

    def section(title):
        return [p(title.upper(), h2), HRFlowable(width="100%", thickness=0.6, color=accent, spaceAfter=4)]

    story = [p(data["name"], name), p(data["headline"], headline)]
    if data["contact"]:
        story.append(p("  ·  ".join(data["contact"]), small))
    if data["summary"]:
        story += section("Perfil") + [p(data["summary"])]
    if data["experience"]:
        story += section("Experiencia")
        for exp in data["experience"]:
            dates = " – ".join(x for x in (exp.get("start"), exp.get("end")) if x)
            story.append(p(f"{exp['role']} · {exp['company']}" + (f"   ({dates})" if dates else ""), role))
            if exp["highlights"]:
                story.append(ListFlowable(
                    [ListItem(p(h), leftIndent=10) for h in exp["highlights"]],
                    bulletType="bullet", start="•", leftIndent=10, bulletFontSize=8,
                ))
            if exp.get("technologies"):
                story.append(p("Tecnologías: " + ", ".join(exp["technologies"]), small))
    if data["skills"]:
        story += section("Habilidades") + [p(", ".join(data["skills"]))]
    for title, key in (("Formación", "education"), ("Certificaciones", "certifications"), ("Idiomas", "languages")):
        if data[key]:
            story += section(title) + [p(x) for x in data[key]]

    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                      topMargin=15 * mm, bottomMargin=15 * mm,
                      title=f"CV {data['name']}", author=data["name"]).build(story)
    return path


# ── Paquete completo ────────────────────────────────────────────


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _norm(text))[:40].strip("-") or "oferta"


def prepare_package(db: Session, llm: LLMClient, settings: Settings, job: Job, cv_row: CVProfile) -> ApplicationPackage:
    cv = CVExtraction.model_validate(cv_row.profile)
    if not job.details:
        from .job_ingest import analyze_job

        job.details = analyze_job(llm, job.raw_text).model_dump(mode="json")
    details = JobExtraction.model_validate(job.details)

    match = db.exec(select(MatchResult).where(MatchResult.job_id == job.id, MatchResult.cv_id == cv_row.id)
                    .order_by(MatchResult.created_at.desc())).first()
    missing = match.result["analysis"]["missing_keywords"] if match else []
    opt = optimize_application(llm, cv, details, missing)

    seed_answer_bank(db)
    entries = db.exec(select(AnswerBankEntry)).all()
    answers = tailor_answers(llm, entries, cv, details)
    pending = [{"key": e.key, "question": e.question, "answer": None} for e in entries if not e.answer.strip()]

    pdf = render_cv_pdf(build_tailored_cv(cv, details, opt),
                        settings.generated_dir / f"cv_{job.id}_{_slug(details.company or '')}-{_slug(details.title)}.pdf")

    pkg = db.exec(select(ApplicationPackage).where(ApplicationPackage.job_id == job.id)).first() or ApplicationPackage(
        job_id=job.id, cv_id=cv_row.id)
    pkg.cv_id = cv_row.id
    pkg.status = "pendiente"
    pkg.headline = opt.suggested_headline
    pkg.cover_letter = opt.cover_letter
    pkg.bullets = [b.model_dump() for b in opt.bullet_suggestions]
    pkg.answers = answers + pending
    pkg.honesty_warnings = opt.honesty_warnings
    pkg.cv_pdf_path = str(pdf)
    pkg.created_at = datetime.now(timezone.utc)
    pkg.decided_at = pkg.decision_reason = None
    db.add(job)
    db.add(pkg)
    db.commit()
    db.refresh(pkg)
    return pkg
