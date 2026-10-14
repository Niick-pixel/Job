"""0.9.1: buscar actualizaciones, novedades, tus datos y recarga del actualizador."""
import json
import subprocess
import sys
from pathlib import Path

from app.routers import system


def test_changelog_sections():
    text = "# Changelog\n\nIntro\n\n## 0.9.1 — calidad de vida\n\n- **A**: uno\n  - sub\n\n## 0.9.0\n\n- B\n\n## 0.8.0\n\n- C\n"
    s = system.changelog_sections(text)
    assert [x["version"] for x in s] == ["0.9.1", "0.9.0", "0.8.0"] and s[0]["title"] == "calidad de vida"
    assert s[0]["body"].startswith("- **A**") and s[1]["body"] == "- B"


def test_changelog_endpoint(client):
    r = client.get("/api/system/changelog", params={"limit": 1}).json()
    assert len(r["sections"]) == 1 and r["sections"][0]["version"] == r["version"]
    # desde una versión anterior: todo lo nuevo, sin incluir la que ya tenía
    r = client.get("/api/system/changelog", params={"since": "0.8.0", "limit": 5}).json()
    assert "0.8.0" not in [x["version"] for x in r["sections"]] and r["sections"][0]["version"] == r["version"]


def test_dev_mode_update_endpoints(client):
    v = client.get("/api/system/version").json()
    assert v["installed"] is False and v["updating"] is False
    assert client.post("/api/system/check").status_code == 409
    assert client.post("/api/system/auto-update", json={"enabled": False}).status_code == 409


def test_installed_check_runs_cli(client, tmp_path, monkeypatch):
    home = tmp_path / "app"
    (home / "current" / "installer").mkdir(parents=True)
    (home / "state.json").write_text(json.dumps({"current": "0.9.0", "auto_update": True}))
    monkeypatch.setattr(system, "JOBTRACKER_HOME", home)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd[2:])
        (home / "state.json").write_text(json.dumps({"current": "0.9.0", "available": {"version": "0.9.1", "notes": "x"},
                                                     "last_check": "2026-10-14T10:00:00+00:00"}))
        return subprocess.CompletedProcess(cmd, 0, "Nueva versión disponible: 0.9.1", "")
    monkeypatch.setattr(system.subprocess, "run", fake_run)
    r = client.post("/api/system/check").json()
    assert calls == [["check"]] and r["update_available"] and r["latest"] == "0.9.1"
    client.post("/api/system/auto-update", json={"enabled": False})
    assert calls[-1] == ["config", "auto-update", "off"]

    # con una actualización en curso no se comprueba (el actualizador tiene el candado)
    import fcntl
    with open(home / ".lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        assert system.update_running() is True
        assert client.post("/api/system/check").json()["message"] == "Hay una actualización en curso"
    assert system.update_running() is False


def test_data_and_backups(client, tmp_path, monkeypatch):
    import sqlite3

    monkeypatch.setattr(system, "DATA_DIR", tmp_path)
    assert client.get("/api/system/data").json()["backups"] == []
    assert client.post("/api/system/backups").status_code == 409  # sin base de datos
    con = sqlite3.connect(tmp_path / "jobtracker.db")
    con.execute("create table t (x)")
    con.commit()
    con.close()
    d = client.post("/api/system/backups").json()
    assert len(d["backups"]) == 1 and "manual" in d["backups"][0]["name"] and d["data_dir"] == str(tmp_path)


def test_reload_updater_skipped_when_marker_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(system, "JOBTRACKER_HOME", tmp_path)
    monkeypatch.setattr(system.sys, "platform", "darwin")
    started = []
    monkeypatch.setattr(system.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda self: started.append(1)})())
    (tmp_path / ".updater_interval").write_text("3600")
    system.maybe_reload_updater()
    assert started == []
    (tmp_path / ".updater_interval").write_text("21600")
    system.maybe_reload_updater()
    assert started == [1]


def test_updater_interval_matches_installer():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "installer"))
    import jobtracker
    assert jobtracker.CHECK_INTERVAL_SECONDS == system.UPDATER_INTERVAL == 3600
