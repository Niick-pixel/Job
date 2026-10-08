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
from .services.digest import build_digest, digest_message
from .services.notify import notify

STATE = DATA_DIR / "digest.json"


def _last_sent() -> str | None:
    try:
        return json.loads(STATE.read_text()).get("last_sent")
    except (OSError, ValueError):
        return None


def should_send(now: datetime, hour: int, last_sent: str | None) -> bool:
    return now.hour >= hour and last_sent != now.date().isoformat()


def main(argv: list[str] | None = None) -> int:
    force = "--force" in (argv if argv is not None else sys.argv[1:])
    init_db()
    with Session(engine) as db:
        prefs = load_preferences(db)
        now = datetime.now()  # hora local del Mac
        if not force and (not prefs.digest_enabled or not should_send(now, prefs.digest_hour, _last_sent())):
            return 0
        msg = digest_message(build_digest(db))
    if msg:
        notify(*msg)
        print(f"[resumen] {msg[1]}")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"last_sent": date.today().isoformat()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
