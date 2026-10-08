"""Abre el formulario de una candidatura en el navegador y lo rellena (no lo envía).

    python -m app.autofill <id_de_candidatura>

Lo lanza la app (botón «Rellenar formulario» en la Bandeja); el estado queda en data/autofill/<id>.json.
"""
import os
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from sqlmodel import Session, select

from .database import engine, init_db
from .models import AnswerBankEntry, ApplicationPackage, CVProfile, Job
from .services.autofill import WORK, build_profile, form_url, run, write_status


def render_letter_pdf(text: str, name: str | None, path: Path) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    style = ParagraphStyle("b", fontName="Helvetica", fontSize=10.5, leading=15)
    story = []
    for para in text.split("\n\n"):
        story += [Paragraph(escape(para).replace("\n", "<br/>"), style), Spacer(1, 8)]
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm, topMargin=22 * mm,
                      bottomMargin=22 * mm, title=f"Carta de presentación{' · ' + name if name else ''}").build(story)
    return path


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    pkg_id = int(args[0])
    init_db()
    with Session(engine) as db:
        pkg = db.get(ApplicationPackage, pkg_id)
        if not pkg:
            write_status(pkg_id, state="error", error="not_found", message="Candidatura no encontrada")
            return 1
        job, cv = db.get(Job, pkg.job_id), db.get(CVProfile, pkg.cv_id)
        url = job.apply_url or job.source_url
        if not url:
            write_status(pkg_id, state="error", error="no_url", message="La oferta no tiene enlace al formulario")
            return 1
        bank = [e.model_dump() for e in db.exec(select(AnswerBankEntry)).all()]
        profile = build_profile(cv.profile or {}, pkg.model_dump(), bank)
        files = {}
        if pkg.cv_pdf_path:
            files["resume"] = pkg.cv_pdf_path
        if pkg.cover_letter.strip():
            WORK.mkdir(parents=True, exist_ok=True)
            files["cover"] = str(render_letter_pdf(pkg.cover_letter, cv.full_name, WORK / f"carta-{pkg_id}.pdf"))
    final = run(pkg_id, form_url(url, job.source), profile, files,
                headless=os.getenv("JOBTRACKER_AUTOFILL_HEADLESS") == "1")
    return 0 if final.get("state") != "error" else 1


if __name__ == "__main__":
    sys.exit(main())
