"""jobtracker restore-db: lista y restaura copias de seguridad de los datos."""
import os
import time
from pathlib import Path

import jobtracker as jt


def test_restore_db(tmp_path, monkeypatch, capsys):
    home = tmp_path / "app"
    monkeypatch.setenv("JOBTRACKER_HOME", str(home))
    monkeypatch.setenv("JOBTRACKER_ALLOW_NON_MAC", "1")
    data = home / "data"
    (data / "backups").mkdir(parents=True)
    (data / "jobtracker.db").write_text("actual")
    old, new = data / "backups" / "jobtracker-1-antes-de-0.7.0.db", data / "backups" / "jobtracker-2-semanal.db"
    old.write_text("vieja")
    new.write_text("reciente")
    os.utime(old, (time.time() - 100, time.time() - 100))

    assert jt.main(["restore-db"]) == 0  # sin --yes solo lista
    out = capsys.readouterr().out
    assert out.index("semanal") < out.index("antes-de-0.7.0") and (data / "jobtracker.db").read_text() == "actual"

    assert jt.main(["restore-db", "--yes"]) == 0
    assert (data / "jobtracker.db").read_text() == "reciente"
    assert any("antes-de-restaurar" in p.name for p in (data / "backups").iterdir())  # la actual se guardó

    assert jt.main(["restore-db", old.name]) == 0
    assert (data / "jobtracker.db").read_text() == "vieja"
    assert jt.main(["restore-db", "no-existe.db"]) == 1


def test_restore_db_without_backups(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBTRACKER_HOME", str(tmp_path / "app"))
    assert jt.main(["restore-db", "--yes"]) == 1
