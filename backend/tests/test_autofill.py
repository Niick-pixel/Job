"""Relleno de formularios: se prueba de verdad en un navegador headless con formularios que imitan
Greenhouse, Lever y Ashby. Se omite si no hay ningún Chromium/Chrome disponible."""
import functools
import http.server
import json
import os
import shutil
import threading
from pathlib import Path

import pytest

from app.services import autofill

FORMS = Path(__file__).with_name("forms")
CV = {"full_name": "Nicolás Pérez Gil", "email": "nico@example.com", "phone": "+34 600 000 000",
      "location": "Madrid", "links": ["https://linkedin.com/in/nico", "https://github.com/nico", "https://nico.dev"],
      "experience": [{"company": "Acme Cloud", "role": "Backend"}]}
PKG = {"cover_letter": "Estimado equipo:\n\nMe interesa el puesto.", "answers": [
    {"key": "por_que_empresa", "question": "¿Por qué quieres trabajar en nuestra empresa?", "answer": "Por su producto de logística."},
    {"key": "kubernetes", "question": "Describe your experience running Kubernetes in production", "answer": "Dos años con EKS."},
    {"key": "pendiente", "question": "¿Algo más?", "answer": None}]}
BANK = [{"key": "expectativa_salarial", "question": "¿Cuáles son tus expectativas salariales?", "answer": "45.000-50.000 € brutos/año"},
        {"key": "disponibilidad", "question": "¿Cuándo podrías incorporarte?", "answer": "15 días"},
        {"key": "nivel_ingles", "question": "¿Cuál es tu nivel de inglés?", "answer": "C1 (avanzado)"},
        {"key": "permiso_trabajo", "question": "¿Permiso de trabajo?", "answer": "Sí, ciudadano UE"},
        {"key": "modalidad", "question": "¿Modalidad?", "answer": ""}]


def find_browser():
    for p in [os.getenv("JOBTRACKER_BROWSER"), "/opt/pw-browsers/chromium", shutil.which("google-chrome"),
              shutil.which("chromium"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]:
        if p and Path(p).exists():
            return p
    return None


BROWSER = find_browser()
needs_browser = pytest.mark.skipif(not BROWSER, reason="sin navegador Chromium/Chrome")


def test_profile_and_urls():
    p = autofill.build_profile(CV, PKG, BANK)
    assert (p["first_name"], p["last_name"]) == ("Nicolás", "Pérez Gil")
    assert p["linkedin"] == "https://linkedin.com/in/nico" and p["website"] == "https://nico.dev"
    assert p["current_company"] == "Acme Cloud"
    assert p["answers_by_key"]["por_que_empresa"] == "Por su producto de logística."  # la adaptada manda
    assert "modalidad" not in p["answers_by_key"]  # respuestas vacías no se usan
    assert not any(a["question"] == "¿Algo más?" for a in p["answers"])
    assert autofill.form_url("https://jobs.lever.co/orbit/abc-123") == "https://jobs.lever.co/orbit/abc-123/apply"
    assert autofill.form_url("https://jobs.ashbyhq.com/linear/x?src=a") == "https://jobs.ashbyhq.com/linear/x/application"
    assert autofill.form_url("https://boards.greenhouse.io/orbit/jobs/1") == "https://boards.greenhouse.io/orbit/jobs/1"


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=BROWSER)
        yield b.new_page()
        b.close()


def fill(page, name):
    page.goto((FORMS / name).as_uri())
    return page.evaluate(autofill.FILL_JS, autofill.build_profile(CV, PKG, BANK))


@needs_browser
def test_greenhouse_like(page):
    r = fill(page, "greenhouse.html")
    v = lambda sel: page.input_value(sel)  # noqa: E731
    assert (v("#first_name"), v("#last_name"), v("#email"), v("#phone")) == ("Nicolás", "Pérez Gil", "nico@example.com", "+34 600 000 000")
    assert v("#q1") == "https://linkedin.com/in/nico" and v("#q2") == "45.000-50.000 € brutos/año"
    assert v("#q3") == "Por su producto de logística."
    assert v("#q4") == "Dos años con EKS."            # pregunta propia: emparejada con tus respuestas
    assert v("#pre") == "Ya escrito"                 # no pisa lo que ya había
    assert v("#gender") == ""                        # demográficas: nunca
    assert any("sponsorship" in m for m in r["missing"])  # sí/no de visado: para ti, señalado
    assert {f["kind"] for f in r["files"]} == {"resume", "cover"}
    assert page.get_attribute("#resume", "data-jt-file") == "resume"


@needs_browser
def test_lever_like(page):
    r = fill(page, "lever.html")
    v = lambda n: page.input_value(f'[name="{n}"]')  # noqa: E731
    assert v("name") == "Nicolás Pérez Gil"          # sin campo de apellidos → nombre completo
    assert v("org") == "Acme Cloud" and v("urls[GitHub]") == "https://github.com/nico"
    assert v("cards[0][field0]") == "15 días"
    assert v("comments").startswith("Estimado equipo")
    assert r["missing"] == [] and r["files"][0]["kind"] == "resume"


@needs_browser
def test_ashby_like_react_state(page):
    r = fill(page, "ashby.html")
    state = page.evaluate("window.reactState")
    assert state["_systemfield_name"] == "Nicolás Pérez Gil" and state["_systemfield_email"] == "nico@example.com"
    assert state["_systemfield_location"] == "Madrid"
    assert page.input_value('[name="english"]') == "c1"  # opción del desplegable que coincide con tu respuesta
    assert len(r["filled"]) == 4


@needs_browser
def test_runner_end_to_end(tmp_path, monkeypatch):
    """El proceso completo en modo headless: navega, rellena, sube CV y carta, captura y estado."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FORMS))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("JOBTRACKER_BROWSER", BROWSER)
    monkeypatch.setattr(autofill, "WORK", tmp_path / "autofill")
    monkeypatch.setattr(autofill, "PROFILE_DIR", tmp_path / "profile")
    cv_pdf = tmp_path / "cv.pdf"
    cv_pdf.write_bytes(b"%PDF-1.4 cv")
    out = {}
    run = lambda: out.update(final=autofill.run(  # noqa: E731  (hilo propio: la API síncrona no admite otro bucle activo)
        7, f"http://127.0.0.1:{srv.server_address[1]}/greenhouse.html",
        autofill.build_profile(CV, PKG, BANK), {"resume": str(cv_pdf)}, headless=True))
    try:
        t = threading.Thread(target=run)
        t.start()
        t.join(90)
    finally:
        srv.shutdown()
    final = out["final"]
    st = json.loads((tmp_path / "autofill" / "7.json").read_text())
    assert final["state"] == "closed" and st["submitted"] is False
    assert len(st["filled"]) >= 7 and st["uploaded"] == ["resume"]  # sin carta en PDF: no se sube
    assert any("sponsorship" in m for m in st["missing"])
    assert (tmp_path / "autofill" / "7.png").stat().st_size > 1000


def test_api_requires_browser_and_url(client, monkeypatch):
    from app.routers import autofill as router

    monkeypatch.setattr(router, "browser_available", lambda: False)
    assert client.post("/api/packages/999/autofill").status_code == 404
    assert client.get("/api/autofill/browser").json()["installing"] is False
