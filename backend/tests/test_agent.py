"""Fases 1 y 2: fuentes, filtros, criba, agente completo, bandeja, PDF y migración."""
import json
import re
from datetime import date, datetime, timedelta, timezone

import httpx
import pdfplumber
import pytest
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app import schemas
from app.config import get_settings
from app.database import add_missing_columns
from app.models import AgentRun, Application, ApplicationPackage, CVProfile, EmailEvent, Feedback, Job, PipelineStatus
from app.schemas import EmailIn, SearchPreferences, SourcesConfig
from app.services import sources
from app.services.agent import fingerprint, hard_filter, run_agent, save_preferences
from app.services.packages import prepare_package

from .conftest import FAKE_CV, FAKE_JOB, FakeLLM

TODAY = date.today()
ISO = (TODAY - timedelta(days=2)).isoformat()

GREENHOUSE = {"jobs": [
    {"id": 101, "title": "Backend Engineer (Python)", "updated_at": f"{ISO}T10:00:00-04:00",
     "location": {"name": "Madrid, Spain"}, "absolute_url": "https://boards.greenhouse.io/acme/jobs/101",
     "content": "&lt;p&gt;Build APIs with &lt;strong&gt;FastAPI&lt;/strong&gt;&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;&lt;/ul&gt;"},
    {"id": 102, "title": "Sales Manager", "updated_at": f"{ISO}T10:00:00Z",
     "location": {"name": "Madrid"}, "absolute_url": "https://boards.greenhouse.io/acme/jobs/102", "content": "Sell"},
]}
LEVER = [{
    "id": "abc-1", "text": "Platform Engineer", "createdAt": int(datetime(TODAY.year, TODAY.month, TODAY.day,
                                                                          tzinfo=timezone.utc).timestamp() * 1000),
    "categories": {"location": "Remote - EU", "commitment": "Full-time", "team": "Infra"},
    "descriptionPlain": "Kubernetes and AWS.", "lists": [{"text": "Requirements", "content": "<li>Docker</li>"}],
    "additionalPlain": "", "hostedUrl": "https://jobs.lever.co/orbit/abc-1", "applyUrl": "https://jobs.lever.co/orbit/abc-1/apply",
    "workplaceType": "remote", "salaryRange": {"min": 50000, "max": 65000, "currency": "EUR", "interval": "per-year-salary"},
}]
ASHBY = {"jobs": [{
    "id": "z9", "title": "Data Engineer", "location": "Barcelona", "publishedAt": f"{ISO}T08:00:00.000Z",
    "jobUrl": "https://jobs.ashbyhq.com/datanova/z9", "applyUrl": "https://jobs.ashbyhq.com/datanova/z9/application",
    "descriptionPlain": "Spark, SQL", "isListed": True, "workplaceType": "Hybrid",
    "compensation": {"scrapeableCompensationSalarySummary": "€45K – €55K"},
}]}
REMOTIVE = {"jobs": [{  # la misma oferta que Greenhouse 101, publicada también en Remotive
    "id": 7, "url": "https://remotive.com/remote-jobs/7", "title": "Backend Engineer (Python)",
    "company_name": "Acme", "candidate_required_location": "Madrid, Spain",
    "publication_date": f"{ISO}T00:00:00", "salary": "", "description": "<p>Same job</p>",
}]}


def transport(fail: set[str] = frozenset()):
    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host in fail:
            return httpx.Response(500)
        if host == "boards-api.greenhouse.io" and path.endswith("/acme/jobs"):
            assert request.url.params["content"] == "true"
            return httpx.Response(200, json=GREENHOUSE)
        if host == "api.lever.co" and path.endswith("/orbit"):
            return httpx.Response(200, json=LEVER)
        if host == "api.ashbyhq.com" and path.endswith("/datanova"):
            return httpx.Response(200, json=ASHBY)
        if host == "remotive.com":
            return httpx.Response(200, json=REMOTIVE)
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


CFG = SourcesConfig(greenhouse=["acme"], lever=["orbit"], ashby=["datanova"], remotive_queries=["python"],
                    email_alerts=True)


