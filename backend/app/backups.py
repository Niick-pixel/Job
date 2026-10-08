"""Copias de seguridad de la base de datos (SQLite).

Se hace una copia antes de que una versión nueva migre la base de datos y otra cada semana. Se guardan
en data/backups/ (las 8 más recientes). Para restaurar: `jobtracker restore-db` o, a mano, copiar el
fichero sobre data/jobtracker.db con la app cerrada.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

KEEP = 8
WEEKLY = timedelta(days=7)


def backup_dir(db_path: Path) -> Path:
    return db_path.parent / "backups"


def list_backups(db_path: Path) -> list[Path]:
    d = backup_dir(db_path)
    return sorted(d.glob("jobtracker-*.db"), key=lambda p: p.stat().st_mtime, reverse=True) if d.exists() else []


def make_backup(db_path: Path, label: str) -> Path | None:
    """Copia consistente aunque otro proceso esté escribiendo (API de copia de SQLite)."""
    if not db_path.exists() or db_path.stat().st_size == 0:
        return None
    d = backup_dir(db_path)
    d.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    dest = d / f"jobtracker-{stamp}-{label}.db"
    n = 1
    while dest.exists():
        n += 1
        dest = d / f"jobtracker-{stamp}-{label}-{n}.db"
    tmp = dest.with_suffix(".tmp")
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        out = sqlite3.connect(tmp)
        with out:
            src.backup(out)
        out.close()
    finally:
        src.close()
    os.replace(tmp, dest)
    for old in list_backups(db_path)[KEEP:]:
        old.unlink(missing_ok=True)
    return dest


def maybe_backup(db_path: Path, version: str, now: datetime | None = None) -> Path | None:
    """Antes de migrar a una versión nueva, o si la última copia tiene más de una semana."""
    now = now or datetime.now()
    marker = db_path.parent / ".db_version"
    previous = marker.read_text().strip() if marker.exists() else None
    made = None
    if not db_path.exists():
        pass
    elif previous != version:
        made = make_backup(db_path, f"antes-de-{version}")
    else:
        latest = list_backups(db_path)
        if not latest or now - datetime.fromtimestamp(latest[0].stat().st_mtime) > WEEKLY:
            made = make_backup(db_path, "semanal")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(version)
    return made
