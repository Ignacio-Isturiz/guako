"""Reglas de la racha (estilo TikTok). Lógica pura: no toca la base de datos ni el reloj.

- Cuenta un día cuando el usuario completa una acción clave (terminar una conversación).
  Varias acciones el mismo día cuentan una sola vez.
- "Día" = día de calendario en la zona horaria del usuario (el endpoint la convierte a `date`).
- Si falla un día, tiene el SIGUIENTE para recuperar: al completar la acción ese día gasta
  1 oportunidad y la racha sigue. Son 3 por mes (se renuevan cada mes, no se acumulan).
- Si no lo aprovecha (o ya no le quedan oportunidades), la racha se acaba y NO se gasta nada.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

StreakStatus = Literal["none", "done", "pending", "recoverable"]

MAX_RECOVERIES = 3  # oportunidades de recuperar por mes


@dataclass
class StreakData:
    current: int = 0
    best: int = 0
    last_day: date | None = None  # último día con actividad
    recoveries_used: int = 0
    recoveries_month: str = ""  # mes ("2026-11") al que corresponde recoveries_used


def month_key(day: date) -> str:
    return f"{day.year}-{day.month:02d}"


def recoveries_left(data: StreakData, today: date) -> int:
    """Oportunidades que quedan en el mes de `today` (un mes nuevo las renueva a 3)."""
    used = data.recoveries_used if data.recoveries_month == month_key(today) else 0
    return max(0, MAX_RECOVERIES - used)


def _gap(data: StreakData, today: date) -> int | None:
    return None if data.last_day is None else (today - data.last_day).days


def status(data: StreakData, today: date) -> StreakStatus:
    """none | done | pending | recoverable

    done        ya hizo la acción hoy
    pending     la racha está viva; falta hacer la acción hoy
    recoverable falló ayer; si la hace hoy gasta 1 oportunidad y la racha sigue
    none        no hay racha (nunca empezó o ya se acabó)
    """
    gap = _gap(data, today)
    if gap is None or data.current == 0:
        return "none"
    if gap <= 0:
        return "done"
    if gap == 1:
        return "pending"
    if gap == 2 and recoveries_left(data, today) > 0:
        return "recoverable"
    return "none"


def current_count(data: StreakData, today: date) -> int:
    """Racha que se muestra hoy (0 si ya se acabó)."""
    return data.current if status(data, today) != "none" else 0


def register_activity(data: StreakData, today: date) -> bool:
    """Registra una acción clave hecha hoy. Devuelve True si gastó una oportunidad de recuperar."""
    gap = _gap(data, today)
    if gap is not None and gap <= 0:
        return False  # ya contaba hoy (o el reloj retrocedió): no suma dos veces

    recovered = False
    st = status(data, today)
    if st == "pending":
        data.current += 1
    elif st == "recoverable":
        if data.recoveries_month != month_key(today):
            data.recoveries_month = month_key(today)
            data.recoveries_used = 0
        data.recoveries_used += 1
        data.current += 1
        recovered = True
    else:  # nunca hubo racha o se acabó: empieza de nuevo
        data.current = 1

    data.last_day = today
    data.best = max(data.best, data.current)
    return recovered
