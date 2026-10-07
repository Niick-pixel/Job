#!/usr/bin/env python3
"""JobTracker AI · gestor de instalación, servicios y actualizaciones OTA para macOS.

Solo usa la biblioteca estándar: debe funcionar aunque el entorno virtual de la
app esté roto (precisamente para poder repararlo con una actualización).

Estructura en disco (por defecto ~/Library/Application Support/JobTrackerAI):

    versions/<x.y.z>/      código de cada versión instalada (se guardan 2)
    venvs/<hash>/          entornos virtuales, compartidos si requirements.txt no cambia
    current -> versions/…  enlace simbólico a la versión activa (se cambia de forma atómica)
    data/                  base de datos, CVs, tokens de Gmail (nunca se toca al actualizar)
    logs/  .env  state.json

Flujo de una actualización:
    manifest.json firmado → comprobar versión > actual → descargar tarball → verificar
    SHA-256 + firma Ed25519 → extraer → preparar venv → health check en puerto aislado →
    cambiar `current` → reiniciar servicios → si /health falla, rollback automático.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import getpass
import hashlib
import json
import os
import plistlib
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ed25519  # noqa: E402

APP_NAME = "JobTracker AI"
LABEL_PREFIX = "com.jobtrackerai"
DEFAULT_MANIFEST_URL = "https://github.com/Niick-pixel/Job/releases/latest/download/manifest.json"
BACKEND_PORT = 8000
FRONTEND_PORT = 8501
CHECK_INTERVAL_SECONDS = 6 * 3600
KEEP_VERSIONS = 2
IS_MAC = sys.platform == "darwin"

CODE_DIR = Path(__file__).resolve().parent.parent  # raíz de la versión que ejecuta este script


class OTAError(RuntimeError):
    pass


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ── Rutas y estado ──────────────────────────────────────────────


def default_home() -> Path:
    if os.getenv("JOBTRACKER_HOME"):
        return Path(os.environ["JOBTRACKER_HOME"]).expanduser()
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "JobTrackerAI"
    return Path.home() / ".local" / "share" / "jobtracker-ai"


@dataclass(frozen=True)
class Paths:
    home: Path

    @property
    def versions(self) -> Path: return self.home / "versions"
    @property
    def venvs(self) -> Path: return self.home / "venvs"
    @property
    def current(self) -> Path: return self.home / "current"
    @property
    def data(self) -> Path: return self.home / "data"
    @property
    def logs(self) -> Path: return self.home / "logs"
    @property
    def downloads(self) -> Path: return self.home / "downloads"
    @property
    def state_file(self) -> Path: return self.home / "state.json"
    @property
    def env_file(self) -> Path: return self.home / ".env"
    @property
    def force_flag(self) -> Path: return self.home / "force_update"
    @property
    def ctl(self) -> Path: return self.current / "installer" / "jobtracker.py"

    def ensure(self) -> None:
        for d in (self.home, self.versions, self.venvs, self.data, self.logs, self.downloads):
            d.mkdir(parents=True, exist_ok=True)


def load_state(paths: Paths) -> dict:
    try:
        return json.loads(paths.state_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(paths: Paths, state: dict) -> None:
    tmp = paths.state_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    os.replace(tmp, paths.state_file)


def manifest_url(state: dict) -> str:
    return os.getenv("JOBTRACKER_MANIFEST_URL") or state.get("manifest_url") or DEFAULT_MANIFEST_URL


@contextlib.contextmanager
def update_lock(paths: Paths):
    paths.home.mkdir(parents=True, exist_ok=True)
    with open(paths.home / ".lock", "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise OTAError("Ya hay otra instalación/actualización en curso") from None
        yield


# ── Versiones, red y verificación ──────────────────────────────


def parse_version(v: str) -> tuple[int, int, int]:
    parts = v.strip().lstrip("v").split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise OTAError(f"Versión inválida: {v!r} (se espera X.Y.Z)")
    return tuple(int(p) for p in parts)  # type: ignore[return-value]


def read_version(code_dir: Path) -> str:
    return (code_dir / "VERSION").read_text().strip()


def download(url: str, dest: Path, timeout: int = 120) -> None:
    """Descarga con curl si está disponible (usa el llavero del sistema en macOS)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    if url.startswith(("http://", "https://")) and shutil.which("curl"):
        r = subprocess.run(
            ["curl", "-fsSL", "--retry", "3", "--max-time", str(timeout), "-o", str(tmp), url],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise OTAError(f"No se pudo descargar {url}: {r.stderr.strip()}")
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "JobTrackerAI-Updater"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as fh:
                shutil.copyfileobj(resp, fh)
        except OSError as e:
            raise OTAError(f"No se pudo descargar {url}: {e}") from e
    os.replace(tmp, dest)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_manifest(manifest: dict) -> bytes:
    """Bytes firmados: el manifiesto sin la firma, con claves ordenadas y sin espacios."""
    body = {k: v for k, v in manifest.items() if k != "signature" and not k.startswith("_")}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def load_pubkey(code_dir: Path) -> bytes | None:
    """Clave pública fijada en la versión instalada. None = firma aún no configurada."""
    try:
        raw = (code_dir / "installer" / "ota_pubkey.txt").read_text()
    except FileNotFoundError:
        return None
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.startswith("#")]
    return bytes.fromhex(lines[0]) if lines else None


