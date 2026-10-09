"""Contexto regional (Costa Rica y Latinoamérica primero).

- Nombres y ciudades de cada país, para filtrar por ubicación.
- Ofertas «remotas» que en realidad solo contratan en EE. UU., Europa…: se descartan si no incluyen tu país.
- Costumbres salariales y laborales de cada país para la negociación y las ofertas.
"""
from __future__ import annotations

import re
import unicodedata

COUNTRIES: dict[str, dict] = {
    "CR": {"name": "Costa Rica", "iso3": "CRI", "currency": "CRC", "period": "mensual", "thirteenth": True,
           "places": ["costa rica", "san jose", "heredia", "alajuela", "cartago", "escazu", "santa ana", "belen",
                      "curridabat", "la uruca", "puntarenas", "liberia", "san pedro", "zona franca", "coyol", "lagunilla"]},
    "MX": {"name": "México", "iso3": "MEX", "currency": "MXN", "period": "mensual", "thirteenth": True,
           "places": ["mexico", "cdmx", "ciudad de mexico", "guadalajara", "monterrey", "queretaro", "puebla", "merida"]},
    "CO": {"name": "Colombia", "iso3": "COL", "currency": "COP", "period": "mensual", "thirteenth": True,
           "places": ["colombia", "bogota", "medellin", "cali", "barranquilla", "bucaramanga"]},
    "AR": {"name": "Argentina", "iso3": "ARG", "currency": "ARS", "period": "mensual", "thirteenth": True,
           "places": ["argentina", "buenos aires", "cordoba", "rosario", "mendoza", "caba"]},
    "CL": {"name": "Chile", "iso3": "CHL", "currency": "CLP", "period": "mensual", "thirteenth": False,
           "places": ["chile", "santiago", "valparaiso", "concepcion"]},
    "PE": {"name": "Perú", "iso3": "PER", "currency": "PEN", "period": "mensual", "thirteenth": True,
           "places": ["peru", "lima", "arequipa"]},
    "GT": {"name": "Guatemala", "iso3": "GTM", "currency": "GTQ", "period": "mensual", "thirteenth": True,
           "places": ["guatemala"]},
    "PA": {"name": "Panamá", "iso3": "PAN", "currency": "USD", "period": "mensual", "thirteenth": True,
           "places": ["panama"]},
    "SV": {"name": "El Salvador", "iso3": "SLV", "currency": "USD", "period": "mensual", "thirteenth": True,
           "places": ["el salvador", "san salvador"]},
    "HN": {"name": "Honduras", "iso3": "HND", "currency": "HNL", "period": "mensual", "thirteenth": True,
           "places": ["honduras", "tegucigalpa", "san pedro sula"]},
    "DO": {"name": "República Dominicana", "iso3": "DOM", "currency": "DOP", "period": "mensual", "thirteenth": True,
           "places": ["republica dominicana", "dominican republic", "santo domingo"]},
    "UY": {"name": "Uruguay", "iso3": "URY", "currency": "UYU", "period": "mensual", "thirteenth": True,
           "places": ["uruguay", "montevideo"]},
    "EC": {"name": "Ecuador", "iso3": "ECU", "currency": "USD", "period": "mensual", "thirteenth": True,
           "places": ["ecuador", "quito", "guayaquil"]},
    "BR": {"name": "Brasil", "iso3": "BRA", "currency": "BRL", "period": "mensual", "thirteenth": True,
           "places": ["brasil", "brazil", "sao paulo", "rio de janeiro"]},
    "ES": {"name": "España", "iso3": "ESP", "currency": "EUR", "period": "anual", "thirteenth": False,
           "places": ["espana", "spain", "madrid", "barcelona", "valencia", "sevilla"]},
}
LATAM = {"CR", "MX", "CO", "AR", "CL", "PE", "GT", "PA", "SV", "HN", "DO", "UY", "EC", "BR"}

