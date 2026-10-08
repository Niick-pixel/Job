"""Ejecuta una pasada del agente de búsqueda.

    python -m app.agent            (lo lanza launchd cada pocas horas en la instalación de Mac)

Un candado de fichero impide dos ejecuciones simultáneas (programada + botón «Buscar ahora»).
"""
import fcntl
import sys
from contextlib import contextmanager

from sqlmodel import Session

from .config import DATA_DIR, get_settings
from .database import engine, init_db
from .models import AgentRun
from .services.agent import run_agent
from .services.email_sources import fetch_emails
from .services.llm import get_llm
from .services.packages import prepare_package


class AgentBusy(RuntimeError):
    pass


@contextmanager
def agent_lock():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / "agent.lock", "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AgentBusy("El agente ya se está ejecutando") from None
        yield


def run_once(trigger: str = "schedule", llm=None) -> AgentRun:
    settings = get_settings()
    with agent_lock(), Session(engine) as db:
        return run_agent(
            db, llm or get_llm(), settings, trigger=trigger,
            email_loader=lambda: fetch_emails(settings, interactive=False), prepare=prepare_package,
        )


def main() -> int:
    init_db()
    try:
        run = run_once("schedule")
    except AgentBusy as e:
        print(e)
        return 0
    print(f"[agente] {run.status} {run.stats} {run.error or ''}")
    return 0 if run.status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
