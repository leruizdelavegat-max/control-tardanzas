"""Registro de actividades y tardanzas, con cálculo automático de retraso y penalidad."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal

import pandas as pd
import sqlalchemy as sa

import database as db
import payments
import volunteers
from config import delay_minutes, get_settings, now_lima, penalty_for_delay, today_lima


class TardyError(ValueError):
    pass


@dataclass
class Calculation:
    delay_minutes: int
    penalty: Decimal


def calculate(start: time, arrival: time, rules: list[dict]) -> Calculation:
    minutes = delay_minutes(start, arrival)
    return Calculation(minutes, penalty_for_delay(minutes, rules))


# ------------------------------------------------------------------ actividades


def get_or_create_activity(name: str, activity_date: date, start_time: time) -> tuple[int, bool, time]:
    """Devuelve (id, creada, hora_de_inicio). Si ya existe una actividad con el mismo
    nombre y fecha se reutiliza, conservando su hora de inicio original."""
    name = db.clean_name(name)
    if len(name) < 2:
        raise TardyError("Escribe el nombre de la actividad.")
    if activity_date > today_lima():
        raise TardyError("La fecha de la actividad no puede ser futura.")
    key = db.normalize_key(name)
    with db.transaction() as conn:
        existing = conn.execute(
            sa.select(db.activities).where(
                db.activities.c.name_key == key, db.activities.c.activity_date == activity_date
            )
        ).mappings().first()
        if existing:
            return existing["id"], False, existing["start_time"]
        new_id = conn.execute(
            db.activities.insert()
            .values(name=name, name_key=key, activity_date=activity_date, start_time=start_time, created_at=now_lima())
            .returning(db.activities.c.id)
        ).scalar_one()
        db.log_change(conn, "actividad", new_id, "crear", {"nombre": name, "fecha": activity_date, "inicio": start_time})
        return new_id, True, start_time


def get_activity(activity_id: int) -> dict | None:
    with db.get_engine().connect() as conn:
        row = conn.execute(sa.select(db.activities).where(db.activities.c.id == activity_id)).mappings().first()
    return dict(row) if row else None


def list_activities() -> pd.DataFrame:
    a, t = db.activities, db.tardies
    count = sa.func.count(t.c.id)
    stmt = (
        sa.select(
            a.c.id, a.c.name, a.c.activity_date, a.c.start_time,
            count.label("tardies"),
            sa.func.coalesce(sa.func.sum(t.c.penalty), 0).label("total_penalty"),
        )
        .select_from(a.outerjoin(t, sa.and_(t.c.activity_id == a.c.id, t.c.status != db.STATUS_VOID)))
        .group_by(a.c.id, a.c.name, a.c.activity_date, a.c.start_time)
        .order_by(a.c.activity_date.desc(), a.c.name)
    )
    with db.get_engine().connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    df = pd.DataFrame(rows, columns=["id", "name", "activity_date", "start_time", "tardies", "total_penalty"])
    df["total_penalty"] = df["total_penalty"].astype(float)
    return df


def activity_names() -> list[str]:
    with db.get_engine().connect() as conn:
        rows = conn.execute(
            sa.select(db.activities.c.name, sa.func.max(db.activities.c.activity_date).label("last"))
            .group_by(db.activities.c.name)
            .order_by(sa.desc("last"))
        ).all()
    return [r.name for r in rows]


def update_activity(activity_id: int, name: str, activity_date: date, start_time: time) -> int:
    """Corrige los datos de una actividad. Si cambia la hora de inicio, recalcula el
    retraso de sus tardanzas usando las reglas que tenía cada registro.
    Devuelve el número de tardanzas recalculadas."""
    name = db.clean_name(name)
    if len(name) < 2:
        raise TardyError("Escribe el nombre de la actividad.")
    if activity_date > today_lima():
        raise TardyError("La fecha de la actividad no puede ser futura.")
    with db.transaction() as conn:
        current = conn.execute(sa.select(db.activities).where(db.activities.c.id == activity_id)).mappings().one()
        clash = conn.execute(
            sa.select(db.activities.c.id).where(
                db.activities.c.name_key == db.normalize_key(name),
                db.activities.c.activity_date == activity_date,
                db.activities.c.id != activity_id,
            )
        ).first()
        if clash:
            raise TardyError("Ya existe otra actividad con ese nombre en esa fecha.")
        conn.execute(
            db.activities.update()
            .where(db.activities.c.id == activity_id)
            .values(name=name, name_key=db.normalize_key(name), activity_date=activity_date, start_time=start_time)
        )
        recalculated = 0
        if start_time != current["start_time"]:
            rows = conn.execute(
                sa.select(db.tardies).where(db.tardies.c.activity_id == activity_id, db.tardies.c.status != db.STATUS_VOID)
            ).mappings().all()
            for row in rows:
                calc = calculate(start_time, row["arrival_time"], json.loads(row["rules_snapshot"]))
                _apply_calculation(conn, row, start_time, calc, row["rules_snapshot"], "cambio de hora de inicio")
                recalculated += 1
        db.log_change(
            conn, "actividad", activity_id, "editar",
            {"antes": {k: current[k] for k in ("name", "activity_date", "start_time")},
             "despues": {"name": name, "activity_date": activity_date, "start_time": start_time}},
        )
    return recalculated


# -------------------------------------------------------------------- tardanzas


def register_tardy(
    activity_id: int,
    volunteer_name: str,
    arrival_time: time,
    notes: str | None = None,
    client_token: str | None = None,
) -> dict:
    """Registra una tardanza con su deuda en estado «Pendiente».

    Es idempotente respecto a ``client_token``: si el mismo envío llega dos veces
    (doble clic, reintento por mala conexión) no se crea un duplicado."""
    rules = get_settings()["penalty_rules"]
    with db.transaction() as conn:
        return _insert_tardy(conn, _load_activity(conn, activity_id), rules, volunteer_name, arrival_time, notes,
                             client_token)


def register_tardies(activity_id: int, entries: list[dict], batch_token: str | None = None) -> list[dict]:
    """Guarda varias tardanzas de una misma actividad en una sola operación: se guardan
    todas o ninguna. Cada entrada es {"name", "arrival", "notes"}."""
    if not entries:
        raise TardyError("La lista está vacía.")
    keys = [db.normalize_key(e["name"]) for e in entries]
    if len(set(keys)) != len(keys):
        raise TardyError("Hay un voluntario repetido en la lista.")
    rules = get_settings()["penalty_rules"]
    with db.transaction() as conn:
        activity = _load_activity(conn, activity_id)
        results = []
        for i, entry in enumerate(entries):
            token = f"{batch_token}-{i}" if batch_token else None
            try:
                results.append(_insert_tardy(conn, activity, rules, entry["name"], entry["arrival"],
                                             entry.get("notes"), token))
            except (TardyError, volunteers.VolunteerError) as exc:
                raise TardyError(f"{entry['name']}: {exc}") from None
    return results


def _load_activity(conn: sa.Connection, activity_id: int):
    activity = conn.execute(sa.select(db.activities).where(db.activities.c.id == activity_id)).mappings().first()
    if not activity:
        raise TardyError("La actividad seleccionada no existe.")
    return activity


def _insert_tardy(conn, activity, rules, volunteer_name, arrival_time, notes, client_token) -> dict:
    if client_token:
        dup = conn.execute(sa.select(db.tardies.c.id).where(db.tardies.c.client_token == client_token)).scalar()
        if dup:
            return {"id": dup, "duplicate": True}

    calc = calculate(activity["start_time"], arrival_time, rules)
    if calc.delay_minutes == 0:
        raise TardyError("La hora de llegada no es posterior a la hora de inicio: no hay tardanza que registrar.")

    volunteer_id, created = volunteers.get_or_create(conn, volunteer_name)
    already = conn.execute(
        sa.select(db.tardies.c.id).where(
            db.tardies.c.activity_id == activity["id"],
            db.tardies.c.volunteer_id == volunteer_id,
            db.tardies.c.status != db.STATUS_VOID,
        )
    ).scalar()
    if already:
        raise TardyError("Este voluntario ya tiene una tardanza registrada en esta actividad.")

    now = now_lima()
    tardy_id = conn.execute(
        db.tardies.insert()
        .values(
            activity_id=activity["id"],
            volunteer_id=volunteer_id,
            start_time=activity["start_time"],
            arrival_time=arrival_time,
            delay_minutes=calc.delay_minutes,
            penalty=calc.penalty,
            rules_snapshot=json.dumps(rules),
            status=db.STATUS_PENDING,
            notes=(notes or "").strip() or None,
            registered_at=now,
            updated_at=now,
            client_token=client_token,
        )
        .returning(db.tardies.c.id)
    ).scalar_one()
    db.log_change(
        conn, "tardanza", tardy_id, "registrar",
        {"actividad": activity["id"], "voluntario": volunteer_id, "llegada": arrival_time,
         "retraso": calc.delay_minutes, "penalidad": calc.penalty},
    )
    return {
        "id": tardy_id,
        "duplicate": False,
        "volunteer_created": created,
        "delay_minutes": calc.delay_minutes,
        "penalty": calc.penalty,
    }


def _apply_calculation(conn, row, start_time: time, calc: Calculation, rules_json: str, reason: str) -> None:
    if calc.delay_minutes == 0:
        raise TardyError("Con estos datos ya no hay retraso. Si corresponde, anula el registro.")
    conn.execute(
        db.tardies.update()
        .where(db.tardies.c.id == row["id"])
        .values(
            start_time=start_time,
            delay_minutes=calc.delay_minutes,
            penalty=calc.penalty,
            rules_snapshot=rules_json,
            updated_at=now_lima(),
        )
    )
    payments.refresh_status(conn, row["id"])
    if Decimal(str(row["penalty"])) != calc.penalty or row["delay_minutes"] != calc.delay_minutes:
        db.log_change(
            conn, "tardanza", row["id"], "recalcular",
            {"motivo": reason, "retraso_antes": row["delay_minutes"], "retraso_despues": calc.delay_minutes,
             "penalidad_antes": row["penalty"], "penalidad_despues": calc.penalty},
        )


def update_tardy(tardy_id: int, arrival_time: time, notes: str | None, reason: str) -> None:
    """Corrige la hora de llegada u observaciones. Usa las reglas originales del registro."""
    reason = (reason or "").strip()
    if not reason:
        raise TardyError("Indica el motivo de la corrección.")
    with db.transaction() as conn:
        row = conn.execute(sa.select(db.tardies).where(db.tardies.c.id == tardy_id)).mappings().first()
        if not row or row["status"] == db.STATUS_VOID:
            raise TardyError("El registro no existe o está anulado.")
        calc = calculate(row["start_time"], arrival_time, json.loads(row["rules_snapshot"]))
        if calc.penalty < Decimal(str(row["penalty"])):
            paid, _ = payments._paid_total(conn, tardy_id)
            if paid > calc.penalty:
                raise TardyError("La nueva penalidad sería menor que lo ya pagado. Anula primero el pago.")
        conn.execute(
            db.tardies.update()
            .where(db.tardies.c.id == tardy_id)
            .values(arrival_time=arrival_time, notes=(notes or "").strip() or None, updated_at=now_lima())
        )
        _apply_calculation(conn, row, row["start_time"], calc, row["rules_snapshot"], reason)
        db.log_change(
            conn, "tardanza", tardy_id, "editar",
            {"motivo": reason, "llegada_antes": row["arrival_time"], "llegada_despues": arrival_time,
             "obs_antes": row["notes"], "obs_despues": notes},
        )


def void_tardy(tardy_id: int, reason: str) -> None:
    """Anula un registro (no se borra: queda en el historial de cambios)."""
    reason = (reason or "").strip()
    if not reason:
        raise TardyError("Indica el motivo de la anulación.")
    with db.transaction() as conn:
        row = conn.execute(sa.select(db.tardies).where(db.tardies.c.id == tardy_id)).mappings().first()
        if not row:
            raise TardyError("El registro no existe.")
        if row["status"] == db.STATUS_VOID:
            raise TardyError("El registro ya estaba anulado.")
        _, count = payments._paid_total(conn, tardy_id)
        if count:
            raise TardyError("Tiene pagos registrados. Anula primero los pagos en «Control de pagos».")
        conn.execute(
            db.tardies.update()
            .where(db.tardies.c.id == tardy_id)
            .values(status=db.STATUS_VOID, void_reason=reason, updated_at=now_lima())
        )
        db.log_change(conn, "tardanza", tardy_id, "anular", {"motivo": reason, "penalidad": row["penalty"]})


def preview_recalculation(tardy_ids: list[int], rules: list[dict]) -> pd.DataFrame:
    """Muestra cómo cambiarían las penalidades con las reglas indicadas (sin guardar)."""
    if not tardy_ids:
        return pd.DataFrame(columns=["id", "penalty_before", "penalty_after"])
    with db.get_engine().connect() as conn:
        rows = conn.execute(
            sa.select(db.tardies.c.id, db.tardies.c.delay_minutes, db.tardies.c.penalty).where(
                db.tardies.c.id.in_(tardy_ids), db.tardies.c.status != db.STATUS_VOID
            )
        ).all()
    data = [
        {"id": r.id, "penalty_before": float(r.penalty), "penalty_after": float(penalty_for_delay(r.delay_minutes, rules))}
        for r in rows
    ]
    return pd.DataFrame(data, columns=["id", "penalty_before", "penalty_after"])


def recalculate_with_rules(tardy_ids: list[int], rules: list[dict]) -> int:
    """Aplica las reglas indicadas a registros existentes (solo a pedido expreso del
    administrador). Omite los ya pagados para no descuadrar la caja. Devuelve los modificados."""
    rules_json = json.dumps(rules)
    changed = 0
    with db.transaction() as conn:
        rows = conn.execute(
            sa.select(db.tardies).where(db.tardies.c.id.in_(tardy_ids), db.tardies.c.status == db.STATUS_PENDING)
        ).mappings().all()
        for row in rows:
            calc = calculate(row["start_time"], row["arrival_time"], rules)
            paid, _ = payments._paid_total(conn, row["id"])
            if paid > calc.penalty:
                continue
            if calc.penalty != Decimal(str(row["penalty"])) or rules_json != row["rules_snapshot"]:
                _apply_calculation(conn, row, row["start_time"], calc, rules_json, "recálculo con reglas vigentes")
                changed += 1
    return changed


# -------------------------------------------------------------- consultas


RECORD_COLUMNS = [
    "id", "activity_id", "activity", "activity_date", "volunteer_id", "volunteer", "start_time", "arrival_time",
    "delay_minutes", "penalty", "status", "notes", "registered_at", "updated_at", "void_reason",
]


def fetch_records(include_void: bool = False) -> pd.DataFrame:
    """Todas las tardanzas con sus datos de pago agregados, listas para tablas y reportes."""
    t, a, v = db.tardies, db.activities, db.volunteers
    stmt = (
        sa.select(
            t.c.id, t.c.activity_id, a.c.name.label("activity"), a.c.activity_date, t.c.volunteer_id,
            v.c.name.label("volunteer"), t.c.start_time, t.c.arrival_time, t.c.delay_minutes, t.c.penalty,
            t.c.status, t.c.notes, t.c.registered_at, t.c.updated_at, t.c.void_reason,
        )
        .select_from(t.join(a, t.c.activity_id == a.c.id).join(v, t.c.volunteer_id == v.c.id))
        .order_by(a.c.activity_date.desc(), a.c.name, t.c.arrival_time)
    )
    if not include_void:
        stmt = stmt.where(t.c.status != db.STATUS_VOID)
    with db.get_engine().connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    df = pd.DataFrame(rows, columns=RECORD_COLUMNS)
    df["penalty"] = df["penalty"].astype(float)
    df["delay_minutes"] = df["delay_minutes"].astype(int)
    df["activity_date"] = pd.to_datetime(df["activity_date"])
    df["registered_at"] = pd.to_datetime(df["registered_at"])

    pays = payments.fetch_payments()
    if pays.empty:
        agg = pd.DataFrame(columns=["tardy_id", "paid", "payment_date", "payment_method", "payment_notes"])
    else:
        agg = (
            pays.sort_values(["payment_date", "payment_id"])
            .groupby("tardy_id")
            .agg(
                paid=("amount", "sum"),
                payment_date=("payment_date", "max"),
                payment_method=("method", lambda s: ", ".join(dict.fromkeys(s))),
                payment_notes=("notes", lambda s: " | ".join(x for x in s if isinstance(x, str) and x)),
            )
            .reset_index()
        )
    df = df.merge(agg, how="left", left_on="id", right_on="tardy_id").drop(columns=["tardy_id"])
    df["paid"] = df["paid"].fillna(0.0).astype(float)
    df["payment_date"] = pd.to_datetime(df["payment_date"])
    df["balance"] = (df["penalty"] - df["paid"]).clip(lower=0)
    df.loc[df["status"] != db.STATUS_PENDING, "balance"] = 0.0
    df["month"] = df["activity_date"].dt.to_period("M")
    return df
