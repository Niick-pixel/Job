"""Motor SQLite/PostgreSQL vía SQLModel."""
from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

settings = get_settings()
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args)


def init_db() -> None:
    if settings.database_url.startswith("sqlite:///"):
        from pathlib import Path

        Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    from . import models  # noqa: F401  (registra las tablas)

    SQLModel.metadata.create_all(engine)
    add_missing_columns()
    _close_stale_runs()


def _close_stale_runs() -> None:
    """Ejecuciones del agente que quedaron «running» por un cierre inesperado.
    Solo si nadie tiene el candado del agente (si no, hay una ejecución real en curso)."""
    from sqlalchemy import text

    from .agent import AgentBusy, agent_lock

    try:
        with agent_lock(), engine.begin() as conn:
            conn.execute(text("UPDATE agentrun SET status='error', error='interrumpida' WHERE status='running'"))
    except AgentBusy:
        pass


def add_missing_columns(engine=engine) -> None:
    """Migración mínima para actualizaciones OTA: create_all() crea tablas nuevas pero no
    añade columnas a las existentes. Añade las que falten (siempre como anulables/por defecto)."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                default = ""
                if column.default is not None and getattr(column.default, "is_scalar", False):
                    value = column.default.arg
                    value = value.value if hasattr(value, "value") else value
                    default = f" DEFAULT '{value}'" if isinstance(value, str) else f" DEFAULT {value}"
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}{default}'))


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
