from fastapi import APIRouter, Depends
from sqlmodel import Session

from ..database import get_session
from ..services.stats import build_stats

router = APIRouter(tags=["Resultados"])


@router.get("/api/stats")
def stats(db: Session = Depends(get_session)):
    """Embudo, respuesta por fuente y por CV, tiempo de respuesta, actividad semanal y agente."""
    return build_stats(db)
