"""Relleno de formularios de candidatura (Greenhouse, Lever, Ashby y genérico) con un navegador visible.

Principio: la app rellena y sube los documentos; **tú revisas y pulsas «Enviar»**. Nunca se envía nada
de forma automática. El proceso se ejecuta aparte (`python -m app.autofill <id>`) para que la ventana
del navegador siga abierta mientras revisas, e informa de su estado en data/autofill/<id>.json.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from ..config import DATA_DIR

FILL_JS = (Path(__file__).with_name("autofill_fill.js")).read_text(encoding="utf-8")
WORK = DATA_DIR / "autofill"
PROFILE_DIR = DATA_DIR / "browser-profile"
MAX_OPEN = 45 * 60  # cierra solo tras 45 min sin que cierres la ventana

MAC_BROWSERS = [Path("/Applications/Google Chrome.app"), Path("/Applications/Microsoft Edge.app"),
                Path.home() / "Applications" / "Google Chrome.app"]


# ── Datos que se rellenan ──────────────────────────────────────


def _link(links: list[str], needle: str) -> str | None:
    return next((u for u in links if needle in u.lower()), None)


def build_profile(cv: dict, package: dict, bank: list[dict]) -> dict:
    """cv: CVExtraction (dict) · package: answers y carta · bank: banco de respuestas {key, question, answer}."""
    name = (cv.get("full_name") or "").strip()
    first, _, last = name.partition(" ")
    links = cv.get("links") or []
    website = next((u for u in links if not re.search(r"linkedin|github", u, re.I)), None)
    answers = [a for a in (package.get("answers") or []) if a.get("answer")]
    by_key = {e["key"]: e["answer"] for e in bank if (e.get("answer") or "").strip()}
    by_key.update({a["key"]: a["answer"] for a in answers if a.get("key")})  # las adaptadas a la oferta mandan
    for e in bank:
        if (e.get("answer") or "").strip() and not any(a["question"] == e["question"] for a in answers):
            answers.append({"key": e["key"], "question": e["question"], "answer": e["answer"]})
    experience = cv.get("experience") or []
    return {
        "full_name": name or None, "first_name": first or None, "last_name": last or None,
        "email": cv.get("email"), "phone": cv.get("phone"), "location": cv.get("location"),
        "linkedin": _link(links, "linkedin") or by_key.get("linkedin"), "github": _link(links, "github"),
        "website": website,
        "current_company": (experience[0].get("company") if experience and isinstance(experience[0], dict) else None),
        "cover_letter": package.get("cover_letter") or None,
        "answers": answers, "answers_by_key": by_key,
    }


def form_url(url: str, source: str | None = None) -> str:
    """Lleva directamente al formulario cuando el portal lo tiene en otra página."""
    host, path = urlparse(url).netloc.lower(), urlparse(url).path.rstrip("/")
    if host == "jobs.lever.co" and not path.endswith("/apply") and path.count("/") >= 2:
        return url.split("?")[0].rstrip("/") + "/apply"
    if host == "jobs.ashbyhq.com" and not path.endswith("/application") and path.count("/") >= 2:
        return url.split("?")[0].rstrip("/") + "/application"
    return url


def browser_available() -> bool:
    if os.getenv("JOBTRACKER_BROWSER"):
        return Path(os.environ["JOBTRACKER_BROWSER"]).exists()
    if any(p.exists() for p in MAC_BROWSERS):
        return True
    cache = Path(os.getenv("PLAYWRIGHT_BROWSERS_PATH") or Path.home() / "Library" / "Caches" / "ms-playwright")
    return any(cache.glob("chromium-*")) if cache.exists() else False


# ── Estado (lo lee la app mientras el navegador está abierto) ──


def status_path(pkg_id: int) -> Path:
    return WORK / f"{pkg_id}.json"


def read_status(pkg_id: int) -> dict | None:
    try:
        st = json.loads(status_path(pkg_id).read_text())
    except (OSError, ValueError):
        return None
    st["alive"] = _alive(st.get("pid"))
    if st.get("state") in ("starting", "filling", "ready") and not st["alive"]:
        st["state"] = "closed"
    return st


def write_status(pkg_id: int, **data) -> dict:
    WORK.mkdir(parents=True, exist_ok=True)
    current = {}
    try:
        current = json.loads(status_path(pkg_id).read_text())
    except (OSError, ValueError):
        pass
    current.update(data, updated_at=datetime.now(timezone.utc).isoformat())
    tmp = status_path(pkg_id).with_suffix(".tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False))
    os.replace(tmp, status_path(pkg_id))
    return current


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # un proceso hijo terminado sigue «vivo» como zombi hasta que se recoge
        return os.waitpid(pid, os.WNOHANG) == (0, 0)
    except ChildProcessError:
        return True


# ── El proceso que maneja el navegador ─────────────────────────

SUBMIT_URL = re.compile(r"appl|submit|candida|postul", re.I)
APPLY_BUTTON = re.compile(r"^\s*(apply|apply (now|for this job)|aplicar|postular(me|se)?|inscribirme|enviar candidatura|solicitar)\b", re.I)

BANNER_JS = """(r) => {
  const d = document.createElement('div');
  d.id = 'jobtracker-banner';
  d.style.cssText = 'position:fixed;z-index:2147483647;left:50%;top:12px;transform:translateX(-50%);max-width:640px;' +
    'background:#111827;color:#fff;font:14px/1.45 -apple-system,system-ui,sans-serif;padding:12px 16px;border-radius:12px;' +
    'box-shadow:0 10px 30px rgba(0,0,0,.3)';
  d.innerHTML = '<b>JobTracker AI</b> rellenó ' + r.filled + ' campo(s)' + (r.files ? ' y subió ' + r.files + ' documento(s)' : '') +
    '. <span style="color:#fbbf24">' + (r.missing ? r.missing + ' pendiente(s) en naranja. ' : '') + '</span>' +
    'Revísalo todo y pulsa <b>Enviar</b> tú: la app nunca envía por ti. ' +
    '<a href="#" style="color:#93c5fd" onclick="this.parentNode.remove();return false">Ocultar</a>';
  document.body.appendChild(d);
}"""


def _launch(p, headless: bool):
    exe = os.getenv("JOBTRACKER_BROWSER")
    attempts = [{"executable_path": exe}] if exe else [{"channel": "chrome"}, {"channel": "msedge"}, {}]
    last = None
    for opts in attempts:
        try:
            return p.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=headless, no_viewport=not headless, locale="es-ES",
                args=["--disable-blink-features=AutomationControlled"], **opts)
        except Exception as e:  # noqa: BLE001  (probamos el siguiente navegador)
            last = e
    raise RuntimeError(f"no_browser: {last}")


def _fill_frames(page, profile: dict) -> dict:
    total = {"filled": [], "missing": [], "skipped": [], "files": []}
    for frame in page.frames:
        try:
            r = frame.evaluate(FILL_JS, profile)
        except Exception:  # noqa: BLE001  (iframes de terceros, anuncios…)
            continue
        for k in total:
            total[k] += r.get(k, [])
        for f in r.get("files", []):
            f["frame"] = frame
    return total


def run(pkg_id: int, url: str, profile: dict, files: dict[str, str], headless: bool = False) -> dict:
    from playwright.sync_api import sync_playwright

    write_status(pkg_id, state="starting", pid=os.getpid(), url=url, filled=[], missing=[], skipped=[],
                 uploaded=[], submitted=False, error=None, message="Abriendo el navegador…")
    shot = WORK / f"{pkg_id}.png"
    with sync_playwright() as p:
        try:
            ctx = _launch(p, headless)
        except RuntimeError as e:
            return write_status(pkg_id, state="error", error="no_browser", message=str(e)[:300])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        submitted = {"v": False}

        def on_request(req):
            if req.method == "POST" and req.resource_type in ("document", "xhr", "fetch") and SUBMIT_URL.search(req.url) \
                    and urlparse(req.url).netloc.split(".")[-2:] == urlparse(url).netloc.split(".")[-2:]:
                if not submitted["v"]:
                    submitted["v"] = True
                    write_status(pkg_id, submitted=True, message="Parece que has enviado la candidatura")
        ctx.on("request", on_request)

        try:
            write_status(pkg_id, state="filling", message="Cargando el formulario…")
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:  # noqa: BLE001
                pass
            report = _fill_frames(page, profile)
            if not report["filled"] and not report["files"]:
                # Página de la oferta sin formulario: prueba el botón «Apply / Aplicar» una vez
                btn = page.get_by_role("link", name=APPLY_BUTTON).or_(page.get_by_role("button", name=APPLY_BUTTON)).first
                if btn.count():
                    btn.click(timeout=5000)
                    page.wait_for_load_state("domcontentloaded")
                    page.wait_for_timeout(1500)
                    report = _fill_frames(page, profile)
            uploaded = []
            for f in report["files"]:
                path = files.get(f["kind"])
                if path and Path(path).exists():
                    try:
                        f["frame"].set_input_files(f'[data-jt-file="{f["kind"]}"]', path)
                        uploaded.append(f["kind"])
                    except Exception:  # noqa: BLE001
                        report["missing"].append(f["label"])
            page.evaluate(BANNER_JS, {"filled": len(report["filled"]), "files": len(uploaded),
                                      "missing": len(report["missing"])})
            page.screenshot(path=str(shot), full_page=True)
        except Exception as e:  # noqa: BLE001
            write_status(pkg_id, state="error", error="page", message=f"No se pudo rellenar: {str(e)[:240]}")
            if headless:
                ctx.close()
                return read_status(pkg_id) or {}
            report, uploaded = {"filled": [], "missing": [], "skipped": []}, []
        else:
            write_status(pkg_id, state="ready", filled=report["filled"], missing=report["missing"],
                         skipped=report["skipped"], uploaded=uploaded, screenshot=shot.exists(),
                         message="Listo para revisar en el navegador")

        if not headless:  # espera a que cierres la ventana (o 45 min)
            deadline = time.time() + MAX_OPEN
            try:
                while ctx.pages and time.time() < deadline:
                    ctx.pages[0].wait_for_timeout(1000)
            except Exception:  # noqa: BLE001  (ventana cerrada a mitad de la espera)
                pass
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass
    final = read_status(pkg_id) or {}
    state = final.get("state") if final.get("state") == "error" else "closed"
    return write_status(pkg_id, state=state, pid=None, message=final.get("message") if state == "error" else
                        ("Cerraste el navegador" + (" tras enviar" if submitted["v"] else "")))
