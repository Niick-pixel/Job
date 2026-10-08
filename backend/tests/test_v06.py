"""0.6.0: entrevistas (calendario y dossier) y seguimiento."""
from datetime import datetime, timedelta, timezone

import pytest

from app import schemas
from app.services.interviews import build_ics, contact_from_senders

# ── Calendario ──────────────────────────────────────────────────


def _unfold(ics: str) -> str:
    return ics.replace("\r\n ", "")


def test_ics_local_time_is_floating_and_valid():
    ics = build_ics(uid="u1", start=datetime(2026, 10, 9, 10, 0), summary="Entrevista · Orbit — Platform Engineer",
                    description="Línea 1\nNotas: café, té; y más", url="https://jobs.lever.co/orbit/1",
                    now=datetime(2026, 10, 8, tzinfo=timezone.utc))
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    flat = _unfold(ics)
    assert "DTSTART:20261009T100000\r\n" in flat and "DTEND:20261009T110000\r\n" in flat  # hora local, sin «Z»
    assert "DESCRIPTION:Línea 1\\nNotas: café\\, té\\; y más" in flat
    assert "TRIGGER:-PT60M" in flat and "UID:u1" in flat
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))


def test_ics_aware_time_is_utc_and_long_lines_fold():
    start = datetime(2026, 10, 9, 10, 0, tzinfo=timezone(timedelta(hours=2)))
    ics = build_ics(uid="u2", start=start, summary="Entrevista", description="á" * 200)
    assert "DTSTART:20261009T080000Z" in ics
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))
    assert "á" * 200 in _unfold(ics)  # el plegado no rompe caracteres multibyte


def test_contact_skips_no_reply():
    assert contact_from_senders(["no-reply@datanova.com", "Laura <laura@orbit.io>"]) == "laura@orbit.io"
    assert contact_from_senders(["jobs-noreply@x.com"]) is None


# ── Ficha, dossier y seguimiento vía API ───────────────────────

PREP = schemas.InterviewPrepOut(
    company_summary="Orbit hace logística (verifícalo)", role_focus=["APIs en Python"],
    likely_questions=[schemas.PrepQuestion(question="¿Diseño de una API?", why="Es el día a día",
                                           answer_outline="API REST con Flask (CV)")],
    technical_topics=["Kubernetes"], questions_to_ask=["¿Cómo es el on-call?"],
    weak_spots=["Kubernetes: experiencia solo con Docker"], checklist=["Probar la cámara"])
DRAFT = schemas.MessageDraft(subject="Seguimiento candidatura", body="Hola Laura…\nNicolás")


@pytest.fixture
def app_id(client, fake_llm, tmp_path):
    fake_llm.responses[schemas.InterviewPrepOut] = PREP
    fake_llm.responses[schemas.MessageDraft] = DRAFT
    with open(tmp_path / "cv.txt", "w") as f:
        f.write("x" * 100)
    with open(tmp_path / "cv.txt", "rb") as f:
        client.post("/api/cv", files={"file": ("cv.txt", f, "text/plain")})
    job = client.post("/api/jobs", json={"text": "Platform Engineer en Orbit " * 6, "url": "https://jobs.lever.co/orbit/1"}).json()
    return next(a["id"] for a in client.get("/api/applications").json() if a["job_id"] == job["id"])


def test_interview_calendar_flow(client, app_id):
    assert client.post(f"/api/applications/{app_id}/calendar").status_code == 409  # sin fecha aún
    client.patch(f"/api/applications/{app_id}", json={"status": "entrevista", "interview_at": "2026-10-09T10:00:00"})
    ics = client.get(f"/api/applications/{app_id}/calendar.ics")
    # «10:00» escrito por el usuario es hora local del Mac: se guarda y exporta en UTC
    expected = datetime(2026, 10, 9, 10, 0).astimezone().astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    assert ics.headers["content-type"].startswith("text/calendar") and f"DTSTART:{expected}" in ics.text
    assert client.get(f"/api/applications/{app_id}/detail").json()["interview_at"].endswith(("Z", "+00:00"))
    r = client.post(f"/api/applications/{app_id}/calendar").json()  # fuera de macOS: descarga
    assert r == {"opened": False, "url": f"/api/applications/{app_id}/calendar.ics"}
    client.patch(f"/api/applications/{app_id}", json={"clear_interview": True})
    assert client.get(f"/api/applications/{app_id}/detail").json()["interview_at"] is None


