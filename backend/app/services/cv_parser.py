"""Extracción de texto del CV (PDF/TXT/MD) y perfilado con IA."""
import io
import re

import pdfplumber

from ..schemas import CVExtraction
from .llm import LLMClient

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}

CV_SYSTEM = """Eres un reclutador técnico experto y un parser de CVs preciso.
Extrae la información del CV sin inventar nada: si un dato no aparece, déjalo vacío o null.
Normaliza los nombres de tecnologías a su forma canónica (p. ej. 'postgres' → 'PostgreSQL',
'js' → 'JavaScript') y no dupliques elementos entre hard_skills y technologies salvo que
sea necesario. Responde en el idioma del CV."""


class CVParseError(ValueError):
    pass


def extract_text(filename: str, content: bytes) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in SUPPORTED_EXTENSIONS:
        raise CVParseError(f"Formato no soportado: {ext or 'sin extensión'}. Usa PDF, TXT o MD.")

    if ext == ".pdf":
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
        except Exception as e:  # pdfplumber lanza varios tipos según la corrupción
            raise CVParseError(f"No se pudo leer el PDF: {e}") from e
        text = "\n\n".join(pages)
    else:
        text = content.decode("utf-8", errors="replace")

    text = _clean(text)
    if len(text) < 50:
        raise CVParseError(
            "El CV no contiene texto extraíble (¿es un PDF escaneado?). "
            "Exporta el CV como PDF con texto o súbelo como .txt."
        )
    return text


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def analyze_cv(llm: LLMClient, cv_text: str) -> CVExtraction:
    return llm.structured(
        system=CV_SYSTEM,
        prompt=f"Analiza este CV y extrae el perfil estructurado.\n\n<cv>\n{cv_text}\n</cv>",
        schema=CVExtraction,
    )
