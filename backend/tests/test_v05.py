"""0.5.0: descubrir empresas, guardar desde el navegador y resumen diario."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.models import Application, ApplicationPackage, ApplicationStatus, CVProfile, EmailEvent, Job
from app.services import discovery
from app.services.digest import build_digest, digest_message

# ── Descubrir empresas ──────────────────────────────────────────


@pytest.mark.parametrize("name,expected", [
    ("Glovo", ["glovo", "glovoapp", "glovohq", "glovoinc"]),
    ("La Fourche", ["lafourche", "la-fourche", "lafourcheapp", "lafourchehq", "lafourcheinc", "la"]),
    ("Cabify S.L.", ["cabify", "cabifyapp", "cabifyhq", "cabifyinc"]),
    ("Café & Co", ["cafeand", "cafe-and", "cafeandapp", "cafeandhq", "cafeandinc", "cafe"]),
    ("  ", []),
])
def test_slug_variants(name, expected):
    assert discovery.slug_variants(name) == expected


@pytest.mark.parametrize("text,expected", [
    ("https://boards.greenhouse.io/airbnb/jobs/123", ("greenhouse", "airbnb")),
    ("https://job-boards.eu.greenhouse.io/Revolut", ("greenhouse", "revolut")),
    ("jobs.lever.co/netflix?team=x", ("lever", "netflix")),
    ("https://jobs.ashbyhq.com/linear/abc", ("ashby", "linear")),
    ("Glovo", None),
])
def test_parse_url(text, expected):
    assert discovery.parse_url(text) == expected


def fake_ats():
    def handler(req: httpx.Request) -> httpx.Response:
        host, path = req.url.host, req.url.path
        if host == "boards-api.greenhouse.io":
            if path == "/v1/boards/glovo/jobs":
                return httpx.Response(200, json={"jobs": [{"title": "Backend Engineer"}, {"title": "Data Analyst"}]})
            if path == "/v1/boards/airbnb/jobs":
                return httpx.Response(200, json={"jobs": []})  # existe pero sin ofertas ahora mismo
            return httpx.Response(404, json={"status": 404})
        if host == "api.lever.co":
            if path == "/v0/postings/la-fourche":
                return httpx.Response(200, json=[{"text": "Product Designer"}])
            return httpx.Response(404, json={"ok": False})
        if host == "api.ashbyhq.com":
            return httpx.Response(200, json={"jobs": []})  # responde a cualquier nombre: debe ignorarse
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_discover_finds_boards_and_ignores_empty_ashby():
    found = discovery.discover(fake_ats(), ["Glovo", "La Fourche", "https://boards.greenhouse.io/airbnb", "Nadie SL"])
    summary = {(b["query"], b["provider"], b["slug"], b["jobs"]) for b in found}
    assert summary == {("Glovo", "greenhouse", "glovo", 2), ("La Fourche", "lever", "la-fourche", 1),
                       ("https://boards.greenhouse.io/airbnb", "greenhouse", "airbnb", 0)}
    glovo = next(b for b in found if b["slug"] == "glovo")
    assert glovo["sample"] == ["Backend Engineer", "Data Analyst"] and glovo["url"] == "https://boards.greenhouse.io/glovo"


def test_discover_endpoint(client):
    from app.main import app
    from app.routers.agent import get_http_client

    app.dependency_overrides[get_http_client] = fake_ats
    r = client.post("/api/agent/discover", json={"companies": ["Glovo", "Nadie SL"]}).json()
    assert [b["slug"] for b in r["found"]] == ["glovo"] and r["missing"] == ["Nadie SL"]
    assert client.post("/api/agent/discover", json={"companies": [" "]}).status_code == 422
    assert client.post("/api/agent/discover", json={"companies": [f"e{i}" for i in range(16)]}).status_code == 422


# ── Guardar desde el navegador ──────────────────────────────────


def test_capture_page_and_scripts(client):
    html = client.get("/capture").text
    assert "/assets/js/capture.js?v=" in html and "{{" not in html
    for f in ["capture.js", "bookmarklet.js"]:
        assert client.get(f"/assets/js/{f}").status_code == 200


def test_captured_job_keeps_source_url(client):
    job = client.post("/api/jobs", json={"text": "Backend en Acme " * 10, "url": "https://www.linkedin.com/jobs/view/1"}).json()
    assert job["source_url"] == "https://www.linkedin.com/jobs/view/1"


# ── Resumen diario ──────────────────────────────────────────────

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _app(db, title, company, **kw):
    job = Job(title=title, company=company, raw_text="x")
    db.add(job)
    db.commit()
    app = Application(job_id=job.id, **kw)
    db.add(app)
    db.commit()
    return app


def test_digest_collects_what_matters(db):
    _app(db, "Platform Engineer", "Orbit", status=ApplicationStatus.INTERVIEW, interview_at=NOW + timedelta(hours=26))
    _app(db, "Old Interview", "Past", status=ApplicationStatus.INTERVIEW, interview_at=NOW - timedelta(days=3))
    stale = _app(db, "Python Engineer", "Fintechly", status=ApplicationStatus.APPLIED, applied_at=NOW - timedelta(days=10))
    answered = _app(db, "Data Engineer", "DataNova", status=ApplicationStatus.APPLIED, applied_at=NOW - timedelta(days=12))
    _app(db, "Recent", "Fresh", status=ApplicationStatus.APPLIED, applied_at=NOW - timedelta(days=2))
    db.add(EmailEvent(message_id="m", sender="x", subject="y", category="solicitud_info", confidence=1,
                      application_id=answered.id))
    db.add(CVProfile(filename="cv", raw_text="x"))
    db.commit()
    db.add(ApplicationPackage(job_id=stale.job_id, cv_id=1, status="aprobada"))
    db.commit()

    d = build_digest(db, NOW)
    assert [i["company"] for i in d["interviews"]] == ["Orbit"]
    assert [s["company"] for s in d["stale"]] == ["Fintechly"] and d["stale"][0]["days"] == 10
    assert d["approved_unsent"] == 1
    title, text = digest_message(d)
    assert "1 entrevista(s) pronto · Orbit" in text and "1 aprobada(s) sin enviar" in text and "más de 7 días" in text


def test_digest_is_silent_when_nothing_happens(db):
    assert digest_message(build_digest(db, NOW)) is None


def test_digest_sends_once_a_day_after_the_hour():
    from app.digest import should_send

    morning = datetime(2026, 10, 8, 9, 30)
    assert should_send(morning, 9, None)
    assert not should_send(morning, 9, "2026-10-08")       # ya enviado hoy
    assert not should_send(morning.replace(hour=8), 9, None)  # aún no es la hora
    assert should_send(morning.replace(hour=15), 9, "2026-10-07")  # Mac dormido a las 9: se envía al despertar


def test_digest_main_force_notifies(tmp_path, monkeypatch):
    import app.digest as d

    sent = []
    monkeypatch.setattr(d, "STATE", tmp_path / "digest.json")
    monkeypatch.setattr(d, "notify", lambda title, msg: sent.append(msg))
    monkeypatch.setattr(d, "build_digest", lambda db: {"pending": 2, "new_today": 2, "approved_unsent": 0,
                                                       "interviews": [], "stale": []})
    monkeypatch.setattr(d, "init_db", lambda: None)
    monkeypatch.setattr(d, "load_preferences", lambda db: type("P", (), {"digest_enabled": True, "digest_hour": 9, "interview_reminders": False})())
    assert d.main(["--force"]) == 0
    assert sent and "2 candidatura(s) nueva(s)" in sent[0] and (tmp_path / "digest.json").exists()


def test_preferences_include_digest_defaults(client):
    prefs = client.get("/api/agent/preferences").json()
    assert prefs["digest_enabled"] is True and prefs["digest_hour"] == 9
    bad = {**prefs, "digest_hour": 25}
    assert client.put("/api/agent/preferences", json=bad).status_code == 422
