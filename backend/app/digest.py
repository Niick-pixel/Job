"""Envía el resumen diario como notificación de macOS.

    python -m app.digest            (launchd lo lanza cada hora; envía como mucho una vez al día,
                                     a partir de la hora elegida en las preferencias del agente)
    python -m app.digest --force    (envía ahora, para probar)
"""
import json
import sys
from datetime import date, datetime

from sqlmodel import Session

from .config import DATA_DIR
from .database import engine, init_db
from .services.agent import load_preferences
from .services.digest import build_digest, digest_message, due_reminders, reminder_message
from .services.notify import notify

STATE = DATA_DIR / "digest.json"


def _state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _last_sent() -> str | None:
    return _state().get("last_sent")


def _save(**changes) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({**_state(), **changes}))


def send_reminders(db) -> int:
    """Avisos de la víspera (o del mismo día) de cada entrevista; uno por entrevista."""
    sent = set(_state().get("reminded", []))
    due = due_reminders(db, datetime.now().astimezone(), sent)
    for r in due:
        notify(*reminder_message(r))
        print(f"[recordatorio] {r['company']} {r['when']}")
    if due:
        _save(reminded=sorted(sent | {r["key"] for r in due})[-200:])
    return len(due)


def should_send(now: datetime, hour: int, last_sent: str | None) -> bool:
    return now.hour >= hour and last_sent != now.date().isoformat()


def main(argv: list[str] | None = None) -> int:
    force = "--force" in (argv if argv is not None else sys.argv[1:])
    init_db()
    with Session(engine) as db:
        prefs = load_preferences(db)
        if prefs.interview_reminders:
            send_reminders(db)
        now = datetime.now()  # hora local del Mac
        if not force and (not prefs.digest_enabled or not should_send(now, prefs.digest_hour, _last_sent())):
            return 0
        msg = digest_message(build_digest(db))
    if msg:
        notify(*msg)
        print(f"[resumen] {msg[1]}")
    _save(last_sent=date.today().isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