# Remoto abierto a tu región
OPEN_REMOTE = re.compile(
    r"\b(latam|latin america|latinoamerica|america latina|americas|central america|centroamerica|south america|"
    r"sudamerica|worldwide|anywhere|global(ly)?|todo el mundo|cualquier pais|nearshore)\b")
# Remoto restringido a otra región
RESTRICTED = re.compile(
    r"\b(?:(?:us|usa|u\.s\.|united states|canada|uk|united kingdom|europe|eu|emea|apac|india|germany|spain)"
    r"[\s-]*(?:only|based|residents?|citizens?)\b"
    r"|(?:must|need to|required to) (?:be )?(?:located|based|living|reside|residing) in (?:the )?"
    r"(?:us|usa|u\.s\.|united states|canada|uk|united kingdom|europe|eu)\b"
    r"|remote[\s,(-]+(?:us|usa|united states|canada|uk|europe|eu|emea)\b"
    r"|(?:us|usa|united states|canada|uk|europe|eu|emea)[\s,)-]+remote\b"
    r"|authorized to work in the (?:us|united states)\b)", re.I)


def norm(text: str | None) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def country_info(code: str | None) -> dict | None:
    return COUNTRIES.get((code or "").upper())


def guess_country(*texts: str | None) -> str | None:
    """ISO2 del país mencionado en un texto (ubicación del CV, de la oferta…)."""
    blob = f" {norm(' '.join(t for t in texts if t))} "
    for code, info in COUNTRIES.items():
        if any(f" {p} " in blob or f" {p}," in blob or f",{p} " in blob for p in info["places"][:1] + info["places"]):
            return code
    return None


_US_SAN_JOSE = re.compile(r"san jose,?\s*(ca\b|california)")


def mentions_country(text: str | None, code: str | None) -> bool:
    info = country_info(code)
    if not info or not text:
        return False
    blob = norm(text)
    if code == "CR" and _US_SAN_JOSE.search(blob) and "costa rica" not in blob:
        return False  # San José de California no es San José de Costa Rica
    return any(p in blob for p in info["places"])


def remote_restriction(location: str | None, description: str | None, code: str | None) -> str | None:
    """Si una oferta remota solo contrata en otra región, devuelve el fragmento que lo dice."""
    loc = norm(location)
    head = norm((description or "")[:2500])
    if mentions_country(loc, code) or OPEN_REMOTE.search(loc):
        return None
    if code in LATAM and (OPEN_REMOTE.search(head) or mentions_country(head, code)):
        return None
    m = RESTRICTED.search(f"{loc}\n{head}")
    return m.group(0).strip() if m else None


def market_context(code: str | None) -> str:
    """Costumbres laborales del país para la IA (negociación, ofertas, cartas)."""
    if code == "CR":
        return ("Mercado de Costa Rica: los salarios se hablan en bruto MENSUAL, en colones o, en multinacionales y "
                "empresas de servicios (zonas francas), a menudo en dólares. El aguinaldo es obligatorio (un salario "
                "extra al año, proporcional, pagado en diciembre). Al trabajador se le descuenta la CCSS (en torno al "
                "10,7 %) y el impuesto sobre la renta por tramos. Vacaciones legales mínimas: 2 semanas por cada 50 "
                "semanas trabajadas. Beneficios habituales a negociar: asociación solidarista, seguro médico privado, "
                "teletrabajo (Ley 9738), bonos y formación. En correos profesionales se usa «usted».")
    info = country_info(code)
    if info and code in LATAM:
        extra = "Hay aguinaldo o 13.er salario obligatorio. " if info["thirteenth"] else ""
        return (f"Mercado de {info['name']}: los salarios suelen hablarse en bruto mensual ({info['currency']} o USD en "
                f"empresas internacionales). {extra}Considera prestaciones de ley y beneficios habituales del país.")
    if info:
        return f"Mercado de {info['name']}: salarios en bruto {info['period']} ({info['currency']})."
    return ""