# ── Fuentes ─────────────────────────────────────────────────────


def test_sources_parse_all_providers():
    jobs, report = sources.collect(transport(), CFG, None)
    assert report == {"greenhouse:acme": 2, "lever:orbit": 1, "ashby:datanova": 1, "remotive:python": 1}
    gh = next(j for j in jobs if j.external_id == "greenhouse:acme:101")
    assert "FastAPI" in gh.description and "<" not in gh.description and "• Python" in gh.description
    assert gh.posted_date == TODAY - timedelta(days=2)
    lv = next(j for j in jobs if j.source == "lever")
    assert lv.remote is True and lv.posted_date == TODAY and "Docker" in lv.description
    assert (lv.salary_min, lv.salary_max) == (50000, 65000)
    ab = next(j for j in jobs if j.source == "ashby")
    assert ab.salary_text == "€45K – €55K" and ab.apply_url.endswith("/application")


def test_failing_source_does_not_stop_others():
    jobs, report = sources.collect(transport(fail={"api.lever.co"}), CFG, None)
    assert report["lever:orbit"].startswith("error")
    assert report["greenhouse:acme"] == 2 and len(jobs) == 4


def test_adzuna_without_credentials_is_reported():
    _, report = sources.collect(transport(), SourcesConfig(adzuna_queries=["python"]), None)
    assert "sin credenciales" in report["adzuna"]


def test_job_alert_detection():
    alert = EmailIn(message_id="1", sender="jobalerts-noreply@linkedin.com", subject="x", body="")
    reply = EmailIn(message_id="2", sender="talento@acme.io", subject="Entrevista", body="")
    assert sources.is_job_alert(alert) and not sources.is_job_alert(reply)


# ── Duplicados y filtros ────────────────────────────────────────


def test_fingerprint_matches_across_sources():
    assert fingerprint("Acme Inc.", "Backend Engineer (Python)", "Madrid, Spain") == \
        fingerprint("ACME", "Backend Engineer", "Madrid")


def _raw(**kw):
    base = dict(source="x", external_id="x:1", title="Backend Engineer", company="Acme", location="Madrid",
                url=None, description="Python", posted_date=TODAY, remote=False)
    return sources.RawJob(**{**base, **kw})


@pytest.mark.parametrize("prefs,raw,expected", [
    (SearchPreferences(), _raw(), None),
    (SearchPreferences(max_age_days=10), _raw(posted_date=TODAY - timedelta(days=40)), "publicada"),
    (SearchPreferences(blacklist_companies=["acme"]), _raw(), "lista negra"),
    (SearchPreferences(target_titles=["data engineer"]), _raw(), "puestos objetivo"),
    (SearchPreferences(exclude_keywords=["guardias"]), _raw(description="Incluye guardias"), "guardias"),
    (SearchPreferences(remote_only=True), _raw(), "no es remota"),
    (SearchPreferences(locations=["Barcelona"]), _raw(), "ubicación"),
    (SearchPreferences(locations=["Barcelona"]), _raw(remote=True, location="Remote - EU"), None),
    (SearchPreferences(min_salary=60000), _raw(salary_max=45000), "salario"),
])
def test_hard_filter(prefs, raw, expected):
    reason = hard_filter(raw, prefs, TODAY)
    assert (reason is None) if expected is None else (expected in reason)


# ── Agente completo ─────────────────────────────────────────────


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "generated_dir", tmp_path / "generated")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(CVProfile(filename="cv.txt", raw_text="Desarrollé una API REST con Flask", full_name="Nicolás",
                              profile=FAKE_CV.model_dump(mode="json")))
        session.commit()
        yield session


