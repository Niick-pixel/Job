VENV ?= .venv
PY   := $(VENV)/bin/python

.PHONY: setup backend desktop dev test release pkg

setup:            ## Crea el entorno e instala dependencias (macOS)
	./scripts/setup_mac.sh

backend:          ## API + interfaz en http://localhost:8000 (docs en /docs)
	cd backend && ../$(VENV)/bin/uvicorn app.main:app --reload --port 8000

desktop:          ## Ventana nativa (macOS; con el backend ya arrancado)
	cd backend && ../$(PY) -m app.desktop

dev:              ## Backend con la interfaz en http://localhost:8000 (recarga al guardar)
	$(MAKE) backend

test:
	cd backend && ../$(PY) -m pytest -q
	cd installer && ../$(PY) -m pytest -q

release:          ## Genera dist/ (tarball + manifest firmado si OTA_SIGNING_KEY está definida)
	$(PY) scripts/release.py --out dist

pkg: release      ## Genera dist/JobTrackerAI-X.Y.Z.pkg (solo en macOS)
	installer/pkg/build_pkg.sh dist
