"""Gasto en IA: cada llamada a Claude se apunta con sus tokens y su coste estimado.

Precios en USD por millón de tokens (API de Anthropic, octubre de 2026). Las escrituras en caché
cuestan 1,25 veces la entrada; las lecturas, lo indicado. Es una estimación: la factura oficial está
en console.anthropic.com.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

PRICES = {  # entrada, salida, lectura de caché
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-fable-5-1": (10.00, 50.00, 0.25),
}
HAIKU_LONG = (0.50, 2.50, 0.05)  # Haiku 5.5 con prompts de más de 100 000 tokens

# Para qué se usó cada llamada (por el esquema de respuesta que pide)
PURPOSE = {
    "TriageBatch": "Criba de ofertas", "JobExtraction": "Análisis de ofertas", "MatchAnalysis": "Análisis de ofertas",
    "AlertExtraction": "Alertas por correo", "OptimizationResult": "Candidaturas (CV y carta)",
    "TailoredAnswers": "Candidaturas (CV y carta)", "CVExtraction": "Tu CV", "PreferencesProposal": "Configuración",
    "EmailClassification": "Correos", "InterviewPrepOut": "Entrevistas", "MockStep": "Simulacros",
    "MessageDraft": "Correos redactados", "NegotiationOut": "Ofertas y negociación", "OfferComparison": "Ofertas y negociación",
}


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_write: int = 0, cache_read: int = 0) -> float:
    prices = PRICES.get(model) or PRICES.get(model.rsplit("[", 1)[0]) or PRICES["claude-opus-5-5"]
    if model.startswith("claude-haiku-5-5") and input_tokens + cache_write + cache_read > 100_000:
        prices = HAIKU_LONG
    pin, pout, pread = prices
    return (input_tokens * pin + cache_write * pin * 1.25 + cache_read * pread + output_tokens * pout) / 1_000_000


def record(model: str, schema_name: str, usage) -> None:
    """Apunta una llamada. Nunca debe romper la llamada a la IA: los fallos se ignoran."""
    try:
        from ..database import engine
        from ..models import LLMUsage

        i = getattr(usage, "input_tokens", 0) or 0
        o = getattr(usage, "output_tokens", 0) or 0
        cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cr = getattr(usage, "cache_read_input_tokens", 0) or 0
        with Session(engine) as db:
            db.add(LLMUsage(model=model, purpose=PURPOSE.get(schema_name, "Otros"), input_tokens=i, output_tokens=o,
                            cache_write_tokens=cw, cache_read_tokens=cr, cost_usd=cost_usd(model, i, o, cw, cr)))
            db.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[gasto] no se pudo registrar: {e}")


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.astimezone().replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def spend_summary(db: Session, now: datetime | None = None, budget: float | None = None) -> dict:
    from ..models import LLMUsage

    now = now or datetime.now(timezone.utc)
    start = month_start(now)
    rows = db.exec(select(LLMUsage).where(LLMUsage.created_at >= start)).all()
    total = sum(r.cost_usd for r in rows)
    by_purpose: dict[str, dict] = {}
    for r in rows:
        p = by_purpose.setdefault(r.purpose, {"purpose": r.purpose, "cost_usd": 0.0, "calls": 0})
        p["cost_usd"] += r.cost_usd
        p["calls"] += 1
    local = now.astimezone()
    days = local.day + local.hour / 24
    days_in_month = calendar.monthrange(local.year, local.month)[1]
    projected = total / days * days_in_month if days >= 1 else total
    last30 = db.exec(select(LLMUsage).where(LLMUsage.created_at >= now - timedelta(days=30))).all()
    return {
        "month_usd": round(total, 4), "projected_usd": round(projected, 4), "calls": len(rows),
        "last30_usd": round(sum(r.cost_usd for r in last30), 4),
        "by_purpose": sorted(({**p, "cost_usd": round(p["cost_usd"], 4)} for p in by_purpose.values()),
                             key=lambda p: -p["cost_usd"]),
        "budget_usd": budget, "over_budget": bool(budget and total >= budget),
        "budget_ratio": round(total / budget, 3) if budget else None,
    }


def over_budget(db: Session, budget: float | None) -> bool:
    return bool(budget) and spend_summary(db, budget=budget)["over_budget"]


def budget_notice(db: Session, budget: float | None, now: datetime | None = None) -> str | None:
    """Aviso (una vez por mes y umbral) al pasar el 80 % y el 100 % del tope. Devuelve el texto o None."""
    import json

    from ..config import DATA_DIR

    if not budget:
        return None
    s = spend_summary(db, now, budget)
    level = "100" if s["over_budget"] else "80" if s["budget_ratio"] >= 0.8 else None
    if not level:
        return None
    marker = DATA_DIR / "budget_notice.json"
    month = (now or datetime.now(timezone.utc)).astimezone().strftime("%Y-%m")
    try:
        seen = json.loads(marker.read_text())
    except (OSError, ValueError):
        seen = {}
    key = f"{month}:{level}"
    if seen.get(key):
        return None
    seen[key] = True
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(seen))
    if level == "100":
        return (f"Has llegado a tu tope de {budget:.2f} $ este mes: el agente se pausa hasta el mes que viene "
                "(puedes subirlo en Ajustes → Gasto en IA).").replace(".", ",", 1)
    return f"Llevas {s['month_usd']:.2f} $ de tu tope de {budget:.2f} $ este mes.".replace(".", ",", 2)
