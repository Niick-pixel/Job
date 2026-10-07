"""JobTracker AI · API (FastAPI).

Arranque:  uvicorn app.main:app --reload   (desde la carpeta backend/)
Docs:      http://localhost:8000/docs
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db
from .routers import applications, cv, emails, jobs


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="JobTracker AI", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (cv.router, jobs.router, applications.router, emails.router):
    app.include_router(r)


@app.get("/health")
def health():
    return {"status": "ok"}
