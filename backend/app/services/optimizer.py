"""Optimización de la candidatura: viñetas adaptadas a keywords y carta de presentación."""
from ..schemas import CVExtraction, JobExtraction, OptimizationResult
from .llm import LLMClient

OPTIMIZER_SYSTEM = """Eres un experto en CVs y sistemas ATS. Reescribe viñetas del CV para una oferta concreta:
- Formato: verbo de acción + qué hiciste + resultado cuantificado cuando el original lo permita.
- Integra keywords de la oferta SOLO si el CV aporta evidencia; nunca inventes experiencia,
  cifras ni tecnologías. Lo que no se pueda respaldar va a honesty_warnings.
- Elige las 5-8 viñetas con más impacto para esta oferta.
La carta de presentación: 250-350 palabras, tono profesional y cercano, específica para la empresa,
con un gancho inicial, 2-3 logros relevantes y un cierre con llamada a la acción.
Escribe en el idioma de la oferta."""


def optimize_application(
    llm: LLMClient, cv: CVExtraction, job: JobExtraction, missing_keywords: list[str] | None = None
) -> OptimizationResult:
    prompt = (
        "<perfil_candidato>\n" + cv.model_dump_json(indent=1) + "\n</perfil_candidato>\n\n"
        "<oferta>\n" + job.model_dump_json(indent=1) + "\n</oferta>\n\n"
        f"<keywords_faltantes>{', '.join(missing_keywords or [])}</keywords_faltantes>\n\n"
        "Propón las viñetas mejoradas, un titular adaptado y la carta de presentación."
    )
    return llm.structured(system=OPTIMIZER_SYSTEM, prompt=prompt, schema=OptimizationResult)