def agent_llm() -> FakeLLM:
    llm = FakeLLM()

    def triage(system, prompt):
        refs = re.findall(r"^\[(\d+)\] (.+?) —", prompt, re.M)
        return schemas.TriageBatch(items=[
            schemas.TriageItem(ref=int(r), score=90 if "Backend" in t or "Platform" in t else 20, reason="motivo")
            for r, t in refs
        ])

    llm.responses[schemas.TriageBatch] = triage
    llm.responses[schemas.OptimizationResult] = schemas.OptimizationResult(
        bullet_suggestions=[schemas.BulletSuggestion(
            original="Desarrollé una API REST con Flask", improved="Diseñé una API REST en Python (Flask→FastAPI-ready)",
            keywords_added=["Python"], reason="keyword")],
        suggested_headline="Backend Engineer · Python", cover_letter="Estimado equipo…", honesty_warnings=["Kubernetes"])
    llm.responses[schemas.TailoredAnswers] = lambda system, prompt: schemas.TailoredAnswers(answers=[
        schemas.TailoredAnswer(key="expectativa_salarial", question="¿Salario?", answer="50.000 € brutos/año")])
    llm.responses[schemas.AlertExtraction] = schemas.AlertExtraction(jobs=[
        schemas.AlertJob(title="Python Developer", company="Fintechly", location="Madrid",
                         url="https://linkedin.com/jobs/view/1", snippet="Python, Django")])
    return llm


def test_agent_end_to_end(db):
    from app.models import AnswerBankEntry
    from app.services.packages import seed_answer_bank

    seed_answer_bank(db)
    entry = db.exec(select(AnswerBankEntry).where(AnswerBankEntry.key == "expectativa_salarial")).one()
    entry.answer = "50.000 €"
    db.add(entry)
    save_preferences(db, SearchPreferences(prepare_threshold=70, deep_match_top_n=5, sources=CFG))
    llm = agent_llm()
    alert = EmailIn(message_id="alert-1", sender="jobalerts-noreply@linkedin.com",
                    subject="Nuevas ofertas", body="Python Developer - Fintechly - Madrid")

    run = run_agent(db, llm, get_settings(), http_client=transport(), email_loader=lambda: [alert],
                    prepare=prepare_package)
    assert run.status == "ok", run.error
    s = run.stats
    assert s["descubiertas"] == 6 and s["duplicadas"] == 1  # Remotive repite la de Greenhouse
    assert s["fuentes"]["email"] == 1
    # Sales Manager, Data Engineer y Python Developer (alerta) caen en la criba; Backend y Platform pasan
    assert s["criba_baja"] == 3 and s["analizadas"] == 2 and s["preparadas"] == 2

    # La criba usa el modelo rápido, esfuerzo bajo y el perfil cacheado
    triage_kwargs = [k for c, k in zip(llm.calls, llm.kwargs) if c is schemas.TriageBatch]
    assert triage_kwargs and all(k["model"] == "claude-haiku-5-5" and k["cache_system"] for k in triage_kwargs)

    pkgs = db.exec(select(ApplicationPackage)).all()
    assert len(pkgs) == 2
    pkg = pkgs[0]
    assert {a["key"] for a in pkg.answers if a["answer"]} == {"expectativa_salarial"}
    assert any(a["answer"] is None for a in pkg.answers)  # las demás quedan pendientes, no inventadas
    with pdfplumber.open(pkg.cv_pdf_path) as pdf:
        text = "\n".join(p.extract_text() for p in pdf.pages)
    assert "Nicolás Ejemplo" in text and "Backend Engineer · Python" in text
    assert "Diseñé una API REST en Python" in text

    jobs = db.exec(select(Job)).all()
    assert next(j for j in jobs if j.title == "Sales Manager").pipeline_status == PipelineStatus.LOW_SCORE.value
    assert [j.pipeline_status for j in jobs].count(PipelineStatus.IN_INBOX.value) == 2
    assert db.exec(select(EmailEvent).where(EmailEvent.category == "alerta_empleo")).one()
    assert not db.exec(select(Application)).all()  # nada entra al Kanban sin tu aprobación

    # Segunda pasada: todo es duplicado; no se re-puntúa ni se re-extrae la alerta
    calls_before = len(llm.calls)
    run2 = run_agent(db, llm, get_settings(), http_client=transport(), email_loader=lambda: [alert],
                     prepare=prepare_package)
    assert run2.stats["nuevas"] == 0 and run2.stats["duplicadas"] == 5
    assert len(llm.calls) == calls_before


