"""0.8.0: gasto en IA, diagnóstico, Llavero de macOS y fuentes de Latinoamérica."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.services import usage

# ── Gasto en IA ─────────────────────────────────────────────────


def test_cost_by_model():
    assert usage.cost_usd("claude-haiku-5-5", 100_000, 0) == pytest.approx(0.01)
    assert usage.cost_usd("claude-haiku-5-5", 10_000, 2_000) == pytest.approx(0.001 + 0.001)
    assert usage.cost_usd("claude-sonnet-5-5", 0, 1_000_000) == pytest.approx(10.0)
    # caché: escribir 1,25× la entrada; leer al precio de lectura
    assert usage.cost_usd("claude-opus-5-5", 0, 0, cache_write=1_000_000, cache_read=1_000_000) == pytest.approx(5.0 + 0.20)
    # Haiku con prompts de más de 100K tokens cambia de tramo (0,50 $ / 2,50 $)
    assert usage.cost_usd("claude-haiku-5-5", 200_000, 100_000) == pytest.approx(0.10 + 0.25)


@pytest.fixture
def mem_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.database.engine", engine)
    return engine


def test_record_and_summary_and_budget(mem_engine, tmp_path, monkeypatch):
    from app.models import LLMUsage

    monkeypatch.setattr("app.config.DATA_DIR", tmp_path)
    u = SimpleNamespace(input_tokens=90_000, output_tokens=300_000, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    usage.record("claude-haiku-5-5", "TriageBatch", u)      # 0,009 + 0,15 = 0,159 $
    usage.record("claude-sonnet-5-5", "MockStep", SimpleNamespace(input_tokens=50_000, output_tokens=10_000))  # 0,10 + 0,10
    usage.record("claude-haiku-5-5", "Rara", None)            # sin usage: 0 $, no rompe
    with Session(mem_engine) as db:
        old = LLMUsage(model="claude-opus-5-5", cost_usd=99, created_at=datetime.now(timezone.utc) - timedelta(days=40))
        db.add(old)
        db.commit()
        s = usage.spend_summary(db, budget=0.3)
        assert s["month_usd"] == pytest.approx(0.359) and s["calls"] == 3
        assert [p["purpose"] for p in s["by_purpose"]] == ["Simulacros", "Criba de ofertas", "Otros"]
        assert s["over_budget"] is True and usage.over_budget(db, 0.3) and not usage.over_budget(db, None)
        assert usage.budget_notice(db, 0.3).startswith("Has llegado a tu tope")
        assert usage.budget_notice(db, 0.3) is None  # una vez por mes
        assert usage.budget_notice(db, 0.4).startswith("Llevas 0,36 $")  # 90 %: aviso del 80 %


def test_llm_client_records_usage(monkeypatch):
    """El cliente real apunta cada respuesta (sin llamar a la API)."""
    from app import schemas
    from app.services import llm

    seen = []
    monkeypatch.setattr(usage, "record", lambda model, name, u: seen.append((model, name, u.output_tokens)))
    fake_resp = SimpleNamespace(model="claude-haiku-5-5", stop_reason="end_turn", usage=SimpleNamespace(output_tokens=7),
                                parsed_output=schemas.MessageDraft(subject="a", body="b"))
    client = llm.AnthropicLLM(api_key="sk-test")
    monkeypatch.setattr(client._client.beta.messages, "parse", lambda **kw: fake_resp)
    out = client.structured(system="s", prompt="p", schema=schemas.MessageDraft)
    assert out.subject == "a" and seen == [("claude-haiku-5-5", "MessageDraft", 7)]


def test_agent_pauses_over_budget(client, fake_llm, monkeypatch):
    prefs = client.get("/api/agent/preferences").json()
    client.put("/api/agent/preferences", json={**prefs, "monthly_budget_usd": 1})
    monkeypatch.setattr("app.services.agent.over_budget", lambda db, b: True)
    monkeypatch.setattr("app.services.agent.budget_notice", lambda db, b: None)
    from app.config import get_settings
    from app.database import get_session
    from app.main import app as fastapi_app
    from app.services.agent import run_agent

    db = next(fastapi_app.dependency_overrides[get_session]())
    run = run_agent(db, fake_llm, get_settings())
    assert run.status == "ok" and "tope de gasto" in run.error and fake_llm.calls == []


def test_spend_and_diagnostics_endpoints(client):
    s = client.get("/api/status/spend").json()
    assert s["month_usd"] == 0 and s["budget_usd"] is None
    d = client.get("/api/status/diagnostics").json()
    ids = {c["id"]: c for c in d["checks"]}
    assert {"claude", "cv", "agent", "gmail", "browser", "backups", "updates", "spend", "disk", "keychain"} <= set(ids)
    assert ids["cv"]["status"] == "error" and ids["cv"]["action"]["route"] == "perfil"
    assert d["checks"][0]["status"] == "error"  # lo roto, primero


# ── Llavero de macOS ────────────────────────────────────────────


class FakeKeychain:
    def __init__(self):
        self.items = {}

    def get(self, name):
        return self.items.get(name)

    def set(self, name, value):
        self.items[name] = value
        return True

    def delete(self, name):
        self.items.pop(name, None)


@pytest.fixture
def kc(tmp_path, monkeypatch):
    from app import keychain
    from app.services import secrets

    fake = FakeKeychain()
    monkeypatch.setattr(keychain, "backend", fake)
    monkeypatch.setattr(keychain, "available", lambda: True)
    env = tmp_path / ".env"
    monkeypatch.setattr(secrets, "env_path", lambda: env)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MI_API_KEY", raising=False)
    return fake, env


def test_keychain_store_migrate_delete(kc, monkeypatch):
    import os

    from app import keychain
    from app.services import secrets

    fake, env = kc
    env.write_text("ANTHROPIC_API_KEY=sk-ant-viejo\nLLM_MODEL=claude-haiku-5-5\n")
    moved = secrets.migrate_to_keychain({"ANTHROPIC_API_KEY", "ADZUNA_APP_ID"})
    assert moved == ["ANTHROPIC_API_KEY"] and fake.items["ANTHROPIC_API_KEY"] == "sk-ant-viejo"
    text = env.read_text()
    assert "sk-ant" not in text and "KEYCHAIN_KEYS=ANTHROPIC_API_KEY" in text and "LLM_MODEL=claude-haiku-5-5" in text
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-viejo"  # el proceso sigue teniéndola

    assert secrets.store_secret("MI_API_KEY", "abc") == "llavero"
    assert secrets.keychain_names() == ["ANTHROPIC_API_KEY", "MI_API_KEY"] and "abc" not in env.read_text()

    # Otro proceso (el agente) arranca: carga del Llavero lo que indica el .env
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert keychain.load_into_environ(secrets.read_env()) == ["ANTHROPIC_API_KEY"]  # MI_API_KEY ya estaba
    # Si el .env trae un valor nuevo (p. ej. `jobtracker config api-key`), manda el del .env
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert keychain.load_into_environ({**secrets.read_env(), "ANTHROPIC_API_KEY": "sk-nueva"}) == []

    secrets.delete_secret("MI_API_KEY")
    assert "MI_API_KEY" not in fake.items and secrets.keychain_names() == ["ANTHROPIC_API_KEY"]


def test_keys_api_uses_keychain(client, kc):
    fake, env = kc
    r = client.put("/api/settings/keys", json={"name": "ANTHROPIC_API_KEY", "value": "sk-ant-nueva-1234"}).json()
    assert r["stored"] == "llavero" and fake.items["ANTHROPIC_API_KEY"] == "sk-ant-nueva-1234"
    keys = client.get("/api/settings/keys").json()
    claude = next(k for k in keys["keys"] if k["name"] == "ANTHROPIC_API_KEY")
    assert claude["configured"] and claude["stored"] == "llavero" and keys["keychain"] is True
    client.put("/api/settings/keys", json={"name": "OTRA_API_KEY", "value": "x1"})
    assert [c["name"] for c in client.get("/api/settings/keys").json()["custom"]] == ["OTRA_API_KEY"]
    assert client.delete("/api/settings/keys/OTRA_API_KEY").status_code == 204 and "OTRA_API_KEY" not in fake.items


def test_without_keychain_falls_back_to_env(tmp_path, monkeypatch):
    from app import keychain
    from app.services import secrets

    monkeypatch.setattr(keychain, "available", lambda: False)
    env = tmp_path / ".env"
    monkeypatch.setattr(secrets, "env_path", lambda: env)
    assert secrets.store_secret("MI_API_KEY", "abc") == "env" and "MI_API_KEY=abc" in env.read_text()
    assert secrets.migrate_to_keychain({"MI_API_KEY"}) == []
    monkeypatch.delenv("MI_API_KEY", raising=False)


# ── Latinoamérica y Costa Rica ─────────────────────────────────

import httpx  # noqa: E402

from app.services import region, sources_latam  # noqa: E402


@pytest.mark.parametrize("location,desc,expected", [
    ("Remote, US", "", "remote, us"),
    ("Remote", "Candidates must be located in the United States.", "must be located in the united states"),
    ("Remote - LATAM", "", None),
    ("Remote", "We hire across Latin America", None),
    ("Remote (Costa Rica)", "", None),
    ("Anywhere", "US only", None),
    ("Remote, EMEA", "", "remote, emea"),
])
def test_remote_restriction(location, desc, expected):
    assert region.remote_restriction(location, desc, "CR") == expected


def test_country_helpers():
    assert region.guess_country("Heredia, Costa Rica") == "CR" and region.guess_country("Bogotá") == "CO"
    assert region.mentions_country("San José, Costa Rica", "CR") and not region.mentions_country("San Jose, CA", "CR")
    assert "aguinaldo" in region.market_context("CR") and "usted" in region.market_context("CR")
    assert "13.er salario" in region.market_context("MX") and region.market_context(None) == ""


def test_hard_filter_drops_us_only_remote():
    from app.schemas import SearchPreferences
    from app.services.agent import hard_filter
    from app.services.sources import RawJob

    prefs = SearchPreferences(country="CR", locations=["Costa Rica", "San José"])
    us = RawJob(source="x", external_id="1", title="Backend", company="A", location="Remote, US", url=None,
                description="...", remote=True)
    latam = RawJob(source="x", external_id="2", title="Backend", company="B", location="Remote - LATAM", url=None,
                   description="...", remote=True)
    assert "otra región" in hard_filter(us, prefs) and hard_filter(latam, prefs) is None
    assert hard_filter(us, SearchPreferences()) is None  # sin país indicado, no se filtra


def mock_latam():
    def handler(req: httpx.Request) -> httpx.Response:
        host, path = req.url.host, req.url.path
        if host == "intel.wd1.myworkdayjobs.com":
            if req.method == "POST" and path == "/wday/cxs/intel/External/jobs":
                import json
                assert json.loads(req.content)["searchText"] in ("Costa Rica", "")  # "" al descubrir
                return httpx.Response(200, json={"total": 2, "jobPostings": [
                    {"title": "Software Engineer", "externalPath": "/job/Costa-Rica-Heredia/Software-Engineer_JR1",
                     "locationsText": "Costa Rica, Heredia", "postedOn": "Posted 3 Days Ago", "bulletFields": ["JR1"]},
                    {"title": "Firmware Engineer", "externalPath": "/job/US-Folsom/Firmware_JR2",
                     "locationsText": "US, California, Folsom", "postedOn": "Posted Today", "bulletFields": ["JR2"]}]})
            if path == "/wday/cxs/intel/External/job/Costa-Rica-Heredia/Software-Engineer_JR1":
                return httpx.Response(200, json={"jobPostingInfo": {"jobDescription": "<p>Python y <b>C++</b></p>",
                                                                    "location": "Costa Rica, Heredia", "startDate": "2026-10-05"},
                                                 "hiringOrganization": {"name": "Intel"}})
        if host == "api.smartrecruiters.com":
            if path == "/v1/companies/Visa/postings":
                assert req.url.params["country"] == "cr"
                return httpx.Response(200, json={"totalFound": 1, "content": [
                    {"id": "744", "name": "Data Analyst", "releasedDate": "2026-10-01T10:00:00.000Z",
                     "location": {"city": "San José", "country": "cr", "remote": False}, "company": {"identifier": "Visa", "name": "Visa"}}]})
            if path == "/v1/companies/Visa/postings/744":
                return httpx.Response(200, json={"jobAd": {"sections": {"jobDescription": {"text": "<p>SQL y Tableau</p>"}}}})
        if host == "www.getonbrd.com":
            return httpx.Response(200, json={"data": [
                {"id": "py-dev-acme-san-jose", "attributes": {"title": "Python Developer", "description": "<p>Django</p>",
                 "remote": True, "remote_modality": "fully_remote", "countries": ["Costa Rica", "Remote"], "published_at": 1759700000,
                 "min_salary": 2500, "max_salary": 3500, "company": {"data": {"attributes": {"name": "Acme"}}}},
                 "links": {"public_url": "https://www.getonbrd.com/jobs/programming/py-dev-acme-san-jose"}},
                {"id": "local-ar", "attributes": {"title": "Dev local", "remote": True, "remote_modality": "remote_local",
                 "countries": ["Argentina"], "published_at": 1759700000}}]})
        if host == "himalayas.app":
            return httpx.Response(200, json={"jobs": [
                {"title": "Backend (LATAM)", "companyName": "Remote Co", "applicationLink": "https://h/1", "guid": "1",
                 "locationRestrictions": ["Latin America"], "pubDate": 1759700000, "description": "<p>Go</p>"},
                {"title": "US only role", "companyName": "X", "applicationLink": "https://h/2", "guid": "2",
                 "locationRestrictions": ["United States"], "pubDate": 1759700000},
                {"title": "Worldwide role", "companyName": "Y", "applicationLink": "https://h/3", "guid": "3",
                 "locationRestrictions": [], "pubDate": 1759700000}]})
        if host == "www.amazon.jobs":
            assert req.url.params["country"] == "CRI"
            return httpx.Response(200, json={"jobs": [{"id_icims": "300", "title": "Support Engineer", "company_name": "Amazon",
                                                       "normalized_location": "Heredia, CR", "posted_date": "October 2, 2026",
                                                       "job_path": "/en/jobs/300/support-engineer", "description": "AWS",
                                                       "basic_qualifications": "Inglés B2"}]})
        if host == "nuvemshop.recruitee.com":
            return httpx.Response(200, json={"offers": [
                {"id": 9, "title": "Frontend", "location": "Remote", "remote": True, "careers_url": "https://n/9",
                 "description": "<p>React</p>", "published_at": "2026-10-01"},
                {"id": 10, "title": "Barista", "location": "Lisbon, Portugal", "remote": False, "careers_url": "https://n/10"}]})
        if host == "wizeline.breezy.hr":
            return httpx.Response(200, json=[{"id": "b1", "name": "QA Engineer", "url": "https://wizeline.breezy.hr/p/b1",
                                              "published_date": "2026-10-03", "location": {"name": "San José, Costa Rica"},
                                              "company": {"name": "Wizeline"}}])
        if host == "apply.workable.com" and path.endswith("/akurey"):
            return httpx.Response(200, json={"name": "Akurey", "jobs": [
                {"title": "DevOps", "shortcode": "AB1", "country": "Costa Rica", "city": "San José", "url": "https://apply.workable.com/akurey/j/AB1",
                 "published_on": "2026-10-04", "description": "<p>AWS</p>"}]})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_latam_fetchers():
    c = mock_latam()
    wd = sources_latam.fetch_workday(c, "https://intel.wd1.myworkdayjobs.com/en-US/External", "CR", today=datetime(2026, 10, 8).date())
    assert [j.title for j in wd] == ["Software Engineer"]  # la de EE. UU. se descarta
    assert wd[0].company == "Intel" and "C++" in wd[0].description and str(wd[0].posted_date) == "2026-10-05"
    assert wd[0].url == "https://intel.wd1.myworkdayjobs.com/en-US/External/job/Costa-Rica-Heredia/Software-Engineer_JR1"
    sr = sources_latam.fetch_smartrecruiters(c, "Visa", "CR")
    assert sr[0].description == "SQL y Tableau" and sr[0].url == "https://jobs.smartrecruiters.com/Visa/744"
    gob = sources_latam.fetch_getonbrd(c, "python", "CR")
    assert [j.title for j in gob] == ["Python Developer"] and gob[0].salary_text == "2500-3500 USD/mes"
    assert gob[0].posted_date.year == 2025 or gob[0].posted_date.year == 2026
    hm = sources_latam.fetch_himalayas(c, "CR")
    assert [j.title for j in hm] == ["Backend (LATAM)", "Worldwide role"]
    az = sources_latam.fetch_amazon(c, "CR")
    assert az[0].url == "https://www.amazon.jobs/en/jobs/300/support-engineer" and "Inglés B2" in az[0].description
    assert [j.title for j in sources_latam.fetch_recruitee(c, "nuvemshop", "CR")] == ["Frontend"]
    br = sources_latam.fetch_breezy(c, "wizeline", "CR")
    assert br[0].extra["partial"] is True and br[0].company == "Wizeline"
    assert sources_latam.fetch_workable(c, "akurey", "CR")[0].company == "Akurey"
    with pytest.raises(sources_latam.SourceError):
        sources_latam.fetch_workday(c, "https://example.com/careers")


def test_collect_reports_latam_sources():
    from app.schemas import SourcesConfig
    from app.services.sources import collect

    cfg = SourcesConfig(workday=["https://intel.wd1.myworkdayjobs.com/External"], smartrecruiters=["Visa"],
                        getonbrd_queries=["python"], himalayas=True, amazon=True, breezy=["nadie"])
    jobs, report = collect(mock_latam(), cfg, None, country="CR")
    assert report["workday:intel"] == 1 and report["smartrecruiters:Visa"] == 1 and report["amazon"] == 1
    assert report["breezy:nadie"].startswith("error")  # una fuente que falla no para a las demás
    assert {j.source for j in jobs} >= {"workday", "smartrecruiters", "getonbrd", "himalayas", "amazon"}


def test_discovery_finds_new_platforms():
    from app.services import discovery

    assert discovery.parse_url("https://intel.wd1.myworkdayjobs.com/en-US/External/job/x") == (
        "workday", "https://intel.wd1.myworkdayjobs.com/en-US/External")
    assert discovery.parse_url("https://careers.smartrecruiters.com/Visa") == ("smartrecruiters", "visa")
    assert discovery.parse_url("https://wizeline.breezy.hr/p/123") == ("breezy", "wizeline")
    assert discovery.parse_url("apply.workable.com/akurey/") == ("workable", "akurey")
    found = discovery.discover(mock_latam(), ["Wizeline", "https://intel.wd1.myworkdayjobs.com/External"])
    assert {(b["provider"], b["jobs"]) for b in found} == {("breezy", 1), ("workday", 2)}


def test_autoconfig_sets_latam_sources(fake_llm):
    from app import schemas
    from app.config import get_settings
    from app.services.agent import autoconfigure_preferences
    from tests.conftest import FAKE_CV

    fake_llm.responses[schemas.PreferencesProposal] = schemas.PreferencesProposal(
        locations=["San José", "Heredia", "Costa Rica"], remote_ok=True, exclude_keywords=["pasantía"],
        remotive_queries=["python"], adzuna_queries=["desarrollador"], adzuna_country="cr", country="CR",
        getonbrd_queries=["python", "backend"])
    p = autoconfigure_preferences(fake_llm, get_settings(), FAKE_CV)
    assert p.country == "CR" and p.sources.getonbrd_queries == ["python", "backend"]
    assert p.sources.himalayas and p.sources.amazon
    assert p.sources.adzuna_queries == []  # Adzuna no cubre Costa Rica


def test_offer_monthly_with_aguinaldo_and_defaults(client, fake_llm, tmp_path):
    from app.services.interviews import offer_annual, offer_text

    assert offer_annual({"base_salary": 2000, "period": "mensual", "thirteenth": True}) == 26000
    assert offer_annual({"base_salary": 2000, "period": "mensual", "variable": 1000}) == 25000
    assert "brutos al mes + aguinaldo" in offer_text({"base_salary": 2000, "period": "mensual", "thirteenth": True, "currency": "USD"})
    prefs = client.get("/api/agent/preferences").json()
    client.put("/api/agent/preferences", json={**prefs, "country": "CR"})
    job = client.post("/api/jobs", json={"text": "Backend en Acme " * 6}).json()
    app_id = next(a["id"] for a in client.get("/api/applications").json() if a["job_id"] == job["id"])
    d = client.get(f"/api/applications/{app_id}/detail").json()
    assert d["offer_defaults"] == {"currency": "CRC", "period": "mensual", "thirteenth": True, "country": "CR"}
    client.put(f"/api/applications/{app_id}/offer", json={"base_salary": 1_500_000, "period": "mensual", "thirteenth": True,
                                                          "currency": "CRC"})
    assert client.get(f"/api/applications/{app_id}/detail").json()["offer_total"] == 19_500_000


def test_latam_alert_senders():
    from app.schemas import EmailIn
    from app.services.sources import is_job_alert

    for sender in ["alertas@computrabajo.com", "noreply@elempleo.com", "info@empleos.net", "avisos@bumeran.com"]:
        assert is_job_alert(EmailIn(message_id="x", sender=sender, subject="Hola", body=""))
    assert is_job_alert(EmailIn(message_id="y", sender="a@b.c", subject="Vacantes nuevas para ti", body=""))


def test_existing_install_gets_region_once(client, fake_llm, tmp_path):
    """Instalación configurada antes de la 0.8: el agente deduce el país del CV una sola vez."""
    from app.config import get_settings
    from app.database import get_session
    from app.main import app as fastapi_app
    from app.services.agent import load_preferences, run_agent, save_preferences
    from app.schemas import SearchPreferences, SourcesConfig
    from tests.conftest import FAKE_CV

    from app import schemas

    fake_llm.responses[type(FAKE_CV)] = FAKE_CV.model_copy(update={"location": "Heredia, Costa Rica"})
    fake_llm.responses[schemas.TriageBatch] = lambda **kw: schemas.TriageBatch.model_validate({"items": []})
    with open(tmp_path / "cv.txt", "w") as f:
        f.write("x" * 100)
    with open(tmp_path / "cv.txt", "rb") as f:
        client.post("/api/cv", files={"file": ("cv.txt", f, "text/plain")})
    db = next(fastapi_app.dependency_overrides[get_session]())
    save_preferences(db, SearchPreferences(sources=SourcesConfig(remotive_queries=["python"], email_alerts=False)))
    run_agent(db, fake_llm, get_settings(), http_client=mock_latam())
    p = load_preferences(db)
    assert (p.country, p.region_checked, p.sources.getonbrd_queries, p.sources.himalayas, p.sources.amazon) == \
        ("CR", True, ["python"], True, True)
    p.sources.himalayas = False  # el usuario lo apaga: no se vuelve a encender
    save_preferences(db, p)
    run_agent(db, fake_llm, get_settings(), http_client=mock_latam())
    assert load_preferences(db).sources.himalayas is False
