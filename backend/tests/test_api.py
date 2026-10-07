from pathlib import Path

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


def _upload_cv(client):
    with open(SAMPLES / "sample_cv.txt", "rb") as f:
        r = client.post("/api/cv", files={"file": ("cv.txt", f, "text/plain")})
    assert r.status_code == 200, r.text
    return r.json()


def _create_job(client):
    r = client.post("/api/jobs", json={"text": (SAMPLES / "sample_job.txt").read_text()})
    assert r.status_code == 200, r.text
    return r.json()


def test_full_flow(client):
    cv = _upload_cv(client)
    assert cv["full_name"] == "Nicolás Ejemplo"

    job = _create_job(client)
    assert job["urgency"]["level"] == "ideal"

    match = client.post(f"/api/jobs/{job['id']}/match", params={"cv_id": cv["id"]}).json()
    # 0.7 * 80 + 0.3 * 60 = 74
    assert match["score"] == 74.0
    assert match["analysis"]["gaps"] == ["Kubernetes"]

    board = client.get("/api/applications/board").json()
    assert len(board["por_aplicar"]) == 1
    assert board["por_aplicar"][0]["match_score"] == 74.0


def test_email_moves_card_to_interview(client):
    _create_job(client)
    r = client.post("/api/emails/classify", json={
        "message_id": "x1", "sender": "rrhh@acmecloud.io", "subject": "Entrevista", "body": "¿Hablamos el jueves?",
    })
    assert r.status_code == 200
    assert r.json()["application_id"] is not None
    board = client.get("/api/applications/board").json()
    assert len(board["entrevista"]) == 1

    # Idempotente: el mismo correo no se reprocesa
    client.post("/api/emails/classify", json={
        "message_id": "x1", "sender": "rrhh@acmecloud.io", "subject": "Entrevista", "body": "...",
    })
    assert len(client.get("/api/emails").json()) == 1


def test_job_requires_text_or_url(client):
    assert client.post("/api/jobs", json={}).status_code == 422


def test_move_card(client):
    _create_job(client)
    app_id = client.get("/api/applications").json()[0]["id"]
    r = client.patch(f"/api/applications/{app_id}", json={"status": "aplicado"})
    assert r.json()["status"] == "aplicado"
    assert r.json()["applied_at"] is not None
