"""Tests del instalador/actualizador OTA.

El flujo completo (install.sh → update → manipulación → rollback) se ejecuta de verdad
en un HOME temporal. En Linux, launchd se simula; el resto es el código real.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

import ed25519
import jobtracker as jt

REPO = Path(__file__).resolve().parents[2]
SEED = bytes.fromhex("11" * 32)
PUB = ed25519.public_key(SEED)


# ── Unitarios ───────────────────────────────────────────────────


def test_rfc8032_vector():
    sk = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    pk = ed25519.public_key(sk)
    assert pk.hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    sig = ed25519.sign(sk, b"")
    assert sig.hex().startswith("e5564300c360ac729086e2cc806e828a")
    assert ed25519.verify(pk, b"", sig)
    assert not ed25519.verify(pk, b"x", sig)


def test_interop_with_cryptography():
    crypto = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    key = crypto.Ed25519PrivateKey.from_private_bytes(SEED)
    msg = b"jobtracker"
    assert ed25519.verify(PUB, msg, key.sign(msg))
    key.public_key().verify(ed25519.sign(SEED, msg), msg)  # lanza si no es válida


@pytest.mark.parametrize("a,b", [("0.2.0", "0.10.0"), ("1.9.9", "2.0.0"), ("v1.0.0", "1.0.1")])
def test_version_order(a, b):
    assert jt.parse_version(a) < jt.parse_version(b)


def test_bad_version():
    with pytest.raises(jt.OTAError):
        jt.parse_version("1.0")


def _signed(manifest):
    return {**manifest, "signature": ed25519.sign(SEED, jt.canonical_manifest(manifest)).hex()}


def test_manifest_signature_and_tampering():
    m = _signed({"version": "1.0.0", "url": "x.tgz", "sha256": "ab", "size": 1})
    jt.verify_manifest({**m, "_resolved_url": "http://local"}, PUB)  # campos locales no cuentan
    with pytest.raises(jt.OTAError, match="INVÁLIDA"):
        jt.verify_manifest({**m, "sha256": "cd"}, PUB)
    with pytest.raises(jt.OTAError, match="no está firmado"):
        jt.verify_manifest({k: v for k, v in m.items() if k != "signature"}, PUB)


def test_safe_extract_rejects_traversal(tmp_path):
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        data = b"pwned"
        info = tarfile.TarInfo("root/../../evil.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    with pytest.raises(jt.OTAError, match="peligrosa"):
        jt.safe_extract(bad, tmp_path / "out")


def test_safe_extract_rejects_symlinks(tmp_path):
    bad = tmp_path / "link.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        info = tarfile.TarInfo("root/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    with pytest.raises(jt.OTAError, match="no permitido"):
        jt.safe_extract(bad, tmp_path / "out")


def test_launchd_plists():
    paths = jt.Paths(Path("/Users/x/Library/Application Support/JobTrackerAI"))
    services = jt.Services(paths, {"python": "/py"})
    agent = services.plist("agent")
    assert agent["ProgramArguments"][-2:] == ["run", "agent"]
    assert agent["StartInterval"] == 3 * 3600 and agent["RunAtLoad"] is False and "KeepAlive" not in agent
    assert services.plist("updater")["RunAtLoad"] is True
    assert set(jt.Services.SCHEDULED) == {"updater", "agent"}


# ── Extremo a extremo ──────────────────────────────────────────


def make_release(tmp: Path, version: str, *, break_backend: bool = False) -> Path:
    """Copia el repo, cambia VERSION (y opcionalmente rompe el backend) y genera la release."""
    src = tmp / f"src-{version}"
    files = subprocess.check_output(["git", "ls-files"], cwd=REPO, text=True).split()
    for f in files:
        if (REPO / f).is_file():
            (src / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / f, src / f)
    (src / "VERSION").write_text(version + "\n")
    (src / "installer" / "ota_pubkey.txt").write_text("# test\n" + PUB.hex() + "\n")
    if break_backend:
        (src / "backend" / "app" / "main.py").write_text("raise RuntimeError('versión rota')\n")
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q"], cwd=src, check=True)
    subprocess.run([*git, "add", "-A"], cwd=src, check=True)
    out = tmp / f"dist-{version}"
    subprocess.run([sys.executable, str(src / "scripts" / "release.py"), "--root", str(src), "--out", str(out)],
                   check=True, env={**os.environ, "OTA_SIGNING_KEY": SEED.hex()}, capture_output=True)
    return out


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    return {
        **os.environ,
        "HOME": str(home),
        "JOBTRACKER_HOME": str(home / "app"),
        "JOBTRACKER_ALLOW_NON_MAC": "1",
        "JOBTRACKER_PYTHON": sys.executable,
        "JOBTRACKER_VENV_PYTHON": sys.executable,  # reutiliza el entorno de tests (sin pip install)
        "JOBTRACKER_NO_START": "1",
    }


def ctl(env, *args, check=True):
    shim = Path(env["HOME"]) / ".local" / "bin" / "jobtracker"
    r = subprocess.run([str(shim), *args], env=env, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(r.stdout + r.stderr)
    return r


def state(env):
    return json.loads((Path(env["JOBTRACKER_HOME"]) / "state.json").read_text())


def test_install_update_tamper_rollback(tmp_path, env):
    v1, v2 = make_release(tmp_path, "0.2.0"), make_release(tmp_path, "0.3.0")
    app_home = Path(env["JOBTRACKER_HOME"])

    # 1) Instalación con install.sh (igual que el .pkg, desde ficheros locales)
    r = subprocess.run(["bash", str(REPO / "installer" / "install.sh"), "--non-interactive",
                        "--tarball", str(v1 / "jobtracker-ai-0.2.0.tar.gz"), "--manifest", str(v1 / "manifest.json")],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert state(env)["current"] == "0.2.0"
    assert (app_home / "current").resolve().name == "0.2.0"
    app = Path(env["HOME"]) / "Applications" / "JobTracker AI.app"
    assert (app / "Contents" / "Resources" / "AppIcon.icns").exists()
    assert oct((app_home / ".env").stat().st_mode)[-3:] == "600"
    (app_home / "data" / "keep.txt").write_text("datos del usuario")

    # 2) Sin novedades
    env["JOBTRACKER_MANIFEST_URL"] = (v1 / "manifest.json").as_uri()
    assert "al día" in ctl(env, "check").stdout

    # 3) OTA a 0.3.0
    env["JOBTRACKER_MANIFEST_URL"] = (v2 / "manifest.json").as_uri()
    assert "0.3.0" in ctl(env, "check").stdout
    ctl(env, "update")
    s = state(env)
    assert (s["current"], s["previous"]) == ("0.3.0", "0.2.0")
    assert (app_home / "current").resolve().name == "0.3.0"
    assert (app_home / "data" / "keep.txt").read_text() == "datos del usuario"
    assert "0.3.0" in ctl(env, "version").stdout
    # El CLI encuentra la instalación aunque JOBTRACKER_HOME no esté en el entorno
    bare = {k: v for k, v in env.items() if k != "JOBTRACKER_HOME"}
    assert "0.3.0" in ctl(bare, "version").stdout

    # 4) Release manipulada (paquete distinto con firma vieja) → rechazada
    evil = make_release(tmp_path, "0.4.0")
    m = json.loads((evil / "manifest.json").read_text())
    m["url"] = "http://attacker.invalid/x.tgz"
    (evil / "manifest.json").write_text(json.dumps(m))
    env["JOBTRACKER_MANIFEST_URL"] = (evil / "manifest.json").as_uri()
    r = ctl(env, "update", check=False)
    assert r.returncode == 1 and "INVÁLIDA" in r.stderr
    assert state(env)["current"] == "0.3.0"

    # 5) Release firmada pero que no arranca → el health check la frena
    broken = make_release(tmp_path, "0.5.0", break_backend=True)
    env["JOBTRACKER_MANIFEST_URL"] = (broken / "manifest.json").as_uri()
    r = ctl(env, "update", check=False)
    assert r.returncode == 1 and "no arranca" in r.stderr
    assert state(env)["current"] == "0.3.0"
    assert not (app_home / "versions" / "0.5.0").exists()

    # 6) Downgrade: un manifiesto antiguo (aunque esté firmado) no se instala
    env["JOBTRACKER_MANIFEST_URL"] = (v1 / "manifest.json").as_uri()
    assert "al día" in ctl(env, "check").stdout

    # 7) Rollback manual
    ctl(env, "rollback")
    assert state(env)["current"] == "0.2.0"
    assert (app_home / "current").resolve().name == "0.2.0"

    # 8) Desinstalar conservando datos
    ctl(env, "uninstall", "--keep-data")
    assert (app_home / "data" / "keep.txt").exists()
    assert not (app_home / "versions").exists()
    assert not app.exists()


def test_shell_scripts_safe_for_macos_bash32():
    """El bash 3.2 de macOS (sin locale UTF-8) toma el primer byte de «…», «→», etc. como
    parte del nombre de la variable: "$VAR…" falla con «unbound variable». Usa "${VAR}…"."""
    import re

    pattern = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7F]")
    scripts = [REPO / "installer" / "install.sh", *(REPO / "installer" / "pkg").glob("*.sh"),
               REPO / "installer" / "pkg" / "postinstall", REPO / "scripts" / "setup_mac.sh"]
    bad = [f"{s.name}:{i}: {line.strip()}" for s in scripts
           for i, line in enumerate(s.read_text().splitlines(), 1) if pattern.search(line)]
    assert not bad, "Variables pegadas a caracteres no ASCII:\n" + "\n".join(bad)