def test_agent_without_cv_reports_error(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        run = run_agent(session, agent_llm(), get_settings(), http_client=transport())
        assert run.status == "error" and "CV" in run.error


def test_disabled_agent_does_nothing(db):
    save_preferences(db, SearchPreferences(enabled=False, sources=CFG))
    llm = agent_llm()
    run = run_agent(db, llm, get_settings(), http_client=transport())
    assert run.status == "ok" and not llm.calls and not db.exec(select(Job)).all()


# ── Bandeja vía API ─────────────────────────────────────────────


def test_inbox_decisions_and_learning(client, fake_llm, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "generated_dir", tmp_path / "gen")
    fake_llm.responses.update(agent_llm().responses)
    with open(tmp_path / "cv.txt", "w") as f:
        f.write("x" * 100)
    with open(tmp_path / "cv.txt", "rb") as f:
        cv = client.post("/api/cv", files={"file": ("cv.txt", f, "text/plain")}).json()
    job = client.post("/api/jobs", json={"text": "Backend en Acme"}).json()

    pkg = client.post(f"/api/jobs/{job['id']}/prepare", params={"cv_id": cv["id"]}).json()
    assert pkg["status"] == "pendiente" and pkg["headline"] == "Backend Engineer · Python"
    pdf = client.get(f"/api/packages/{pkg['id']}/cv.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert [p["id"] for p in client.get("/api/packages").json()] == [pkg["id"]]

    r = client.post(f"/api/packages/{pkg['id']}/decision", json={"decision": "enviada", "cover_letter": "Editada"})
    assert r.json()["status"] == "enviada" and r.json()["cover_letter"] == "Editada"
    board = client.get("/api/applications/board").json()
    assert len(board["aplicado"]) == 1

    # Respuestas: siembra + edición
    answers = client.get("/api/answers").json()
    assert any(a["key"] == "por_que_empresa" for a in answers)
    client.put("/api/answers", json={"key": "por_que_empresa", "question": "¿Por qué?", "answer": "Producto"})
    assert next(a for a in client.get("/api/answers").json() if a["key"] == "por_que_empresa")["answer"] == "Producto"


def test_discard_feeds_next_triage(db):
    save_preferences(db, SearchPreferences(sources=CFG))
    db.add(Feedback(decision="descartada", reason="no quiero consultoras", title="Dev", company="BigConsulting"))
    db.commit()
    llm = agent_llm()
    systems = []
    original = llm.responses[schemas.TriageBatch]
    llm.responses[schemas.TriageBatch] = lambda system, prompt: (systems.append(system), original(system, prompt))[1]
    run_agent(db, llm, get_settings(), http_client=transport())
    assert systems and "no quiero consultoras" in systems[0]


# ── Migración de esquema (instalaciones OTA existentes) ────────


def test_old_database_gets_new_columns(tmp_path):
    path = tmp_path / "old.db"
    old = sa_create_engine(f"sqlite:///{path}")
    with old.begin() as conn:  # tabla job tal como la creaba la v0.2.0
        conn.execute(text("CREATE TABLE job (id INTEGER PRIMARY KEY, title VARCHAR NOT NULL, company VARCHAR, "
                          "location VARCHAR, source_url VARCHAR, raw_text VARCHAR NOT NULL, posted_date DATE, "
                          "applicants_count INTEGER, details JSON, urgency JSON, created_at DATETIME NOT NULL)"))
        conn.execute(text("INSERT INTO job (title, raw_text, details, urgency, created_at) "
                          "VALUES ('Antigua', 'x', '{}', '{}', '2026-01-01')"))
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)
    add_missing_columns(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("job")}
    assert {"source", "pipeline_status", "fingerprint", "triage", "apply_url"} <= cols
    with Session(engine) as s:
        job = s.exec(select(Job)).one()
        assert job.title == "Antigua" and job.pipeline_status == "manual" and job.source == "manual"
    add_missing_columns(engine)  # idempotente
