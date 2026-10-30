"""Control de pagos y cobranzas.

Una deuda solo pasa a «Pagado» cuando el administrador registra un pago que
cubre la penalidad. Los pagos anulados se conservan en el historial.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import sqlalchemy as sa

import database as db
from config import PAYMENT_METHODS, now_lima, today_lima


class PaymentError(ValueError):
    pass


PAYMENT_COLUMNS = [
    "payment_id", "tardy_id", "payment_date", "amount", "method", "notes", "created_at",
    "voided", "void_reason", "volunteer_id", "volunteer", "activity", "activity_date", "penalty",
]


def _paid_total(conn: sa.Connection, tardy_id: int) -> tuple[Decimal, int]:
    row = conn.execute(
        sa.select(sa.func.coalesce(sa.func.sum(db.payments.c.amount), 0), sa.func.count())
        .where(db.payments.c.tardy_id == tardy_id, db.payments.c.voided == sa.false())
    ).one()
    return Decimal(str(row[0])), int(row[1])


def refresh_status(conn: sa.Connection, tardy_id: int) -> str:
    """Recalcula el estado según los pagos válidos registrados por el administrador."""
    tardy = conn.execute(
        sa.select(db.tardies.c.penalty, db.tardies.c.status).where(db.tardies.c.id == tardy_id)
    ).one()
    if tardy.status == db.STATUS_VOID:
        return tardy.status
    paid, count = _paid_total(conn, tardy_id)
    new_status = db.STATUS_PAID if count > 0 and paid >= Decimal(str(tardy.penalty)) else db.STATUS_PENDING
    if new_status != tardy.status:
        conn.execute(
            db.tardies.update().where(db.tardies.c.id == tardy_id).values(status=new_status, updated_at=now_lima())
        )
    return new_status


def balance(conn: sa.Connection, tardy_id: int) -> Decimal:
    penalty = Decimal(str(conn.execute(sa.select(db.tardies.c.penalty).where(db.tardies.c.id == tardy_id)).scalar_one()))
    paid, _ = _paid_total(conn, tardy_id)
    return max(penalty - paid, Decimal("0"))


def register_payment(
    tardy_id: int,
    payment_date: date,
    amount: float | Decimal,
    method: str,
    notes: str | None = None,
) -> str:
    """Registra un pago para una tardanza y devuelve el nuevo estado de la deuda."""
    with db.transaction() as conn:
        return _register_payment(conn, tardy_id, payment_date, amount, method, notes)


def register_payments(tardy_ids: list[int], payment_date: date, method: str, notes: str | None = None) -> int:
    """Paga el saldo completo de varias deudas a la vez (todo o nada)."""
    with db.transaction() as conn:
        for tardy_id in tardy_ids:
            _register_payment(conn, tardy_id, payment_date, balance(conn, tardy_id), method, notes)
    return len(tardy_ids)


def _register_payment(conn, tardy_id, payment_date, amount, method, notes) -> str:
    if method not in PAYMENT_METHODS:
        raise PaymentError("Selecciona un medio de pago válido.")
    if payment_date > today_lima():
        raise PaymentError("La fecha de pago no puede ser futura.")
    amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    if amount < 0:
        raise PaymentError("El monto no puede ser negativo.")
    tardy = conn.execute(
        sa.select(db.tardies.c.status, db.tardies.c.penalty).where(db.tardies.c.id == tardy_id)
    ).first()
    if tardy is None:
        raise PaymentError("La tardanza no existe.")
    if tardy.status == db.STATUS_VOID:
        raise PaymentError("No se puede pagar una tardanza anulada.")
    if tardy.status == db.STATUS_PAID:
        raise PaymentError("Esta deuda ya figura como pagada.")
    pending = balance(conn, tardy_id)
    if amount > pending:
        raise PaymentError(f"El monto (S/ {amount:.2f}) supera el saldo pendiente (S/ {pending:.2f}).")
    if amount == 0 and pending > 0:
        raise PaymentError("Ingresa un monto mayor a cero.")
    payment_id = conn.execute(
        db.payments.insert()
        .values(
            tardy_id=tardy_id,
            payment_date=payment_date,
            amount=amount,
            method=method,
            notes=(notes or "").strip() or None,
            created_at=now_lima(),
            voided=False,
        )
        .returning(db.payments.c.id)
    ).scalar_one()
    status = refresh_status(conn, tardy_id)
    db.log_change(
        conn, "pago", payment_id, "registrar",
        {"tardanza": tardy_id, "monto": amount, "medio": method, "fecha": payment_date, "estado_resultante": status},
    )
    return status


def void_payment(payment_id: int, reason: str) -> None:
    reason = (reason or "").strip()
    if not reason:
        raise PaymentError("Indica el motivo de la anulación.")
    with db.transaction() as conn:
        pay = conn.execute(sa.select(db.payments).where(db.payments.c.id == payment_id)).mappings().first()
        if not pay:
            raise PaymentError("El pago no existe.")
        if pay["voided"]:
            raise PaymentError("El pago ya estaba anulado.")
        conn.execute(
            db.payments.update()
            .where(db.payments.c.id == payment_id)
            .values(voided=True, void_reason=reason, voided_at=now_lima())
        )
        status = refresh_status(conn, pay["tardy_id"])
        db.log_change(
            conn, "pago", payment_id, "anular",
            {"tardanza": pay["tardy_id"], "monto": pay["amount"], "motivo": reason, "estado_resultante": status},
        )


def fetch_payments(include_voided: bool = False) -> pd.DataFrame:
    p, t, a, v = db.payments, db.tardies, db.activities, db.volunteers
    stmt = (
        sa.select(
            p.c.id.label("payment_id"), p.c.tardy_id, p.c.payment_date, p.c.amount, p.c.method, p.c.notes,
            p.c.created_at, p.c.voided, p.c.void_reason, t.c.volunteer_id, v.c.name.label("volunteer"),
            a.c.name.label("activity"), a.c.activity_date, t.c.penalty,
        )
        .select_from(p.join(t, p.c.tardy_id == t.c.id).join(a, t.c.activity_id == a.c.id).join(v, t.c.volunteer_id == v.c.id))
        .order_by(p.c.payment_date.desc(), p.c.id.desc())
    )
    if not include_voided:
        stmt = stmt.where(p.c.voided == sa.false())
    with db.get_engine().connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    df = pd.DataFrame(rows, columns=PAYMENT_COLUMNS)
    df["amount"] = df["amount"].astype(float)
    df["penalty"] = df["penalty"].astype(float)
    for col in ("payment_date", "activity_date"):
        df[col] = pd.to_datetime(df[col])
    df["voided"] = df["voided"].astype(bool)
    return df
