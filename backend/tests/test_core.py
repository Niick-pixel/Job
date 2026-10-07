from datetime import date, timedelta
from pathlib import Path

import pytest

from app.services.cv_parser import CVParseError, extract_text
from app.services.matcher import skills_coverage
from app.services.urgency import assess_urgency

from .conftest import FAKE_CV, FAKE_JOB

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


@pytest.mark.parametrize(
    "days,level",
    [(0, "ideal"), (3, "ideal"), (5, "buena"), (10, "competida"), (20, "tardía"), (45, "probablemente_cerrada")],
)
def test_urgency_bands(days, level):
    today = date(2026, 10, 7)
    assert assess_urgency(today - timedelta(days=days), today=today).level == level


def test_urgency_penalizes_saturation():
    today = date(2026, 10, 7)
    calm = assess_urgency(today, applicants_count=10, today=today)
    busy = assess_urgency(today, applicants_count=500, today=today)
    assert busy.score < calm.score


def test_urgency_unknown_date():
    assert assess_urgency(None).level == "desconocida"


def test_skills_coverage_uses_aliases():
    coverage, covered, missing = skills_coverage(FAKE_CV, FAKE_JOB)
    assert "Postgres" in covered  # alias de PostgreSQL
    assert set(missing) == {"FastAPI", "Kubernetes"}
    assert coverage == pytest.approx(3 / 5)


def test_extract_text_rejects_unknown_format():
    with pytest.raises(CVParseError):
        extract_text("cv.docx", b"whatever")


def test_extract_text_txt():
    text = extract_text("cv.txt", (SAMPLES / "sample_cv.txt").read_bytes())
    assert "Flask" in text
