"""JobTracker AI · API (FastAPI) + interfaz.

Arranque:  uvicorn app.main:app --reload   (desde la carpeta backend/)
Interfaz:  http://localhost:8000/   (la app de escritorio abre esta misma URL en una ventana nativa)
Docs:      http://localhost:8000/docs
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT_DIR, VERSION
from .database import init_db
from .routers import agent, applications, autofill, cv, emails, jobs, packages, settings, stats, status, system

WEB_DIR = ROOT_DIR / "frontend" / "web"
CLIENT_HEADER = "x-jobtracker"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    moved = settings.migrate_to_keychain(settings.secret_names())
    if moved:
        print(f"[llavero] claves pasadas al Llavero de macOS: {', '.join(moved)}")
    if settings.migrate_cost_profile():
        print("[ajustes] instalación pasada al perfil económico (Claude Haiku)")
    yield


app = FastAPI(title="JobTracker AI", version=VERSION, lifespan=lifespan)


@app.middleware("http")
async def require_client_header(request: Request, call_next):
    """Protección CSRF: la API escucha en localhost, así que cualquier web abierta en el navegador
    podría enviarle peticiones. Una cabecera propia obliga al navegador a pedir permiso (preflight
    CORS), que se deniega a otros orígenes. Solo nuestra interfaz la envía."""
    if request.url.path.startswith("/api/") and request.method not in SAFE_METHODS \
            and request.headers.get(CLIENT_HEADER) != "1":
        return JSONResponse({"detail": "Petición no autorizada"}, status_code=403)
    response = await call_next(request)
    if request.url.path.startswith("/assets/"):
        # Revalidar siempre (servidor local: es instantáneo) para que una OTA nunca deje módulos viejos en caché
        response.headers["Cache-Control"] = "no-cache"
    return response


for r in (cv.router, jobs.router, applications.router, autofill.router, emails.router, system.router, agent.router,
          packages.router, settings.router, stats.router, status.router):
    app.include_router(r)

if WEB_DIR.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")


@app.get("/health")
def health():
    return {"status": "ok"}


def _page(name: str) -> HTMLResponse:
    """Sirve una página con el tema ya aplicado (sin parpadeo) y los assets versionados
    (cada actualización OTA invalida la caché de la ventana)."""
    html = (WEB_DIR / name).read_text(encoding="utf-8")
    ui = settings.load_ui()
    html = html.replace("{{THEME}}", ui.theme).replace("{{VERSION}}", VERSION) \
        .replace("{{MOTION}}", "reduce" if ui.reduce_motion else "full")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index():
    return _page("index.html")


@app.get("/capture", response_class=HTMLResponse, include_in_schema=False)
def capture():
    """Destino del botón «Guardar en JobTracker» del navegador (los datos van en el #fragmento)."""
    return _page("capture.html")
