"""Filtro de urgencia: ¿todavía merece la pena aplicar a esta oferta?

Es deliberadamente determinista (sin IA): reglas transparentes que el
usuario puede entender y ajustar. Se basa en que la mayoría de procesos
reciben el grueso de candidaturas en los primeros días y que los
reclutadores revisan antes las primeras.
"""
from datetime import date

from ..schemas import Urgency

# (días máximos, nivel, score base, mensaje)
_BANDS = [
    (3, "ideal", 95, "Recién publicada: aplica hoy, las primeras candidaturas se revisan antes."),
    (7, "buena", 80, "Publicada esta semana: buen momento para aplicar."),
    (14, "competida", 60, "Ya lleva un par de semanas: aplica pronto y personaliza mucho la candidatura."),
    (30, "tardía", 35, "Más de dos semanas: probablemente haya una shortlist; considera contactar al reclutador."),
]


def assess_urgency(posted_date: date | None, applicants_count: int | None = None, today: date | None = None) -> Urgency:
    today = today or date.today()

    if posted_date is None:
        return Urgency(
            level="desconocida",
            days_since_posted=None,
            score=50,
            message="No se encontró la fecha de publicación; indícala manualmente para afinar la urgencia.",
        )

    days = max((today - posted_date).days, 0)
    level, score, message = "probablemente_cerrada", 10, "Más de un mes publicada: es probable que el proceso esté avanzado o cerrado."
    for max_days, band_level, band_score, band_msg in _BANDS:
        if days <= max_days:
            level, score, message = band_level, band_score, band_msg
            break

    if applicants_count is not None:
        if applicants_count > 200:
            score -= 25
            message += f" Muy saturada ({applicants_count} candidatos): busca un referido."
        elif applicants_count > 100:
            score -= 10
            message += f" Bastante demanda ({applicants_count} candidatos)."
        elif applicants_count < 25:
            score += 5
            message += f" Pocos candidatos ({applicants_count}): buena oportunidad."

    return Urgency(level=level, days_since_posted=days, score=max(0, min(100, score)), message=message)
