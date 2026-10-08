"""Fechas: todo se guarda en UTC con zona horaria.

Lo que llega «sin zona» (lo que el usuario escribe en un campo de fecha, o «el jueves a las 10:00»
que la IA extrae de un correo) es hora local del Mac donde corre la app: se convierte a UTC.
"""
from datetime import datetime, timezone


def to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # interpreta la hora como local del sistema
    return dt.astimezone(timezone.utc)