def verify_manifest(manifest: dict, pubkey: bytes | None) -> None:
    for key in ("version", "url", "sha256", "size"):
        if key not in manifest:
            raise OTAError(f"Manifiesto incompleto: falta '{key}'")
    parse_version(manifest["version"])
    if pubkey is None:
        log("⚠️  Firma OTA no configurada (installer/ota_pubkey.txt): solo se verifica SHA-256 + HTTPS")
        return
    sig = manifest.get("signature")
    if not sig:
        raise OTAError("El manifiesto no está firmado y esta instalación exige firma")
    try:
        sig_bytes = bytes.fromhex(sig)
    except ValueError:
        raise OTAError("Firma con formato inválido") from None
    if not ed25519.verify(pubkey, canonical_manifest(manifest), sig_bytes):
        raise OTAError("Firma del manifiesto INVÁLIDA: actualización rechazada")


def fetch_manifest(url: str, workdir: Path) -> dict:
    path = workdir / "manifest.json"
    download(url, path, timeout=30)
    try:
        manifest = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise OTAError(f"Manifiesto corrupto: {e}") from e
    # URL relativa → relativa al propio manifiesto
    manifest["_resolved_url"] = urllib.parse.urljoin(url, manifest.get("url", ""))
    return manifest


def download_release(manifest: dict, dest_dir: Path) -> Path:
    url = manifest.get("_resolved_url") or manifest["url"]
    tar_path = dest_dir / f"jobtracker-ai-{manifest['version']}.tar.gz"
    download(url, tar_path, timeout=600)
    check_tarball(manifest, tar_path)
    return tar_path


def check_tarball(manifest: dict, tar_path: Path) -> None:
    if tar_path.stat().st_size != manifest["size"]:
        raise OTAError("Tamaño del paquete distinto al del manifiesto")
    if sha256_file(tar_path) != manifest["sha256"]:
        raise OTAError("SHA-256 del paquete no coincide: descarga corrupta o manipulada")


def safe_extract(tar_path: Path, dest: Path) -> None:
    """Extrae el tarball quitando el directorio raíz y rechazando rutas peligrosas."""
    dest.mkdir(parents=True)
    with tarfile.open(tar_path, "r:gz") as tar:
        members = []
        for m in tar.getmembers():
            parts = Path(m.name).parts
            if len(parts) <= 1:
                continue  # el directorio raíz jobtracker-ai-x.y.z/
            rel = Path(*parts[1:])
            if rel.is_absolute() or ".." in rel.parts:
                raise OTAError(f"Ruta peligrosa en el paquete: {m.name}")
            if not (m.isfile() or m.isdir()):
                raise OTAError(f"Tipo de entrada no permitido en el paquete: {m.name}")
            m.name = str(rel)
            members.append(m)
        kwargs = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tar.extractall(dest, members=members, **kwargs)


# ── Entornos virtuales ─────────────────────────────────────────


def python_version(python: str) -> str:
    return subprocess.check_output([python, "-c", "import sys; print(sys.version.split()[0])"], text=True).strip()