def test_interview_prep_is_stored_in_detail(client, app_id):
    assert client.get(f"/api/applications/{app_id}/detail").json()["prep"] is None
    prep = client.post(f"/api/applications/{app_id}/prep").json()
    assert prep["weak_spots"] == ["Kubernetes: experiencia solo con Docker"]
    assert client.get(f"/api/applications/{app_id}/detail").json()["prep"]["likely_questions"][0]["question"] == "¿Diseño de una API?"


def test_follow_up_draft_and_suggestion(client, app_id):
    from app.database import get_session
    from app.main import app as fastapi_app
    from app.models import Application, EmailEvent

    session = next(fastapi_app.dependency_overrides[get_session]())
    a = session.get(Application, app_id)
    a.status, a.applied_at = "aplicado", datetime.now(timezone.utc) - timedelta(days=9)
    session.add(a)
    session.add(EmailEvent(message_id="r1", sender="Laura <laura@orbit.io>", subject="Recibido", category="confirmacion_recepcion",
                           confidence=1, application_id=app_id, received_at=datetime.now(timezone.utc) - timedelta(days=9)))
    session.commit()

    d = client.get(f"/api/applications/{app_id}/detail").json()
    assert d["suggest_follow_up"] is True and d["days_since_applied"] == 9 and d["contact"] == "laura@orbit.io"
    msg = client.post(f"/api/applications/{app_id}/message", json={"kind": "seguimiento"}).json()
    assert msg == {"subject": "Seguimiento candidatura", "body": "Hola Laura…\nNicolás", "to": "laura@orbit.io"}
    assert client.get("/api/agent/digest").json()["stale"][0]["application_id"] == app_id

    client.post(f"/api/applications/{app_id}/follow-up-sent")
    assert client.get("/api/agent/digest").json()["stale"] == []  # no insistir tras el seguimiento
    assert client.post(f"/api/applications/{app_id}/message", json={"kind": "otro"}).status_code == 422


def test_interview_email_notifies(client, fake_llm, monkeypatch):
    sent = []
    monkeypatch.setattr("app.routers.emails.notify", lambda title, msg: sent.append((title, msg)))
    client.post("/api/emails/classify", json={"message_id": "i1", "sender": "rrhh@acmecloud.io",
                                              "subject": "Entrevista", "body": "¿Hablamos?"})
    assert sent and sent[0][0] == "🎤 Entrevista detectada" and "Acme Cloud" in sent[0][1]


def test_interview_email_with_naive_datetime_does_not_crash(client, fake_llm):
    """Regresión: la IA devuelve «el jueves a las 10:00» sin zona; antes fallaba al guardar."""
    from tests.conftest import FAKE_EMAIL

    fake_llm.responses[schemas.EmailClassification] = FAKE_EMAIL.model_copy(
        update={"interview_datetime": datetime(2026, 10, 9, 10, 0)})
    client.post("/api/jobs", json={"text": "Backend en Acme Cloud " * 6})
    r = client.post("/api/emails/classify", json={"message_id": "n1", "sender": "rrhh@acmecloud.io",
                                                  "subject": "Entrevista", "body": "El jueves a las 10:00"})
    assert r.status_code == 200, r.text
    board = client.get("/api/applications/board").json()
    assert board["entrevista"][0]["interview_at"].endswith(("Z", "+00:00"))


def test_detail_sheet_script_is_served(client):
    js = client.get("/assets/js/detail.js")
    assert js.status_code == 200 and "openApplication" in js.text
    assert client.get("/api/applications/999/detail").status_code == 404
