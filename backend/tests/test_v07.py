"""0.7.0: copias de seguridad, avisos de entrevista, exportación CSV y más."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app import backups
from app.models import Application, ApplicationStatus, Job

# ── Copias de seguridad ─────────────────────────────────────────


def _db(path):
    con = sqlite3.connect(path)
    con.execute("create table if not exists t (x)")
    con.execute("insert into t values (1)")
    con.commit()
    con.close()


def test_backup_before_new_version_and_weekly(tmp_path):
    db = tmp_path / "jobtracker.db"
    assert backups.maybe_backup(db, "0.6.0") is None  # instalación nueva: nada que copiar
    _db(db)
    first = backups.maybe_backup(db, "0.6.0")  # aún sin ninguna copia → semanal
    assert first and "semanal" in first.name
    assert backups.maybe_backup(db, "0.6.0") is None  # misma versión y copia reciente
    upgrade = backups.maybe_backup(db, "0.7.0")
    assert upgrade and "antes-de-0.7.0" in upgrade.name
    assert sqlite3.connect(upgrade).execute("select count(*) from t").fetchone() == (1,)
    weekly = backups.maybe_backup(db, "0.7.0", now=datetime.now() + timedelta(days=8))
    assert weekly and "semanal" in weekly.name


def test_backups_keep_only_latest(tmp_path, monkeypatch):
    db = tmp_path / "jobtracker.db"
    _db(db)
    import os
    import time
    for i in range(backups.KEEP + 3):
        b = backups.make_backup(db, f"n{i}")
        os.utime(b, (time.time() - 100 + i, time.time() - 100 + i))
    last = backups.make_backup(db, "ultima")
    kept = backups.list_backups(db)
    assert len(kept) == backups.KEEP and kept[0] == last and not any("n0" in p.name for p in kept)


# ── Aviso la víspera de la entrevista ──────────────────────────


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _interview(db, company, at):
    job = Job(title="Backend", company=company, raw_text="x")
    db.add(job)
    db.commit()
    app = Application(job_id=job.id, status=ApplicationStatus.INTERVIEW, interview_at=at)
    db.add(app)
    db.commit()
    return app


MADRID = timezone(timedelta(hours=2))


def test_reminders_eve_and_same_day(db):
    from app.services.digest import due_reminders, reminder_message

    _interview(db, "Orbit", datetime(2026, 10, 9, 10, 0, tzinfo=MADRID))      # mañana
    _interview(db, "Hoy SL", datetime(2026, 10, 8, 20, 30, tzinfo=MADRID))    # hoy, más tarde
    _interview(db, "Lejos", datetime(2026, 10, 12, 10, 0, tzinfo=MADRID))     # dentro de 4 días
    _interview(db, "Pasada", datetime(2026, 10, 8, 9, 0, tzinfo=MADRID))      # ya pasó

    morning = datetime(2026, 10, 8, 11, 0, tzinfo=MADRID)
    assert [r["company"] for r in due_reminders(db, morning, set())] == ["Hoy SL"]
    evening = datetime(2026, 10, 8, 18, 5, tzinfo=MADRID)
    due = due_reminders(db, evening, set())
    assert {r["company"] for r in due} == {"Orbit", "Hoy SL"}
    orbit = next(r for r in due if r["company"] == "Orbit")
    assert reminder_message(orbit)[0] == "🎤 Mañana a las 10:00: entrevista"
    # una sola vez por entrevista
    assert due_reminders(db, evening, {r["key"] for r in due}) == []


def test_digest_main_sends_reminder_once(tmp_path, monkeypatch, db):
    import app.digest as d

    sent = []
    monkeypatch.setattr(d, "STATE", tmp_path / "digest.json")
    monkeypatch.setattr(d, "notify", lambda title, msg: sent.append(title))
    _interview(db, "Orbit", datetime.now(timezone.utc) + timedelta(hours=1))
    assert d.send_reminders(db) == 1 and d.send_reminders(db) == 0
    assert len(sent) == 1 and sent[0].startswith("🎤 Hoy")


# ── Exportar ────────────────────────────────────────────────────


def test_export_csv(client):
    client.post("/api/jobs", json={"text": "Backend en Acme Cloud " * 6, "url": "https://acme.io/j/1"})
    app_id = client.get("/api/applications").json()[0]["id"]
    client.patch(f"/api/applications/{app_id}", json={"notes": "Primera línea\nsegunda; con punto y coma"})
    r = client.get("/api/applications/export.csv")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")
    lines = text.splitlines()
    assert lines[0].startswith("Empresa;Puesto;Estado")
    assert "Acme Cloud;Backend Developer;Por aplicar" in lines[1] and "https://acme.io/j/1" in lines[1]
    assert '"Primera línea segunda; con punto y coma"' in lines[1]


# ── Simulacro de entrevista ─────────────────────────────────────


def test_mock_interview_flow(client, fake_llm, tmp_path):
    from app import schemas

    with open(tmp_path / "cv.txt", "w") as f:
        f.write("x" * 100)
    with open(tmp_path / "cv.txt", "rb") as f:
        client.post("/api/cv", files={"file": ("cv.txt", f, "text/plain")})
    client.post("/api/jobs", json={"text": "Platform Engineer en Orbit " * 6})
    app_id = client.get("/api/applications").json()[0]["id"]

    fake_llm.responses[schemas.MockStep] = schemas.MockStep(next_question="Hola. ¿Por qué Orbit?", question_kind="motivación")
    first = client.post(f"/api/applications/{app_id}/mock", json={}).json()
    assert first["feedback"] is None and first["next_question"] == "Hola. ¿Por qué Orbit?" and "saved_id" not in first

    fb = schemas.MockFeedback(score=3, star=schemas.StarCheck(situation=True, task=True, action=True, result=False),
                              strengths=["Concreto"], improve=["Añade un resultado medible"], better_answer="… [cifra]")
    fake_llm.responses[schemas.MockStep] = schemas.MockStep(feedback=fb, next_question="Cuéntame un conflicto en tu equipo")
    step = client.post(f"/api/applications/{app_id}/mock",
                       json={"current_question": first["next_question"], "answer": "Me encanta la logística"}).json()
    assert step["feedback"]["score"] == 3 and step["feedback"]["star"]["result"] is False

    history = [{"question": first["next_question"], "answer": "Me encanta la logística", "feedback": step["feedback"]}]
    fake_llm.responses[schemas.MockStep] = schemas.MockStep(
        feedback=fb.model_copy(update={"score": 5}), next_question="(ignorada al terminar)", summary="Bien. Prioridades: …")
    end = client.post(f"/api/applications/{app_id}/mock",
                      json={"history": history, "current_question": step["next_question"], "answer": "Hablé con ambos…",
                            "finish": True}).json()
    assert end["next_question"] is None and end["average"] == 4.0 and end["saved_id"]
    assert client.get(f"/api/applications/{app_id}/mocks").json()[0]["questions"] == 2
    assert client.get(f"/api/applications/{app_id}/detail").json()["mocks"][0]["average"] == 4.0
    assert client.post(f"/api/applications/{app_id}/mock", json={"total": 50}).status_code == 422


# ── Resultados ──────────────────────────────────────────────────


def _sent(db, source, *, replied=False, category="solicitud_info", status=ApplicationStatus.APPLIED, days=10, now=None):
    from app.models import EmailEvent

    now = now or datetime(2026, 10, 8, tzinfo=timezone.utc)
    job = Job(title="Backend", company=f"{source}-co", raw_text="x", source=source)
    db.add(job)
    db.commit()
    app = Application(job_id=job.id, status=status, applied_at=now - timedelta(days=days))
    db.add(app)
    db.commit()
    db.add(EmailEvent(message_id=f"c{app.id}", sender="x", subject="Recibida", category="confirmacion_recepcion",
                      confidence=1, application_id=app.id, received_at=now - timedelta(days=days)))
    if replied:
        db.add(EmailEvent(message_id=f"r{app.id}", sender="x", subject="Hola", category=category, confidence=1,
                          application_id=app.id, received_at=now - timedelta(days=days - 4)))
    db.commit()
    return app


def test_stats_funnel_sources_and_weights(db):
    from app.services.stats import build_stats, source_weights

    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    for i in range(6):  # Greenhouse: 4 de 6 responden
        _sent(db, "greenhouse", replied=i < 4, category="entrevista" if i == 0 else "solicitud_info", now=now)
    for i in range(6):  # Remotive: 1 de 6
        _sent(db, "remotive", replied=i == 0, category="rechazo", now=now)
    _sent(db, "lever", status=ApplicationStatus.OFFER, now=now)  # pocos datos
    pending = Job(title="Sin enviar", raw_text="x")
    db.add(pending)
    db.commit()
    db.add(Application(job_id=pending.id))  # en «Por aplicar»: no cuenta
    db.commit()
    s = build_stats(db, now)
    f = s["funnel"]
    assert (f["applied"], f["responses"], f["interviews"], f["offers"], f["rejected"]) == (13, 6, 2, 1, 1)
    gh = next(g for g in s["by_source"] if g["key"] == "greenhouse")
    assert (gh["response_rate"], gh["enough"]) == (67, True)
    assert next(g for g in s["by_source"] if g["key"] == "lever")["enough"] is False
    assert s["reply_days"]["median"] == 4
    assert sum(w["applied"] for w in s["weekly"]) == 13
    w = source_weights(db)
    # proporcional a cuánto se aleja de la media (46 %), acotado a ±10 %
    assert (w["greenhouse"], w["remotive"]) == (1.044, 0.936) and "lever" not in w


def test_stats_endpoint_empty(client):
    s = client.get("/api/stats").json()
    assert s["funnel"]["applied"] == 0 and s["source_weights"] == {} and len(s["weekly"]) == 12


def test_board_has_offer_column(client):
    assert "oferta" in client.get("/api/applications/board").json()


# ── Ofertas, negociación y Gmail ───────────────────────────────


@pytest.fixture
def with_cv(client, tmp_path):
    with open(tmp_path / "cv.txt", "w") as f:
        f.write("x" * 100)
    with open(tmp_path / "cv.txt", "rb") as f:
        client.post("/api/cv", files={"file": ("cv.txt", f, "text/plain")})


def _new_app(client, text):
    job = client.post("/api/jobs", json={"text": text * 6}).json()
    return next(a["id"] for a in client.get("/api/applications").json() if a["job_id"] == job["id"])


def test_offer_negotiation_and_comparison(client, fake_llm, with_cv):
    from app import schemas

    a = _new_app(client, "Platform Engineer en Orbit ")
    assert client.post(f"/api/applications/{a}/negotiate", json={}).status_code == 409  # sin condiciones
    saved = client.put(f"/api/applications/{a}/offer", json={"base_salary": 48000, "variable": 4000, "modality": "híbrido"}).json()
    assert saved == {"base_salary": 48000, "variable": 4000, "modality": "híbrido", "currency": "EUR"}
    d = client.get(f"/api/applications/{a}/detail").json()
    assert d["status"] == "oferta" and d["offer"]["base_salary"] == 48000 and d["other_offers"] == 0

    fake_llm.responses[schemas.NegotiationOut] = schemas.NegotiationOut(
        assessment="Correcta para el mercado (estimación: contrástalo)", leverage=["4 años con Python"],
        asks=[schemas.NegotiationAsk(item="Salario", ask="52.000 € fijos", rationale="Experiencia en K8s del CV")],
        risks=["No des un ultimátum"], call_script=["Agradece", "Pide"],
        email=schemas.MessageDraft(subject="Oferta Platform Engineer", body="Hola…"))
    n = client.post(f"/api/applications/{a}/negotiate", json={"target": "52k", "priorities": ["remoto"]}).json()
    assert n["asks"][0]["ask"] == "52.000 € fijos" and n["email"]["subject"] == "Oferta Platform Engineer"
    from app.services.interviews import offer_text
    assert "Total anual estimado: 52,000 EUR" in offer_text({"base_salary": 48000, "variable": 4000})

    assert client.post("/api/applications/compare-offers", json={}).status_code == 409  # solo una oferta
    b = _new_app(client, "Backend Engineer en Fintechly ")
    client.put(f"/api/applications/{b}/offer", json={"base_salary": 50000, "modality": "remoto"})
    fake_llm.responses[schemas.OfferComparison] = schemas.OfferComparison(
        offers=[schemas.OfferScore(application_id=a, pros=["Variable"], cons=["Híbrido"], score=7),
                schemas.OfferScore(application_id=b, pros=["Remoto"], cons=["Sin variable"], score=8)],
        recommendation="Fintechly si priorizas el remoto", questions_to_clarify=["¿Revisión salarial?"])
    c = client.post("/api/applications/compare-offers", json={"priorities": ["remoto"]}).json()
    assert [(o["application_id"], o["total"], o["score"]) for o in c["offers"]] == [(a, 52000, 7), (b, 50000, 8)]
    assert client.get(f"/api/applications/{a}/detail").json()["other_offers"] == 1


def test_offer_email_moves_to_offer_and_never_backwards(client, fake_llm, monkeypatch):
    from app import schemas
    from tests.conftest import FAKE_EMAIL

    sent = []
    monkeypatch.setattr("app.routers.emails.notify", lambda title, msg: sent.append(title))
    a = _new_app(client, "Backend en Acme Cloud ")
    fake_llm.responses[schemas.EmailClassification] = FAKE_EMAIL.model_copy(update={"category": "oferta", "interview_datetime": None})
    client.post("/api/emails/classify", json={"message_id": "o1", "sender": "rrhh@acmecloud.io", "subject": "Oferta", "body": "…"})
    assert client.get(f"/api/applications/{a}/detail").json()["status"] == "oferta" and "🎉 ¡Oferta recibida!" in sent
    # un acuse de recibo que llega tarde no la devuelve a «Aplicado»
    fake_llm.responses[schemas.EmailClassification] = FAKE_EMAIL.model_copy(update={"category": "confirmacion_recepcion"})
    client.post("/api/emails/classify", json={"message_id": "o2", "sender": "rrhh@acmecloud.io", "subject": "Recibido", "body": "…"})
    assert client.get(f"/api/applications/{a}/detail").json()["status"] == "oferta"
    fake_llm.responses[schemas.EmailClassification] = FAKE_EMAIL.model_copy(update={"category": "rechazo"})
    client.post("/api/emails/classify", json={"message_id": "o3", "sender": "rrhh@acmecloud.io", "subject": "Lo sentimos", "body": "…"})
    assert client.get(f"/api/applications/{a}/detail").json()["status"] == "rechazado"


class FakeGmail:
    def __init__(self):
        self.created = []

    def users(self):
        return self

    def drafts(self):
        return self

    def create(self, userId, body):  # noqa: N803  (nombre de la API de Gmail)
        self.created.append(body)
        return self

    def execute(self):
        return {"id": "d1", "message": {"id": "m1"}}


def test_gmail_draft_in_thread(client, fake_llm, monkeypatch):
    import base64
    import email

    from app import schemas
    from app.config import get_settings
    from app.services import email_sources
    from tests.conftest import FAKE_EMAIL

    a = _new_app(client, "Backend en Acme Cloud ")
    assert client.post(f"/api/applications/{a}/gmail-draft", json={"to": "x@y.z", "subject": "s", "body": "b"}).status_code == 409

    fake_llm.responses[schemas.EmailClassification] = FAKE_EMAIL.model_copy(update={"category": "solicitud_info"})
    client.post("/api/emails/classify", json={"message_id": "g1", "sender": "Laura <laura@acmecloud.io>", "subject": "Una pregunta",
                                              "body": "…", "thread_id": "t-42", "rfc_message_id": "<abc@acmecloud.io>"})
    gmail = FakeGmail()
    monkeypatch.setattr(get_settings(), "email_mode", "gmail")
    monkeypatch.setattr(email_sources, "gmail_service", lambda settings, **kw: gmail)
    r = client.post(f"/api/applications/{a}/gmail-draft",
                    json={"to": "laura@acmecloud.io", "subject": "Seguimiento", "body": "Hola Laura"}).json()
    assert r["url"].endswith("#drafts?compose=m1") and r["thread_id"] == "t-42"
    msg = gmail.created[0]["message"]
    assert msg["threadId"] == "t-42"
    parsed = email.message_from_bytes(base64.urlsafe_b64decode(msg["raw"]))
    assert parsed["Subject"] == "Re: Una pregunta" and parsed["In-Reply-To"] == "<abc@acmecloud.io>"
    assert parsed["To"] == "laura@acmecloud.io" and "Hola Laura" in parsed.get_payload()
