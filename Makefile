VENV ?= .venv
PY   := $(VENV)/bin/python

.PHONY: setup backend frontend dev test release pkg

setup:            ## Crea el entorno e instala dependencias (macOS)
	./scripts/setup_mac.sh

backend:          ## API en http://localhost:8000 (docs en /docs)
	cd backend && ../$(VENV)/bin/uvicorn app.main:app --reload --port 8000

frontend:         ## UI en http://localhost:8501
	$(VENV)/bin/streamlit run frontend/streamlit_app.py

dev:              ## Backend + frontend a la vez (Ctrl+C para parar ambos)
	@trap 'kill 0' INT TERM; $(MAKE) backend & $(MAKE) frontend & wait

test:
	cd backend && ../$(PY) -m pytest -q
	cd installer && ../$(PY) -m pytest -q

release:          ## Genera dist/ (tarball + manifest firmado si OTA_SIGNING_KEY está definida)
	$(PY) scripts/release.py --out dist

pkg: release      ## Genera dist/JobTrackerAI-X.Y.Z.pkg (solo en macOS)
	installer/pkg/build_pkg.sh dist
