"""Ajustes (claves API, IA, apariencia, Gmail), protección CSRF e interfaz."""
import json
import os
import stat

import pytest

from app.config import get_settings
from app.services import secrets


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Cada test escribe en su propio .env y no deja variables en el proceso."""
    env_file = tmp_path / ".env"
    monkeypatch.setattr(secrets, "env_path", lambda: env_file)
    monkeypatch.setattr("app.routers.settings.env_path", lambda: env_file)
    saved = dict(os.environ)
    yield env_file
    os.environ.clear()
    os.environ.update(saved)
    get_settings.cache_clear()


# ── Fichero .env ────────────────────────────────────────────────


def test_write_env_preserves_comments_and_order(isolated_env):
    isolated_env.write_text("# cabecera\nAA=1\n# nota\nBB=2\n")
    secrets.write_env({"AA": "uno", "CC": "valor con espacios", "BB": None})
    assert isolated_env.read_text() == '# cabecera\nAA=uno\n# nota\nCC="valor con espacios"\n'
    assert secrets.read_env() == {"AA": "uno", "CC": "valor con espacios"}
    assert stat.S_IMODE(isolated_env.stat().st_mode) == 0o600


def test_write_env_rejects_injection():
    with pytest.raises(ValueError):
        secrets.write_env({"OK_NAME": "a\nEVIL=1"})
    with pytest.raises(ValueError):
        secrets.write_env({"bad name": "x"})


def test_write_env_applies_live():
    secrets.write_env({"LLM_EFFORT": "high"})
    assert get_settings().llm_effort == "high"


def test_mask():
    assert secrets.mask("sk-ant-api03-abcdefghijklmnop1234") == "sk-ant…1234"
    assert secrets.mask("short") == "•••••" and secrets.mask(None) is None


# ── API de claves ───────────────────────────────────────────────


def test_keys_crud_never_returns_full_value(client, isolated_env):
    keys = client.get("/api/settings/keys").json()
    claude = next(k for k in keys["keys"] if k["name"] == "ANTHROPIC_API_KEY")
    assert claude["required"] and claude["steps"] and claude["url"].startswith("https://console.anthropic.com")

    secret = "sk-ant-api03-SUPERSECRETVALUE-9876"
    r = client.put("/api/settings/keys", json={"name": "ANTHROPIC_API_KEY", "value": f"  {secret}  "})
    assert r.status_code == 200 and r.json()["preview"] == "sk-ant…9876"
    assert secrets.read_env()["ANTHROPIC_API_KEY"] == secret
    assert get_settings().anthropic_api_key == secret  # aplicada sin reiniciar

    client.put("/api/settings/keys", json={"name": "mi_servicio_token", "value": "abc123456789"})
    listing = client.get("/api/settings/keys").text
    assert secret not in listing and "abc123456789" not in listing
    assert any(c["name"] == "MI_SERVICIO_TOKEN" for c in client.get("/api/settings/keys").json()["custom"])

    assert client.delete("/api/settings/keys/MI_SERVICIO_TOKEN").status_code == 204
    assert "MI_SERVICIO_TOKEN" not in secrets.read_env()


@pytest.mark.parametrize("name,value", [("LLM_MODEL", "x"), ("1BAD", "x"), ("OK_NAME", "  ")])
def test_keys_validation(client, name, value):
    assert client.put("/api/settings/keys", json={"name": name, "value": value}).status_code == 422


def test_test_endpoint_without_key(client):
    assert client.post("/api/settings/keys/ANTHROPIC_API_KEY/test").status_code == 409
    assert client.post("/api/settings/keys/OTRA/test").json()["ok"] is None


# ── IA, apariencia, Gmail ───────────────────────────────────────


def test_ai_settings(client):
    r = client.put("/api/settings/ai", json={"model": "claude-sonnet-5-5", "fast_model": "claude-haiku-5-5", "effort": "high"})
    assert r.json()["model"] == "claude-sonnet-5-5" and get_settings().llm_effort == "high"
    assert client.put("/api/settings/ai", json={"model": "gpt-4", "fast_model": "claude-haiku-5-5", "effort": "high"}).status_code == 422


def test_ui_settings_and_index_injection(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.routers.settings.DATA_DIR", tmp_path)
    assert client.put("/api/settings/ui", json={"theme": "medianoche", "reduce_motion": True}).status_code == 200
    assert client.put("/api/settings/ui", json={"theme": "rosa-chicle"}).status_code == 422
    html = client.get("/").text
    assert 'data-theme="medianoche"' in html and 'data-motion="reduce"' in html and "{{" not in html
    assert client.get("/").headers["cache-control"] == "no-store"
    asset = client.get("/assets/js/app.js")
    assert asset.status_code == 200 and asset.headers["cache-control"] == "no-cache"


def test_all_frontend_modules_are_served(client):
    """Cada vista que la navegación puede cargar existe (un 404 dejaría la sección en blanco)."""
    for view in ["bandeja", "ofertas", "kanban", "correos", "agente", "perfil", "ajustes", "_shared"]:
        assert client.get(f"/assets/js/views/{view}.js").status_code == 200, view
    for f in ["js/api.js", "js/ui.js", "js/theme.js", "css/app.css", "css/themes.css", "favicon.svg"]:
        assert client.get(f"/assets/{f}").status_code == 200, f


def test_themes_are_consistent_between_backend_css_and_window(client):
    """Los 8 temas existen en el CSS, en el selector del backend y en el color de la ventana nativa."""
    from app.desktop import THEME_BG
    from app.routers.settings import THEMES

    css = client.get("/assets/css/themes.css").text
    named = [t for t in THEMES if t != "auto"]
    assert len(named) >= 6 and set(named) == set(THEME_BG)
    for t in named:
        block = css.split(f'[data-theme="{t}"]')[1].split("}")[0]
        assert f"--bg: {THEME_BG[t]};" in block, t  # sin destello al abrir la ventana


def test_gmail_credentials_upload(client, tmp_path, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "gmail_credentials_file", tmp_path / "creds.json")
    monkeypatch.setattr(s, "gmail_token_file", tmp_path / "token.json")
    monkeypatch.setattr("app.routers.settings.get_settings", lambda: s)
    bad = client.post("/api/settings/gmail/credentials", files={"file": ("c.json", b'{"web": {}}', "application/json")})
    assert bad.status_code == 422
    ok = client.post("/api/settings/gmail/credentials",
                     files={"file": ("c.json", json.dumps({"installed": {"client_id": "x"}}).encode(), "application/json")})
    assert ok.status_code == 200 and ok.json()["credentials"] is True
    assert stat.S_IMODE((tmp_path / "creds.json").stat().st_mode) == 0o600
    assert secrets.read_env()["EMAIL_MODE"] == "gmail"


# ── Seguridad ───────────────────────────────────────────────────


def test_csrf_guard_blocks_requests_without_header(client):
    from fastapi.testclient import TestClient

    from app.main import app

    bare = TestClient(app)
    assert bare.post("/api/agent/run").status_code == 403
    assert bare.put("/api/settings/keys", json={"name": "X_KEY", "value": "v"}).status_code == 403
    assert bare.get("/api/settings/ai").status_code == 200  # lecturas permitidas
    assert "X_KEY" not in secrets.read_env()


def test_desktop_window_background(tmp_path, monkeypatch):
    from app import desktop

    monkeypatch.setattr(desktop, "DATA_DIR", tmp_path)
    (tmp_path / "ui.json").write_text('{"theme": "bosque"}')
    assert desktop.window_background() == "#111a16"
    (tmp_path / "ui.json").write_text('{"theme": "auto"}')
    monkeypatch.setattr(desktop, "_system_dark", lambda: True)
    assert desktop.window_background() == desktop.THEME_BG["grafito"]
