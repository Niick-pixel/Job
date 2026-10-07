"""Matchmaking CV ↔ oferta.

El score final combina:
  * el juicio holístico de la IA (contexto, seniority, experiencia transferible), y
  * una cobertura de skills determinista (qué % de requisitos obligatorios aparece en el CV),
para que el número sea explicable y no dependa únicamente del modelo.
"""
import json
import re

from ..schemas import CVExtraction, JobExtraction, MatchAnalysis
from .llm import LLMClient

MATCH_SYSTEM = """Eres un reclutador técnico senior que evalúa la compatibilidad entre un candidato y una oferta.
Sé honesto y concreto: cita evidencias del CV para cada punto fuerte, y para cada brecha
indica si es bloqueante o fácil de cerrar. Valora la experiencia transferible (p. ej. Flask → FastAPI).
Escala del score: 85-100 excelente, 70-84 bueno, 50-69 parcial, <50 bajo."""

_ALIASES = {
    "js": "javascript", "ts": "typescript", "postgres": "postgresql", "k8s": "kubernetes",
    "golang": "go", "node": "node.js", "nodejs": "node.js", "react.js": "react", "reactjs": "react",
    "aws cloud": "aws", "amazon web services": "aws", "gcp": "google cloud", "ml": "machine learning",
}


def normalize_skill(skill: str) -> str:
    s = re.sub(r"\s*\(.*?\)", "", skill.strip().lower())
    return _ALIASES.get(s, s)


def skills_coverage(cv: CVExtraction, job: JobExtraction) -> tuple[float, list[str], list[str]]:
    """Devuelve (cobertura 0-1, requisitos cubiertos, requisitos no encontrados)."""
    required = [r for r in job.required_skills if r.strip()]
    if not required:
        return 1.0, [], []

    cv_skills = {normalize_skill(s) for s in cv.hard_skills + cv.technologies}
    for exp in cv.experience:
        cv_skills.update(normalize_skill(t) for t in exp.technologies)
    cv_blob = " ".join(cv_skills)

    covered, missing = [], []
    for req in required:
        n = normalize_skill(req)
        # coincidencia exacta o como palabra dentro de otra skill ("aws" en "aws lambda")
        if n in cv_skills or re.search(rf"(?<![\w+#.]){re.escape(n)}(?![\w+#])", cv_blob):
            covered.append(req)
        else:
            missing.append(req)
    return len(covered) / len(required), covered, missing


def evaluate_match(
    llm: LLMClient, cv: CVExtraction, job: JobExtraction, cv_text: str, llm_weight: float = 0.7
) -> tuple[float, float, MatchAnalysis]:
    """Devuelve (score combinado 0-100, cobertura 0-1, análisis de la IA)."""
    coverage, covered, missing = skills_coverage(cv, job)
    prompt = (
        "<perfil_candidato>\n" + cv.model_dump_json(indent=1) + "\n</perfil_candidato>\n\n"
        "<cv_original>\n" + cv_text[:30_000] + "\n</cv_original>\n\n"
        "<oferta>\n" + job.model_dump_json(indent=1) + "\n</oferta>\n\n"
        "<cobertura_automatica>\n"
        + json.dumps({"cubiertos": covered, "no_encontrados_literalmente": missing}, ensure_ascii=False)
        + "\n</cobertura_automatica>\n\n"
        "La cobertura automática es literal: revisa si los 'no encontrados' están cubiertos "
        "con otro nombre o con experiencia equivalente. Evalúa la compatibilidad."
    )
    analysis = llm.structured(system=MATCH_SYSTEM, prompt=prompt, schema=MatchAnalysis)
    llm_score = max(0, min(100, analysis.score))
    combined = round(llm_weight * llm_score + (1 - llm_weight) * coverage * 100, 1)
    return combined, coverage, analysis
