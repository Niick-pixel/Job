"""Claves API en el Llavero de macOS (en lugar de texto plano en el .env).

Se usa la herramienta `security` del sistema. Los valores se le pasan por la entrada estándar
(`security -i`), así nunca aparecen en la lista de procesos. Fuera de macOS (o con
JOBTRACKER_NO_KEYCHAIN=1) no hace nada y las claves siguen en el .env con permisos 600.

El .env guarda solo los NOMBRES de las claves que viven en el Llavero (KEYCHAIN_KEYS=…), para
saber cuáles cargar al arrancar cada proceso (app, agente, resumen diario…).
"""
from __future__ import annotations

import os
import subprocess
import sys

SERVICE = "JobTracker AI"
INDEX_VAR = "KEYCHAIN_KEYS"
SECURITY = "/usr/bin/security"


def available() -> bool:
    return sys.platform == "darwin" and os.path.exists(SECURITY) and os.getenv("JOBTRACKER_NO_KEYCHAIN") != "1"


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class MacKeychain:
    def get(self, name: str) -> str | None:
        r = subprocess.run([SECURITY, "find-generic-password", "-s", SERVICE, "-a", name, "-w"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.rstrip("\n") if r.returncode == 0 else None

    def set(self, name: str, value: str) -> bool:
        cmd = f"add-generic-password -U -s {_quote(SERVICE)} -a {_quote(name)} -w {_quote(value)}\n"
        r = subprocess.run([SECURITY, "-i"], input=cmd, capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and self.get(name) == value

    def delete(self, name: str) -> None:
        subprocess.run([SECURITY, "delete-generic-password", "-s", SERVICE, "-a", name],
                       capture_output=True, timeout=10)


backend: MacKeychain = MacKeychain()  # los tests lo sustituyen por uno en memoria


def index_from(values: dict[str, str]) -> list[str]:
    return [n for n in (values.get(INDEX_VAR) or "").split(",") if n.strip()]


def load_into_environ(env_values: dict[str, str]) -> list[str]:
    """Carga en os.environ las claves del Llavero (sin pisar variables ya definidas)."""
    if not available():
        return []
    loaded = []
    for name in index_from(env_values):
        # Si el .env trae un valor (p. ej. lo acaba de poner `jobtracker config api-key`), manda ese:
        # la app lo pasará al Llavero al arrancar.
        if os.environ.get(name) or env_values.get(name):
            continue
        value = backend.get(name)
        if value:
            os.environ[name] = value
            loaded.append(name)
    return loaded
