"""0.9.0: perfil ideal, votos, calibración, trazado, búsquedas IA, análisis final, ajustes y seguimientos."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app import schemas
from app.models import Application, ApplicationStatus, EmailEvent, Feedback, Job, LLMUsage, PipelineStatus
from app.schemas import IdealProfile, SearchPreferences
from app.services import targeting, tuning


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _job(db, title, source="getonbrd", status=PipelineStatus.LOW_SCORE.value, score=None, ext=None, **kw):
    j = Job(title=title, company=kw.pop("company", "Acme"), raw_text=f"{title} " * 30, source=source,
            external_id=ext or f"{source}:{title}", pipeline_status=status,
            triage={"score": score} if score is not None else kw.pop("triage", {}), **kw)
    db.add(j)
    db.commit()
    return j


IDEAL = IdealProfile(roles_wanted=["Backend Engineer"], roles_avoid=["Soporte"], seniority=["mid"],
                     min_monthly_salary=2500, salary_currency="USD", modalities=["híbrido", "remoto"],
                     deal_breakers=["turnos de noche"], notes="Producto, no consultoría")

# ── Perfil ideal y votos ────────────────────────────────────────


def test_ideal_text_and_filters():
    prefs = SearchPreferences(ideal=IDEAL)
    t = targeting.ideal_text(prefs)
    assert "Backend Engineer" in t and "2,500 USD brutos al mes" in t and "turnos de noche" in t and "consultoría" in t
    assert targeting.ideal_text(SearchPreferences()) == ""

    from app.services.agent import hard_filter
    from app.services.sources import RawJob
    raw = RawJob(source="x", external_id="1", title="Agente de Soporte Técnico", company="A", location=None, url=None, description="")
    assert hard_filter(raw, prefs) == "es un puesto que no buscas («Soporte»)"


def test_triage_prompt_includes_ideal_and_votes(db):
    from app.services.agent import _triage_system
    from tests.conftest import FAKE_CV

    j = _job(db, "Platform Engineer")
    targeting.record_vote(db, j, "like", "me encanta el stack")
    targeting.record_vote(db, j, "like")  # el último voto reemplaza al anterior
    db.add(Feedback(decision="descartada", reason="Sueldo bajo", title="QA Tester", company="Lowpay"))
    db.commit()
    system = _triage_system(FAKE_CV, SearchPreferences(ideal=IDEAL), targeting.feedback_examples(db))
    assert "<lo_que_busca>" in system and "LE INTERESAN" in system and "Platform Engineer" in system
    assert "NO LE INTERESAN" in system and "Sueldo bajo" in system
    assert len(db.exec(__import__("sqlmodel").select(Feedback).where(Feedback.decision == "like")).all()) == 1


def test_match_prompt_uses_preferences_and_model():
    from app.services.matcher import evaluate_match
    from tests.conftest import FAKE_CV, FAKE_JOB, FAKE_MATCH

    seen = {}

    class LLM:
        def structured(self, **kw):
            seen.update(kw)
            return FAKE_MATCH

    evaluate_match(LLM(), FAKE_CV, FAKE_JOB, "cv", preferences="- Lo descarta: turnos", model="claude-sonnet-5-5")
    assert "<lo_que_busca_el_candidato>" in seen["prompt"] and seen["model"] == "claude-sonnet-5-5"


def test_deep_model_daily_cap(db, monkeypatch):
    prefs = SearchPreferences(deep_model="claude-sonnet-5-5", deep_daily_cap=2)
    now = datetime.now(timezone.utc)
    assert targeting.deep_model_for_today(db, prefs, now) == "claude-sonnet-5-5"
    for _ in range(2):
        db.add(LLMUsage(model="claude-sonnet-5-5", purpose="Análisis de ofertas", created_at=now))
    db.commit()
    assert targeting.deep_model_for_today(db, prefs, now) is None  # tope alcanzado: modelo normal
    assert targeting.deep_model_for_today(db, SearchPreferences(deep_model=None), now) is None


# ── Calibración ─────────────────────────────────────────────────


def test_calibration_sample_is_varied(db):
    for i in range(6):
        _job(db, f"Alta {i}", source=["getonbrd", "himalayas", "workday"][i % 3], status=PipelineStatus.IN_INBOX.value,
             triage={"match_score": 85})
    for i in range(6):
        _job(db, f"Media {i}", score=55)
    for i in range(4):
        _job(db, f"Baja {i}", score=20)
    _job(db, "Filtrada por palabra", status=PipelineStatus.FILTERED.value, triage={"filter_reason": "contiene «junior»"})
    _job(db, "Filtrada por ubicación", status=PipelineStatus.FILTERED.value, triage={"filter_reason": "ubicación fuera"})
    voted = _job(db, "Ya votada", score=90)
    targeting.record_vote(db, voted, "like")
    sample = targeting.calibration_sample(db, n=15, seed=1)
    titles = [j.title for j in sample]
    assert len(sample) == 15 and "Ya votada" not in titles and "Filtrada por ubicación" not in titles
    assert sum(t.startswith("Alta") for t in titles) == 5 and "Filtrada por palabra" in titles
    assert {j.source for j in sample if j.title.startswith("Alta")} == {"getonbrd", "himalayas", "workday"}


def test_calibration_flow(client, fake_llm, tmp_path):
    with open(tmp_path / "cv.txt", "w") as f:
        f.write("x" * 100)
    with open(tmp_path / "cv.txt", "rb") as f:
        client.post("/api/cv", files={"file": ("cv.txt", f, "text/plain")})
    from app.database import get_session
    from app.main import app as fastapi_app

    db = next(fastapi_app.dependency_overrides[get_session]())
    jobs = [_job(db, f"Oferta {i}", score=50 + i) for i in range(10)]
    sample = client.get("/api/agent/calibration").json()["jobs"]
    assert len(sample) == 10 and sample[0]["snippet"]
    assert client.post("/api/agent/calibration", json={"votes": [{"job_id": jobs[0].id, "vote": "skip"}]}).status_code == 422

    proposal = schemas.CalibrationOut(ideal=IDEAL.model_copy(update={"notes": "Startups de producto"}),
                                      learned=["Prefieres backend de producto"],
                                      queries=schemas.QueriesProposal(getonbrd=["backend", "python"], remotive=["backend"],
                                                                      adzuna=[], explanation="…"))
    fake_llm.responses[schemas.CalibrationOut] = proposal
    client.put("/api/agent/preferences", json={**client.get("/api/agent/preferences").json(),
                                                "ideal": {"notes": "Cerca de Heredia"}})
    r = client.post("/api/agent/calibration", json={"votes": [{"job_id": jobs[0].id, "vote": "like"},
                                                              {"job_id": jobs[1].id, "vote": "dislike", "reason": "QA"}],
                                                    "notes": "nada de QA"}).json()
    assert r["learned"] == ["Prefieres backend de producto"] and r["ideal"]["notes"].startswith("Cerca de Heredia")
    votes = {j["id"]: j["vote"] for j in client.get("/api/agent/jobs").json()}
    assert votes[jobs[0].id] == "like" and votes[jobs[1].id] == "dislike"
    prefs = client.post("/api/agent/targeting/apply", json={"ideal": r["ideal"], "queries": r["queries"]}).json()
    assert prefs["ideal"]["roles_wanted"] == ["Backend Engineer"] and prefs["sources"]["getonbrd_queries"] == ["backend", "python"]

    fake_llm.responses[schemas.QueriesProposal] = schemas.QueriesProposal(getonbrd=["go"], remotive=[], adzuna=[], explanation="x")
    assert client.post("/api/agent/queries/suggest").json()["getonbrd"] == ["go"]


def test_vote_endpoint(client):
    from app.database import get_session
    from app.main import app as fastapi_app

    db = next(fastapi_app.dependency_overrides[get_session]())
    j = _job(db, "Descartada por la IA", score=30)
    r = client.post(f"/api/agent/jobs/{j.id}/vote", json={"vote": "like"}).json()
    assert r == {"vote": "like", "can_prepare": True}
    assert client.post("/api/agent/jobs/999/vote", json={"vote": "like"}).status_code == 404


# ── «¿Por qué no vi esta oferta?» ──────────────────────────────


def _trace(db, fake_llm, prefs, url=None, text=None, pages=None):
    from app.services.trace import trace

    def handler(req):
        body = (pages or {}).get(str(req.url))
        return httpx.Response(200, text=body, headers={"content-type": "text/html"}) if body else httpx.Response(404)
    return trace(db, fake_llm, httpx.Client(transport=httpx.MockTransport(handler)), prefs, url, text)


def test_trace_known_job(db, fake_llm):
    _job(db, "Backend", score=40, source_url="https://www.getonbrd.com/jobs/programming/backend-acme?x=1")
    r = _trace(db, fake_llm, SearchPreferences(), url="https://getonbrd.com/jobs/programming/backend-acme")
    assert r["known"] and "por debajo de tu umbral" in r["verdict"] and r["can_prepare"]


def test_trace_coverage(db, fake_llm):
    from app.services.trace import coverage

    prefs = SearchPreferences(sources=schemas.SourcesConfig(lever=["orbit"]))
    assert coverage("https://www.linkedin.com/jobs/view/1", prefs)["status"] == "warn"
    assert coverage("https://jobs.lever.co/orbit/123", prefs)["status"] == "ok"
    c = coverage("https://wizeline.breezy.hr/p/9", prefs)
    assert c["status"] == "error" and c["action"] == {"type": "add_source", "provider": "breezy", "slug": "wizeline",
                                                      "label": "Añadir esta empresa"}
    assert coverage("https://intel.wd1.myworkdayjobs.com/External/job/x", SearchPreferences(
        sources=schemas.SourcesConfig(workday=["https://intel.wd1.myworkdayjobs.com/External"])))["status"] == "ok"


def test_trace_simulates_filters_and_triage(db, fake_llm):
    from app.models import CVProfile
    from tests.conftest import FAKE_CV, FAKE_JOB

    db.add(CVProfile(filename="cv", raw_text="x", profile=FAKE_CV.model_dump()))
    db.commit()
    url = "https://jobs.lever.co/orbit/1"
    page = "<html><body><main><h1>Backend</h1>" + "<p>Python y FastAPI en Madrid.</p>" * 20 + "</main></body></html>"
    # 1) un filtro la descarta
    fake_llm.responses[schemas.JobExtraction] = FAKE_JOB.model_copy(update={"title": "Soporte Técnico"})
    r = _trace(db, fake_llm, SearchPreferences(ideal=IDEAL), url=url, pages={url: page})
    stages = {s["stage"]: s["status"] for s in r["steps"]}
    assert stages["¿Tus fuentes la cubren?"] == "error" and stages["Tus filtros"] == "error"
    assert "no buscas" in r["verdict"] and r["steps"][-1]["hint"].startswith("Revisa «Puestos que NO quieres»")
    # 2) pasa filtros y la criba
    fake_llm.responses[schemas.JobExtraction] = FAKE_JOB
    fake_llm.responses[schemas.TriageBatch] = schemas.TriageBatch(items=[schemas.TriageItem(ref=1, score=82, reason="Encaja")])
    r = _trace(db, fake_llm, SearchPreferences(), text="Backend Python en Madrid. " * 20)
    assert r["score"] == 82 and r["verdict"] == "Habría pasado la criba." and r["can_prepare"]
    # 3) no se puede leer
    r = _trace(db, fake_llm, SearchPreferences(), url="https://example.com/oferta")
    assert r["verdict"] == "No se pudo leer la oferta"


# ── Informe de ajuste ───────────────────────────────────────────


def test_tuning_suggestions_and_apply(db):
    prefs = SearchPreferences(triage_threshold=65, sources=schemas.SourcesConfig(himalayas=True, breezy=["ruido"]))
    for i in range(30):
        _job(db, f"Remota {i}", source="himalayas", score=20, ext=f"himalayas:{i}")
    for i in range(26):
        _job(db, f"Breezy {i}", source="breezy", score=10, ext=f"breezy:ruido:{i}")
    liked = [_job(db, f"Platform Engineer {i}", score=50) for i in range(2)]
    for j in liked:
        targeting.record_vote(db, j, "like")
    targeting.record_vote(db, _job(db, "Data Platform Lead", score=88), "like")
    for _ in range(3):
        db.add(Feedback(decision="descartada", reason="Sueldo bajo", title="QA", company="Lowpay"))
    db.commit()
    s = {x["id"]: x for x in tuning.suggestions(db, prefs)}
    assert {"calibrate", "pause:himalayas:", "pause:breezy:ruido", "blacklist:Lowpay", "salary", "threshold", "queries"} <= set(s)
    assert s["threshold"]["action"]["value"] == 55
    p = tuning.apply(prefs, s["pause:himalayas:"])
    assert p.sources.himalayas is False
    p = tuning.apply(p, s["pause:breezy:ruido"])
    assert p.sources.breezy == []
    p = tuning.apply(p, s["blacklist:Lowpay"])
    assert p.blacklist_companies == ["Lowpay"] and tuning.apply(p, s["threshold"]).triage_threshold == 55
    with pytest.raises(ValueError):
        tuning.apply(p, s["salary"])


def test_tuning_endpoints(client):
    sug = client.get("/api/agent/tuning").json()["suggestions"]
    assert sug[0]["id"] == "calibrate"
    assert client.post("/api/agent/tuning/apply", json={"id": "nada"}).status_code == 404
    assert client.post("/api/agent/tuning/apply", json={"id": "calibrate"}).status_code == 422


# ── Borradores de seguimiento automáticos ──────────────────────


def test_followup_drafts(db, fake_llm, monkeypatch):
    from app.config import get_settings
    from app.models import CVProfile
    from app.services.followups import create_followup_drafts
    from tests.conftest import FAKE_CV
    from tests.test_v07 import FakeGmail

    fake_llm.responses[schemas.MessageDraft] = schemas.MessageDraft(subject="Seguimiento", body="Hola Laura")
    db.add(CVProfile(filename="cv", raw_text="x", profile=FAKE_CV.model_dump()))
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    job = _job(db, "Backend", company="Orbit", status=PipelineStatus.APPROVED.value)
    app = Application(job_id=job.id, status=ApplicationStatus.APPLIED, applied_at=now - timedelta(days=9))
    db.add(app)
    db.commit()
    db.add(EmailEvent(message_id="c1", sender="Laura <laura@orbit.io>", subject="Recibida", category="confirmacion_recepcion",
                      confidence=1, application_id=app.id, received_at=now - timedelta(days=9), thread_id="t1",
                      rfc_message_id="<m1@orbit.io>"))
    db.commit()
    settings = get_settings()
    monkeypatch.setattr(settings, "email_mode", "simulated")
    assert create_followup_drafts(db, fake_llm, settings, SearchPreferences(), now, FakeGmail()) == []  # sin Gmail
    monkeypatch.setattr(settings, "email_mode", "gmail")
    gmail = FakeGmail()
    assert create_followup_drafts(db, fake_llm, settings, SearchPreferences(), now, gmail) == ["Orbit"]
    assert gmail.created[0]["message"]["threadId"] == "t1"
    assert create_followup_drafts(db, fake_llm, settings, SearchPreferences(), now + timedelta(days=1), gmail) == []  # 7 días
    assert create_followup_drafts(db, fake_llm, settings, SearchPreferences(auto_followup_drafts=False),
                                  now + timedelta(days=8), gmail) == []


def test_weekly_tuning_message(tmp_path, monkeypatch, db):
    import app.digest as d

    monkeypatch.setattr(d, "STATE", tmp_path / "digest.json")
    now = datetime(2026, 10, 12, 9)  # lunes
    msg = d.weekly_tuning_message(db, SearchPreferences(), now)
    assert msg.startswith("1 sugerencia para mejorar") and "calibración" in msg
    d._save(tuning_week=now.strftime("%G-W%V"))
    assert d.weekly_tuning_message(db, SearchPreferences(), now) is None
