"""Ventana nativa de JobTracker AI (macOS: WKWebView vía pywebview).

    python -m app.desktop        (lo lanza «JobTracker AI.app»; el backend ya debe estar arrancado)

- Una sola ventana a la vez (si ya está abierta, la segunda invocación sale sin hacer nada).
- El color de fondo de la ventana coincide con el tema para que no haya destello blanco al abrir.
- Los enlaces externos (ofertas) se abren en el navegador y los PDF se descargan con diálogo nativo.
- Sin pywebview (o fuera de macOS) abre la interfaz en el navegador como alternativa.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser

from .config import DATA_DIR, ROOT_DIR

URL = os.getenv("JOBTRACKER_UI_URL", "http://127.0.0.1:8000/")
ICON = ROOT_DIR / "installer" / "assets" / "AppIcon.icns"
APP_NAME = "JobTracker AI"

# Fondo de cada tema (debe coincidir con --bg en assets/css/themes.css)
THEME_BG = {
    "porcelana": "#f7f7f5", "grafito": "#151517", "oceano": "#f2f7fa", "bosque": "#111a16",
    "atardecer": "#fbf6f1", "lavanda": "#f6f4fb", "medianoche": "#0d1220", "arena": "#f5f1e8",
}


def wait_backend(timeout: float = 60) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(URL.rstrip("/") + "/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except OSError:
            time.sleep(0.3)
    return False


def _system_dark() -> bool:
    if sys.platform != "darwin":
        return False
    r = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True)
    return "Dark" in r.stdout


def window_background() -> str:
    try:
        theme = json.loads((DATA_DIR / "ui.json").read_text()).get("theme", "auto")
    except (OSError, ValueError):
        theme = "auto"
    if theme == "auto":
        theme = "grafito" if _system_dark() else "porcelana"
    return THEME_BG.get(theme, THEME_BG["porcelana"])


def _mac_identity() -> None:
    """Nombre en la barra de menús e icono del Dock (el proceso es Python, no un bundle propio)."""
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle

        info = NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = APP_NAME
        info["CFBundleDisplayName"] = APP_NAME
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(0)  # NSApplicationActivationPolicyRegular: icono en el Dock
        if ICON.exists():
            app.setApplicationIconImage_(NSImage.alloc().initWithContentsOfFile_(str(ICON)))
    except Exception as e:  # puramente estético: nunca debe impedir abrir la ventana
        print(f"[desktop] identidad de la app no aplicada: {e}")


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock = open(DATA_DIR / "desktop.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("[desktop] la ventana ya está abierta")
        return 0

    if not wait_backend():
        print("[desktop] el backend no responde")
        return 1

    try:
        import webview
    except ImportError:
        print("[desktop] pywebview no disponible: abriendo en el navegador")
        webbrowser.open(URL)
        return 0

    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    if sys.platform == "darwin":
        _mac_identity()

    window = webview.create_window(
        APP_NAME, URL, width=1240, height=820, min_size=(960, 640),
        background_color=window_background(), text_select=True, zoomable=True,
    )

    smoke = os.getenv("JOBTRACKER_DESKTOP_SMOKE")  # CI: cierra la ventana tras N segundos

    def on_started():
        if smoke:
            time.sleep(float(smoke))
            window.destroy()

    webview.start(on_started, private_mode=False, storage_path=str(DATA_DIR / "webview"),
                  icon=str(ICON) if ICON.exists() else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
