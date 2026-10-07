"""Fixtures: BD SQLite temporal y un LLM falso (los tests no llaman a la API real)."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app import schemas
from app.database import get_session
from app.main import app
from app.services.llm import get_llm

FAKE_CV = schemas.CVExtraction(
    full_name="Nicolás Ejemplo", headline="Backend Python", years_experience=4, seniority="mid",
    hard_skills=["Python", "SQL", "Flask"], soft_skills=["Comunicación"],
    technologies=["PostgreSQL", "Docker", "AWS", "Redis"], languages=["Español (nativo)"],
    education=["Ing. Informática"], certifications=[],
    experience=[schemas.Experience(role="Backend Developer", company="Logistix",
                                   highlights=["Desarrollé una API REST con Flask"], technologies=["Celery"])],
    summary="Backend con 4 años.",
)
FAKE_JOB = schemas.JobExtraction(
    title="Backend Developer", company="Acme Cloud", location="Madrid", modality="híbrido", seniority="mid",
    required_skills=["Python", "FastAPI", "Postgres", "Docker", "Kubernetes"], nice_to_have_skills=["Kafka"],
    keywords=["Python", "FastAPI", "Kubernetes"], responsibilities=["Diseñar APIs"], salary_range=None,
    posted_date=date.today() - timedelta(days=2), posted_relative="hace 2 días", applicants_count=38,
)
FAKE_MATCH = schemas.MatchAnalysis(
    score=80, verdict="bueno", strengths=["Python sólido"], gaps=["Kubernetes"],
    improvement_tips=["Curso de K8s"], matched_keywords=["Python"], missing_keywords=["Kubernetes"], summary="Buen encaje",
)
FAKE_EMAIL = schemas.EmailClassification(
    category="entrevista", confidence=0.95, company="Acme Cloud", job_title="Backend Developer",
    interview_datetime=None, action_required="Confirmar disponibilidad", summary="Invitación a entrevista",
)


class FakeLLM:
    responses = {
        schemas.CVExtraction: FAKE_CV, schemas.JobExtraction: FAKE_JOB,
        schemas.MatchAnalysis: FAKE_MATCH, schemas.EmailClassification: FAKE_EMAIL,
    }

    def __init__(self):
        self.calls = []

    def structured(self, *, system, prompt, schema, max_tokens=16000):
        self.calls.append(schema)
        return self.responses[schema]


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def client(fake_llm, tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "upload_dir", tmp_path)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_llm] = lambda: fake_llm
    yield TestClient(app)
    app.dependency_overrides.clear()
