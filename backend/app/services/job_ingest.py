"""Ingesta de ofertas: desde texto pegado o desde un enlace."""
from datetime import date

import httpx
from bs4 import BeautifulSoup

from ..schemas import JobExtraction
from .llm import LLMClient

JOB_SYSTEM = """Eres un analista de ofertas de empleo. Extrae los datos estructurados de la oferta
sin inventar: si algo no aparece, usa null o lista vacía. Distingue con cuidado entre requisitos
obligatorios y deseables. Para posted_date, conviértelo a fecha ISO solo si es deducible a partir
de la fecha de hoy que se te indica (p. ej. 'hace 3 días')."""

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


class JobFetchError(RuntimeError):
    pass


def fetch_job_text(url: str, timeout: float = 15.0) -> str:
    """Descarga la página y devuelve su texto visible.

    Nota: portales como LinkedIn requieren sesión y suelen bloquear scraping;
    en ese caso, pega el texto de la oferta directamente.
    """
    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise JobFetchError(f"No se pudo descargar la oferta: {e}") from e

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "svg"]):
        tag.decompose()
    text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
    if len(text) < 200:
        raise JobFetchError("La página no tiene suficiente texto (¿requiere login?). Pega el texto de la oferta.")
    return text[:60_000]


def analyze_job(llm: LLMClient, job_text: str, today: date | None = None) -> JobExtraction:
    today = today or date.today()
    return llm.structured(
        system=JOB_SYSTEM,
        prompt=f"Fecha de hoy: {today.isoformat()}\n\n<oferta>\n{job_text}\n</oferta>",
        schema=JobExtraction,
    )