def venv_key(code_dir: Path, python: str) -> str:
    h = hashlib.sha256((code_dir / "requirements.txt").read_bytes())
    h.update(python_version(python).encode())
    return h.hexdigest()[:16]


def ensure_venv(paths: Paths, state: dict, code_dir: Path) -> str:
    """Devuelve el python del venv para esta versión, creándolo solo si cambian las dependencias."""
    if os.getenv("JOBTRACKER_VENV_PYTHON"):  # entornos de prueba / desarrollo
        return os.environ["JOBTRACKER_VENV_PYTHON"]
    base = state["python"]
    venv = paths.venvs / venv_key(code_dir, base)
    py = venv / "bin" / "python"
    if (venv / ".complete").exists() and py.exists():
        return str(py)

    shutil.rmtree(venv, ignore_errors=True)
    log(f"Creando entorno virtual ({venv.name}); la primera vez tarda 1-2 minutos…")
    uv = state.get("uv")
    req = str(code_dir / "requirements.txt")
    try:
        if uv and Path(uv).exists():
            subprocess.run([uv, "venv", "--quiet", "--python", base, str(venv)], check=True)
            subprocess.run([uv, "pip", "install", "--quiet", "--python", str(py), "-r", req], check=True)
        else:
            subprocess.run([base, "-m", "venv", str(venv)], check=True)
            subprocess.run([str(py), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=True)
            subprocess.run([str(py), "-m", "pip", "install", "--quiet", "-r", req], check=True)
    except subprocess.CalledProcessError as e:
        shutil.rmtree(venv, ignore_errors=True)
        raise OTAError(f"Fallo instalando dependencias: {e}") from e
    (venv / ".complete").write_text(datetime.now(timezone.utc).isoformat())
    return str(py)


# ── Health checks ──────────────────────────────────────────────


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


def wait_http(url: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if http_ok(url):
            return True
        time.sleep(0.5)
    return False


def health_check(code_dir: Path, venv_python: str, timeout: float = 60) -> None:
    """Arranca el backend de la versión candidata en un puerto y BD temporales."""
    with tempfile.TemporaryDirectory(prefix="jt-health-") as tmp:
        env = {**os.environ, "JOBTRACKER_DATA_DIR": tmp, "PYTHONDONTWRITEBYTECODE": "1"}
        env.pop("JOBTRACKER_HOME", None)  # no leer el .env real durante la prueba
        port = free_port()
        proc = subprocess.Popen(
            [venv_python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=code_dir / "backend", env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            ok = False
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and proc.poll() is None:
                if http_ok(f"http://127.0.0.1:{port}/health"):
                    ok = True
                    break
                time.sleep(0.4)
            if not ok:
                proc.kill()
                out = proc.communicate(timeout=10)[0] or ""
                raise OTAError("La nueva versión no arranca (health check):\n" + out[-2000:])
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()


# ── Servicios (launchd en macOS) ───────────────────────────────


def service_env(paths: Paths) -> dict[str, str]:
    return {
        "JOBTRACKER_HOME": str(paths.home),
        "JOBTRACKER_DATA_DIR": str(paths.data),
        "BACKEND_URL": f"http://127.0.0.1:{BACKEND_PORT}",
        "PYTHONUNBUFFERED": "1",
        "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    }


class Services:
    NAMES = ("backend", "frontend", "updater")

    def __init__(self, paths: Paths, state: dict):
        self.paths, self.state = paths, state
        self.agents_dir = Path.home() / "Library" / "LaunchAgents"
        self.domain = f"gui/{os.getuid()}"

    def label(self, name: str) -> str:
        return f"{LABEL_PREFIX}.{name}"

    def plist_path(self, name: str) -> Path:
        return self.agents_dir / f"{self.label(name)}.plist"

    def _launchctl(self, *args: str, check: bool = False) -> subprocess.CompletedProcess:
        if not IS_MAC:
            log(f"(simulado) launchctl {' '.join(args)}")
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=check)

    def plist(self, name: str) -> dict:
        # Los plists no cambian entre versiones: apuntan a `current/` y a `run`,
        # que resuelve en tiempo de arranque qué venv y qué código usar.
        args = [self.state["python"], str(self.paths.ctl)]
        common = {
            "Label": self.label(name),
            "EnvironmentVariables": service_env(self.paths),
            "StandardOutPath": str(self.paths.logs / f"{name}.log"),
            "StandardErrorPath": str(self.paths.logs / f"{name}.log"),
            "ProcessType": "Background" if name == "updater" else "Interactive",
        }
        if name == "updater":
            return {**common, "ProgramArguments": [*args, "auto-update"],
                    "StartInterval": CHECK_INTERVAL_SECONDS, "RunAtLoad": True}
        return {**common, "ProgramArguments": [*args, "run", name],
                "RunAtLoad": bool(self.state.get("start_at_login", False)),
                "KeepAlive": {"SuccessfulExit": False}, "ThrottleInterval": 5}

    def write_plists(self) -> None:
        if not IS_MAC and not os.getenv("JOBTRACKER_WRITE_PLISTS"):
            return
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        for name in self.NAMES:
            with open(self.plist_path(name), "wb") as fh:
                plistlib.dump(self.plist(name), fh)

    def is_loaded(self, name: str) -> bool:
        if not IS_MAC:
            return False
        return self._launchctl("print", f"{self.domain}/{self.label(name)}").returncode == 0

    def load(self, name: str) -> None:
        if not self.is_loaded(name):
            self._launchctl("bootstrap", self.domain, str(self.plist_path(name)))

    def unload(self, name: str) -> None:
        if self.is_loaded(name):
            self._launchctl("bootout", f"{self.domain}/{self.label(name)}")

    def start(self) -> None:
        for name in ("backend", "frontend"):
            self.load(name)
            self._launchctl("kickstart", f"{self.domain}/{self.label(name)}")
        self.load("updater")

    def stop(self) -> None:
        for name in ("backend", "frontend"):
            self.unload(name)

    def running(self) -> bool:
        return http_ok(f"http://127.0.0.1:{BACKEND_PORT}/health")

    def restart(self) -> None:
        for name in ("backend", "frontend"):
            if self.is_loaded(name):
                self._launchctl("kickstart", "-k", f"{self.domain}/{self.label(name)}")

    def reload_all(self) -> None:
        """Recarga los agentes para que launchd lea plists reescritos."""
        for name in self.NAMES:
            was = self.is_loaded(name)
            self.unload(name)
            if was or name == "updater":
                self.load(name)
                if name != "updater":
                    self._launchctl("kickstart", f"{self.domain}/{self.label(name)}")


def notify(title: str, message: str) -> None:
    if IS_MAC:
        script = f'display notification {json.dumps(message)} with title {json.dumps(title)}'
        subprocess.run(["osascript", "-e", script], capture_output=True)


# ── Integración con el sistema: .app, CLI ──────────────────────


def apps_dir() -> Path:
    return Path(os.getenv("JOBTRACKER_APPS_DIR", Path.home() / "Applications"))


def bin_dir() -> Path:
    return Path(os.getenv("JOBTRACKER_BIN_DIR", Path.home() / ".local" / "bin"))


def write_app_bundle(paths: Paths, state: dict, version: str) -> Path:
    app = apps_dir() / f"{APP_NAME}.app"
    macos = app / "Contents" / "MacOS"
    resources = app / "Contents" / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    launcher = macos / "JobTrackerAI"
    launcher.write_text(
        "#!/bin/bash\n"
        "# Generado por el instalador de JobTracker AI\n"
        f'export JOBTRACKER_HOME="{paths.home}"\n'
        f'exec "{state["python"]}" "{paths.ctl}" open\n'
    )
    launcher.chmod(0o755)
    info = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": f"{LABEL_PREFIX}.launcher",
        "CFBundleExecutable": "JobTrackerAI",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSMinimumSystemVersion": "11.0",
        "LSUIElement": True,
    }
    icon = CODE_DIR / "installer" / "assets" / "AppIcon.icns"
    if icon.exists():
        shutil.copy2(icon, resources / "AppIcon.icns")
        info["CFBundleIconFile"] = "AppIcon"
    with open(app / "Contents" / "Info.plist", "wb") as fh:
        plistlib.dump(info, fh)
    return app


def write_cli_shim(paths: Paths, state: dict) -> Path:
    bdir = bin_dir()
    bdir.mkdir(parents=True, exist_ok=True)
    shim = bdir / "jobtracker"
    shim.write_text(f'#!/bin/bash\nexport JOBTRACKER_HOME="{paths.home}"\nexec "{state["python"]}" "{paths.ctl}" "$@"\n')
    shim.chmod(0o755)
    return shim


# ── Operaciones principales ────────────────────────────────────


def switch_current(paths: Paths, version: str) -> None:
    """Cambia el enlace `current` de forma atómica (rename sobre el enlace existente)."""
    tmp = paths.home / f".current-{os.getpid()}"
    with contextlib.suppress(FileNotFoundError):
        tmp.unlink()
    tmp.symlink_to(Path("versions") / version)
    os.replace(tmp, paths.current)


def stage_version(paths: Paths, state: dict, manifest: dict, tar_path: Path) -> tuple[Path, str]:
    version = manifest["version"]
    dest = paths.versions / version
    if not (dest / ".complete").exists():
        shutil.rmtree(dest, ignore_errors=True)
        staging = paths.versions / f".staging-{version}"
        shutil.rmtree(staging, ignore_errors=True)
        safe_extract(tar_path, staging)
        if read_version(staging) != version:
            shutil.rmtree(staging, ignore_errors=True)
            raise OTAError("El VERSION del paquete no coincide con el manifiesto")
        os.replace(staging, dest)
    try:
        venv_python = ensure_venv(paths, state, dest)
        log("Probando la nueva versión…")
        health_check(dest, venv_python)
    except OTAError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    (dest / ".complete").write_text(datetime.now(timezone.utc).isoformat())
    return dest, venv_python


def refresh_system(paths: Paths, state: dict) -> None:
    """Regenera .app, CLI y LaunchAgents. Se ejecuta con el código de la versión NUEVA."""
    version = read_version(CODE_DIR)
    write_app_bundle(paths, state, version)
    write_cli_shim(paths, state)
    Services(paths, state).write_plists()


def apply_release(paths: Paths, state: dict, manifest: dict, tar_path: Path) -> None:
    services = Services(paths, state)
    was_running = services.running()
    new_dir, _ = stage_version(paths, state, manifest, tar_path)
    previous = state.get("current")

    switch_current(paths, manifest["version"])
    state.update(previous=previous, current=manifest["version"],
                 installed_at=datetime.now(timezone.utc).isoformat(), available=None)
    save_state(paths, state)

    # Los ajustes del sistema los aplica el código nuevo (puede traer cambios en plists/.app)
    subprocess.run([state["python"], str(new_dir / "installer" / "jobtracker.py"), "refresh"], check=True)

    if was_running:
        services.restart()
        if not wait_http(f"http://127.0.0.1:{BACKEND_PORT}/health", 60):
            log("❌ La nueva versión no responde tras reiniciar: revirtiendo…")
            rollback(paths, state, reason="health check tras reinicio")
            raise OTAError("Actualización revertida automáticamente")
    gc_versions(paths, state)


def rollback(paths: Paths, state: dict, reason: str = "manual") -> str:
    prev = state.get("previous")
    if not prev or not (paths.versions / prev).exists():
        raise OTAError("No hay versión anterior disponible para revertir")
    bad = state.get("current")
    switch_current(paths, prev)
    state.update(current=prev, previous=bad, rolled_back_from=bad, rollback_reason=reason)
    save_state(paths, state)
    subprocess.run([state["python"], str(paths.versions / prev / "installer" / "jobtracker.py"), "refresh"],
                   check=False)
    Services(paths, state).restart()
    notify(APP_NAME, f"Se restauró la versión {prev}")
    return prev


def gc_versions(paths: Paths, state: dict) -> None:
    keep = {state.get("current"), state.get("previous")}
    for d in paths.versions.iterdir():
        if d.is_dir() and d.name not in keep:
            shutil.rmtree(d, ignore_errors=True)
    if os.getenv("JOBTRACKER_VENV_PYTHON"):
        return
    used = set()
    for v in keep:
        if v and (paths.versions / v).exists():
            with contextlib.suppress(Exception):
                used.add(venv_key(paths.versions / v, state["python"]))
    for d in paths.venvs.iterdir():
        if d.is_dir() and d.name not in used:
            shutil.rmtree(d, ignore_errors=True)
    for f in paths.downloads.iterdir():
        f.unlink(missing_ok=True) if f.is_file() else shutil.rmtree(f, ignore_errors=True)


def check_for_update(paths: Paths, state: dict) -> dict | None:
    """Devuelve el manifiesto verificado si hay una versión más nueva."""
    work = Path(tempfile.mkdtemp(dir=paths.downloads))
    try:
        manifest = fetch_manifest(manifest_url(state), work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    verify_manifest(manifest, load_pubkey(paths.current if paths.current.exists() else CODE_DIR))
    state["last_check"] = datetime.now(timezone.utc).isoformat()
    newer = parse_version(manifest["version"]) > parse_version(state["current"])
    state["available"] = {"version": manifest["version"], "notes": manifest.get("notes", "")} if newer else None
    save_state(paths, state)
    return manifest if newer else None


def do_update(paths: Paths, state: dict) -> bool:
    manifest = check_for_update(paths, state)
    if not manifest:
        log(f"Ya tienes la última versión ({state['current']})")
        return False
    log(f"Actualizando {state['current']} → {manifest['version']}")
    tar_path = download_release(manifest, paths.downloads)
    apply_release(paths, state, manifest, tar_path)
    log(f"✅ JobTracker AI actualizado a {manifest['version']}")
    notify(APP_NAME, f"Actualizado a la versión {manifest['version']}")
    return True


# ── Comandos CLI ───────────────────────────────────────────────


def require_installed(paths: Paths) -> dict:
    state = load_state(paths)
    if not state.get("current"):
        raise OTAError(f"JobTracker AI no está instalado en {paths.home}")
    return state


def cmd_install(args, paths: Paths) -> None:
    manifest = json.loads(Path(args.manifest).read_text())
    tar_path = Path(args.tarball)
    # Si ya hay una versión instalada, manda SU clave pública (confianza fijada)
    verify_manifest(manifest, load_pubkey(paths.current if paths.current.exists() else CODE_DIR))
    check_tarball(manifest, tar_path)

    with update_lock(paths):
        paths.ensure()
        state = load_state(paths)
        state.update(python=args.python, uv=args.uv or None)
        state.setdefault("auto_update", True)
        state.setdefault("start_at_login", False)
        if args.manifest_url:
            state["manifest_url"] = args.manifest_url

        if state.get("current") and parse_version(manifest["version"]) <= parse_version(state["current"]):
            log(f"Ya está instalada la versión {state['current']}; se regeneran los accesos.")
            refresh_system(paths, state)
            return

        if not paths.env_file.exists():
            paths.env_file.write_text(
                "# Configuración de JobTracker AI (se conserva entre actualizaciones)\n"
                "ANTHROPIC_API_KEY=\nLLM_MODEL=claude-opus-5-5\nLLM_EFFORT=medium\nEMAIL_MODE=simulated\n"
            )
            paths.env_file.chmod(0o600)

        save_state(paths, state)
        if state.get("current"):
            apply_release(paths, state, manifest, tar_path)
        else:
            stage_version(paths, state, manifest, tar_path)
            switch_current(paths, manifest["version"])
            state.update(current=manifest["version"], previous=None,
                         installed_at=datetime.now(timezone.utc).isoformat())
            save_state(paths, state)
            subprocess.run([args.python, str(paths.ctl), "refresh"], check=True)
            services = Services(paths, state)
            services.load("updater")
            if not args.no_start:
                services.start()
    log(f"✅ JobTracker AI {manifest['version']} instalado en {paths.home}")


def cmd_run(args, paths: Paths) -> None:
    state = require_installed(paths)
    code = paths.current.resolve()
    py = ensure_venv(paths, state, code)
    env = {**os.environ, **service_env(paths)}
    if args.service == "backend":
        os.chdir(code / "backend")
        argv = [py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(BACKEND_PORT)]
    else:
        os.chdir(code)
        argv = [py, "-m", "streamlit", "run", str(code / "frontend" / "streamlit_app.py"),
                "--server.port", str(FRONTEND_PORT), "--server.address", "127.0.0.1",
                "--server.headless", "true", "--browser.gatherUsageStats", "false"]
    os.execve(py, argv, env)


def cmd_open(_args, paths: Paths) -> None:
    state = require_installed(paths)
    services = Services(paths, state)
    if not http_ok(f"http://127.0.0.1:{FRONTEND_PORT}/_stcore/health"):
        services.start()
        if not wait_http(f"http://127.0.0.1:{FRONTEND_PORT}/_stcore/health", 90):
            notify(APP_NAME, "No se pudo arrancar. Revisa: jobtracker logs")
            raise OTAError("La interfaz no arrancó a tiempo")
    if "ANTHROPIC_API_KEY=sk-" not in paths.env_file.read_text():
        notify(APP_NAME, "Falta tu clave de Claude: ejecuta «jobtracker config api-key»")
    if IS_MAC:
        subprocess.run(["open", f"http://localhost:{FRONTEND_PORT}"])


def cmd_status(_args, paths: Paths) -> None:
    state = require_installed(paths)
    services = Services(paths, state)
    print(f"Versión:            {state['current']}  (anterior: {state.get('previous') or '—'})")
    print(f"Instalación:        {paths.home}")
    print(f"Backend:            {'🟢 activo' if services.running() else '⚪ parado'}")
    ui = http_ok(f"http://127.0.0.1:{FRONTEND_PORT}/_stcore/health")
    print(f"Interfaz:           {'🟢 http://localhost:%d' % FRONTEND_PORT if ui else '⚪ parada'}")
    print(f"Actualización auto: {'sí' if state.get('auto_update', True) else 'no'}")
    print(f"Última comprobación:{' ' + state['last_check'] if state.get('last_check') else ' nunca'}")
    if state.get("available"):
        print(f"⬆️  Disponible:       {state['available']['version']}  → jobtracker update")


def cmd_check(_args, paths: Paths) -> None:
    state = require_installed(paths)
    manifest = check_for_update(paths, state)
    if manifest:
        print(f"Nueva versión disponible: {manifest['version']}\n{manifest.get('notes', '')}")
    else:
        print(f"Estás al día ({state['current']})")


def cmd_update(_args, paths: Paths) -> None:
    with update_lock(paths):
        do_update(paths, require_installed(paths))


def cmd_auto_update(_args, paths: Paths) -> None:
    """Lo ejecuta launchd cada 6 h (y cuando la interfaz pide «Actualizar ahora»)."""
    state = require_installed(paths)
    forced = paths.force_flag.exists()
    paths.force_flag.unlink(missing_ok=True)
    try:
        with update_lock(paths):
            if forced or state.get("auto_update", True):
                do_update(paths, state)
            elif manifest := check_for_update(paths, state):
                notify(APP_NAME, f"Versión {manifest['version']} disponible: jobtracker update")
    except OTAError as e:
        log(f"Actualización automática fallida: {e}")
        if forced:
            notify(APP_NAME, f"No se pudo actualizar: {e}")


def cmd_rollback(_args, paths: Paths) -> None:
    with update_lock(paths):
        print(f"Restaurada la versión {rollback(paths, require_installed(paths))}")


def cmd_refresh(_args, paths: Paths) -> None:
    refresh_system(paths, require_installed(paths))


def cmd_start(_args, paths: Paths) -> None:
    Services(paths, require_installed(paths)).start()


def cmd_stop(_args, paths: Paths) -> None:
    Services(paths, require_installed(paths)).stop()


def cmd_restart(_args, paths: Paths) -> None:
    Services(paths, require_installed(paths)).restart()


def cmd_logs(args, paths: Paths) -> None:
    f = paths.logs / f"{args.service}.log"
    if not f.exists():
        raise OTAError(f"Aún no hay logs de {args.service}")
    lines = f.read_text(errors="replace").splitlines()[-args.lines:]
    print("\n".join(lines))


def cmd_config(args, paths: Paths) -> None:
    state = require_installed(paths)
    if args.key == "api-key":
        key = args.value or getpass.getpass("ANTHROPIC_API_KEY: ").strip()
        lines = [ln for ln in paths.env_file.read_text().splitlines() if not ln.startswith("ANTHROPIC_API_KEY=")]
        paths.env_file.write_text("\n".join([*lines, f"ANTHROPIC_API_KEY={key}"]) + "\n")
        paths.env_file.chmod(0o600)
        Services(paths, state).restart()
        print("Clave guardada y servicios reiniciados.")
        return
    if args.value not in ("on", "off"):
        raise OTAError("Usa: jobtracker config auto-update|start-at-login on|off")
    field = {"auto-update": "auto_update", "start-at-login": "start_at_login"}[args.key]
    state[field] = args.value == "on"
    save_state(paths, state)
    if field == "start_at_login":
        services = Services(paths, state)
        services.write_plists()
        services.reload_all()
    print(f"{args.key} = {args.value}")


def cmd_uninstall(args, paths: Paths) -> None:
    state = load_state(paths)
    services = Services(paths, state)
    for name in Services.NAMES:
        services.unload(name)
        services.plist_path(name).unlink(missing_ok=True)
    shutil.rmtree(apps_dir() / f"{APP_NAME}.app", ignore_errors=True)
    (bin_dir() / "jobtracker").unlink(missing_ok=True)
    if args.keep_data:
        for d in ("versions", "venvs", "downloads", "python", "tools"):
            shutil.rmtree(paths.home / d, ignore_errors=True)
        for f in ("current", "state.json", ".lock", "force_update"):
            (paths.home / f).unlink(missing_ok=True)
        print(f"Desinstalado. Tus datos siguen en {paths.data} y {paths.env_file}")
    else:
        shutil.rmtree(paths.home, ignore_errors=True)
        print("JobTracker AI desinstalado por completo.")


def cmd_version(_args, paths: Paths) -> None:
    print(load_state(paths).get("current") or read_version(CODE_DIR))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobtracker", description=f"{APP_NAME}: gestión y actualizaciones OTA")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("install", help="(lo usa install.sh) instala desde un paquete verificado")
    i.add_argument("--tarball", required=True)
    i.add_argument("--manifest", required=True)
    i.add_argument("--python", required=True)
    i.add_argument("--uv")
    i.add_argument("--manifest-url")
    i.add_argument("--no-start", action="store_true")
    i.set_defaults(func=cmd_install)

    r = sub.add_parser("run", help="(interno) ejecuta un servicio")
    r.add_argument("service", choices=["backend", "frontend"])
    r.set_defaults(func=cmd_run)

    for name, func, help_ in [
        ("open", cmd_open, "arranca la app y la abre en el navegador"),
        ("start", cmd_start, "arranca los servicios"),
        ("stop", cmd_stop, "para los servicios"),
        ("restart", cmd_restart, "reinicia los servicios"),
        ("status", cmd_status, "estado, versión y actualizaciones"),
        ("check", cmd_check, "comprueba si hay una versión nueva"),
        ("update", cmd_update, "descarga e instala la última versión"),
        ("auto-update", cmd_auto_update, "(interno) tarea periódica de launchd"),
        ("rollback", cmd_rollback, "vuelve a la versión anterior"),
        ("refresh", cmd_refresh, "(interno) regenera .app, CLI y LaunchAgents"),
        ("version", cmd_version, "muestra la versión instalada"),
    ]:
        sub.add_parser(name, help=help_).set_defaults(func=func)

    lg = sub.add_parser("logs", help="muestra los logs de un servicio")
    lg.add_argument("service", nargs="?", default="backend", choices=["backend", "frontend", "updater"])
    lg.add_argument("-n", "--lines", type=int, default=80)
    lg.set_defaults(func=cmd_logs)

    c = sub.add_parser("config", help="api-key | auto-update on/off | start-at-login on/off")
    c.add_argument("key", choices=["api-key", "auto-update", "start-at-login"])
    c.add_argument("value", nargs="?")
    c.set_defaults(func=cmd_config)

    u = sub.add_parser("uninstall", help="desinstala JobTracker AI")
    u.add_argument("--keep-data", action="store_true", help="conserva data/ y .env")
    u.set_defaults(func=cmd_uninstall)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args, Paths(default_home()))
    except OTAError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
