"""Configuración general: valores por defecto, reglas de penalidad y zona horaria."""

from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("America/Lima")
CURRENCY = "S/"
PAYMENT_METHODS = ["Yape", "Plin", "Transferencia", "Efectivo"]

# Cada tramo indica: "desde N minutos de retraso, la penalidad es M soles".
# Con inicio a las 9:00 equivale a: <9:10 → S/0, 9:10–9:19 → S/1, 9:20–9:29 → S/2, ≥9:30 → S/3.
DEFAULT_PENALTY_RULES = [
    {"desde_min": 0, "monto": 0.0},
    {"desde_min": 10, "monto": 1.0},
    {"desde_min": 20, "monto": 2.0},
    {"desde_min": 30, "monto": 3.0},
]

DEFAULT_SETTINGS = {
    "app_name": "Control de Tardanzas",
    "org_name": "Voluntariado",
    "default_start_time": "09:00",
    "penalty_rules": DEFAULT_PENALTY_RULES,
}


def now_lima() -> datetime:
    """Fecha y hora actual de Lima, sin zona (así se guarda en la base de datos)."""
    return datetime.now(TIMEZONE).replace(tzinfo=None, microsecond=0)


def today_lima() -> date:
    return now_lima().date()


def parse_time(value: str | time) -> time:
    if isinstance(value, time):
        return value
    hours, minutes = value.strip().split(":")[:2]
    return time(int(hours), int(minutes))


def validate_rules(rules: list[dict]) -> list[dict]:
    """Valida y ordena los tramos. Lanza ValueError con un mensaje claro si hay errores."""
    if not rules:
        raise ValueError("Debe existir al menos un tramo de penalidad.")
    cleaned = []
    for rule in rules:
        try:
            desde = int(rule["desde_min"])
            monto = round(float(rule["monto"]), 2)
        except (KeyError, TypeError, ValueError):
            raise ValueError("Cada tramo necesita minutos (entero) y monto (número).") from None
        if desde < 0 or monto < 0:
            raise ValueError("Los minutos y montos no pueden ser negativos.")
        cleaned.append({"desde_min": desde, "monto": monto})
    cleaned.sort(key=lambda r: r["desde_min"])
    starts = [r["desde_min"] for r in cleaned]
    if len(set(starts)) != len(starts):
        raise ValueError("Hay dos tramos que empiezan en el mismo minuto.")
    if starts[0] != 0:
        raise ValueError("El primer tramo debe empezar en 0 minutos de retraso.")
    return cleaned


def penalty_for_delay(delay_minutes: int, rules: list[dict]) -> Decimal:
    """Penalidad según el tramo en el que cae el retraso (no se multiplica por minuto)."""
    amount = 0.0
    for rule in sorted(rules, key=lambda r: r["desde_min"]):
        if delay_minutes >= rule["desde_min"]:
            amount = rule["monto"]
    return Decimal(str(amount)).quantize(Decimal("0.01"))


def delay_minutes(start: time, arrival: time) -> int:
    """Minutos exactos de retraso. Llegar antes o justo a la hora = 0."""
    start_m = start.hour * 60 + start.minute
    arrival_m = arrival.hour * 60 + arrival.minute
    return max(0, arrival_m - start_m)


def describe_rules(rules: list[dict], start: time) -> list[str]:
    """Texto legible de los tramos a partir de una hora de inicio."""

    def clock(minutes: int) -> str:
        total = start.hour * 60 + start.minute + minutes
        h, m = divmod(total, 60)
        suffix = "a. m." if h % 24 < 12 else "p. m."
        h12 = h % 12 or 12
        return f"{h12}:{m:02d} {suffix}"

    ordered = sorted(rules, key=lambda r: r["desde_min"])
    lines = []
    for i, rule in enumerate(ordered):
        amount = f"{CURRENCY} {rule['monto']:.2f}"
        if i + 1 < len(ordered):
            nxt = ordered[i + 1]["desde_min"]
            if rule["desde_min"] == 0:
                lines.append(f"Antes de las {clock(nxt)} → {amount}")
            else:
                lines.append(f"Desde las {clock(rule['desde_min'])} hasta antes de las {clock(nxt)} → {amount}")
        else:
            lines.append(f"Desde las {clock(rule['desde_min'])} en adelante → {amount}")
    return lines


# ---------------------------------------------------------------- persistencia


def get_settings() -> dict:
    """Lee la configuración guardada, completando con valores por defecto."""
    import database as db

    values = dict(DEFAULT_SETTINGS)
    with db.get_engine().connect() as conn:
        for row in conn.execute(db.settings.select()):
            try:
                values[row.key] = json.loads(row.value)
            except json.JSONDecodeError:
                values[row.key] = row.value
    return values


def save_settings(changes: dict) -> None:
    """Guarda los valores modificados. Solo afecta a los registros nuevos."""
    import database as db

    if "penalty_rules" in changes:
        changes["penalty_rules"] = validate_rules(changes["penalty_rules"])
    if "default_start_time" in changes:
        changes["default_start_time"] = parse_time(changes["default_start_time"]).strftime("%H:%M")

    current = get_settings()
    with db.transaction() as conn:
        for key, value in changes.items():
            if current.get(key) == value:
                continue
            payload = json.dumps(value, ensure_ascii=False)
            updated = conn.execute(
                db.settings.update().where(db.settings.c.key == key).values(value=payload, updated_at=now_lima())
            )
            if updated.rowcount == 0:
                conn.execute(db.settings.insert().values(key=key, value=payload, updated_at=now_lima()))
            db.log_change(conn, "configuracion", None, "modificar", {"clave": key, "antes": current.get(key), "despues": value})
