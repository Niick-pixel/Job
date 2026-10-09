"""Lectura/escritura segura del fichero .env donde viven las claves API.

- En la app instalada: ~/Library/Application Support/JobTrackerAI/.env (fuera del código,
  sobrevive a las actualizaciones). En desarrollo: el .env del repositorio.
- Escritura atómica, permisos 600 y conservando comentarios y orden.
- Los cambios se aplican en caliente: se limpia la caché de Settings y del cliente de IA.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from ..config import JOBTRACKER_HOME, ROOT_DIR, get_settings

NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def env_path() -> Path:
    return (JOBTRACKER_HOME / ".env") if JOBTRACKER_HOME else (ROOT_DIR / ".env")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value.split(" #", 1)[0].strip()


def read_env(path: Path | None = None) -> dict[str, str]:
    path = path or env_path()
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if m:
            values[m.group(1)] = _unquote(m.group(2))
    return values


def _quote(value: str) -> str:
    if re.search(r"[\s#'\"\\]", value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def write_env(updates: dict[str, str | None], path: Path | None = None) -> None:
    """Aplica cambios (None = borrar la clave) conservando el resto del fichero."""
    path = path or env_path()
    for name, value in updates.items():
        if not NAME_RE.match(name):
            raise ValueError(f"Nombre de variable inválido: {name}")
        if value is not None and ("\n" in value or "\r" in value):
            raise ValueError("El valor no puede contener saltos de línea")

    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else [
        "# Configuración de JobTracker AI (se conserva entre actualizaciones)"]
    pending = dict(updates)
    out = []
    for line in lines:
        m = _LINE_RE.match(line) if not line.lstrip().startswith("#") else None
        if m and m.group(1) in pending:
            value = pending.pop(m.group(1))
            if value is not None:
                out.append(f"{m.group(1)}={_quote(value)}")
            continue
        out.append(line)
    out += [f"{k}={_quote(v)}" for k, v in pending.items() if v is not None]

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise

    # Aplicar en caliente (las variables de entorno del proceso tienen prioridad sobre el .env)
    for name, value in updates.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    reload_runtime()


def reload_runtime() -> None:
    from . import llm

    get_settings.cache_clear()
    llm._llm = None


def mask(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:6]}…{value[-4:]}"


# ── Llavero de macOS ───────────────────────────────────────────


def keychain_names(values: dict[str, str] | None = None) -> list[str]:
    from .. import keychain

    return keychain.index_from(values if values is not None else read_env())


def _set_index(names: list[str]) -> dict[str, str | None]:
    return {"KEYCHAIN_KEYS": ",".join(sorted(set(names))) or None}


def store_secret(name: str, value: str) -> str:
    """Guarda una clave: en el Llavero si se puede (y la quita del .env); si no, en el .env.
    Devuelve dónde quedó: «llavero» o «env»."""
    from .. import keychain

    if keychain.available() and keychain.backend.set(name, value):
        write_env({name: None, **_set_index(keychain_names() + [name])})
        os.environ[name] = value
        reload_runtime()
        return "llavero"
    write_env({name: value})
    return "env"


def delete_secret(name: str) -> None:
    from .. import keychain

    names = keychain_names()
    if name in names:
        if keychain.available():
            keychain.backend.delete(name)
        write_env({name: None, **_set_index([n for n in names if n != name])})
    else:
        write_env({name: None})


def migrate_to_keychain(secret_names: set[str]) -> list[str]:
    """Pasa al Llavero las claves que aún estén en texto plano en el .env (al arrancar la app)."""
    from .. import keychain

    if not keychain.available():
        return []
    env = read_env()
    moved = []
    for name, value in env.items():
        if name in secret_names and value and keychain.backend.set(name, value):
            moved.append(name)
    if moved:
        write_env({**{n: None for n in moved}, **_set_index(keychain_names(env) + moved)})
        for n in moved:  # write_env(None) las quitó del entorno del proceso: se reponen
            os.environ[n] = env[n]
        reload_runtime()
    return moved
