"""Gestión de voluntarios: alta, búsqueda y edición de nombres."""

from __future__ import annotations

import pandas as pd
import sqlalchemy as sa

import database as db
from config import now_lima


class VolunteerError(ValueError):
    pass


def list_volunteers() -> pd.DataFrame:
    with db.get_engine().connect() as conn:
        rows = conn.execute(sa.select(db.volunteers).order_by(db.volunteers.c.name)).mappings().all()
    return pd.DataFrame(rows, columns=["id", "name", "name_key", "created_at", "updated_at"])


def find_by_name(conn: sa.Connection, name: str):
    return conn.execute(
        sa.select(db.volunteers).where(db.volunteers.c.name_key == db.normalize_key(name))
    ).mappings().first()


def get_or_create(conn: sa.Connection, name: str) -> tuple[int, bool]:
    """Devuelve (id, creado). Reutiliza el voluntario si el nombre ya existe."""
    name = db.clean_name(name)
    if len(name) < 2:
        raise VolunteerError("Escribe un nombre válido (mínimo 2 caracteres).")
    existing = find_by_name(conn, name)
    if existing:
        return existing["id"], False
    now = now_lima()
    new_id = conn.execute(
        db.volunteers.insert()
        .values(name=name, name_key=db.normalize_key(name), created_at=now, updated_at=now)
        .returning(db.volunteers.c.id)
    ).scalar_one()
    db.log_change(conn, "voluntario", new_id, "crear", {"nombre": name})
    return new_id, True


def create_volunteer(name: str) -> tuple[int, bool]:
    with db.transaction() as conn:
        return get_or_create(conn, name)


def rename_volunteer(volunteer_id: int, new_name: str) -> None:
    new_name = db.clean_name(new_name)
    if len(new_name) < 2:
        raise VolunteerError("Escribe un nombre válido (mínimo 2 caracteres).")
    with db.transaction() as conn:
        current = conn.execute(
            sa.select(db.volunteers).where(db.volunteers.c.id == volunteer_id)
        ).mappings().first()
        if not current:
            raise VolunteerError("El voluntario no existe.")
        clash = find_by_name(conn, new_name)
        if clash and clash["id"] != volunteer_id:
            raise VolunteerError(f"Ya existe un voluntario llamado «{clash['name']}».")
        conn.execute(
            db.volunteers.update()
            .where(db.volunteers.c.id == volunteer_id)
            .values(name=new_name, name_key=db.normalize_key(new_name), updated_at=now_lima())
        )
        db.log_change(conn, "voluntario", volunteer_id, "renombrar", {"antes": current["name"], "despues": new_name})


def delete_volunteer(volunteer_id: int) -> None:
    """Solo permite eliminar voluntarios sin tardanzas (por ejemplo, creados por error)."""
    with db.transaction() as conn:
        used = conn.execute(
            sa.select(sa.func.count()).select_from(db.tardies).where(db.tardies.c.volunteer_id == volunteer_id)
        ).scalar_one()
        if used:
            raise VolunteerError("No se puede eliminar: el voluntario tiene tardanzas registradas.")
        name = conn.execute(sa.select(db.volunteers.c.name).where(db.volunteers.c.id == volunteer_id)).scalar()
        conn.execute(db.volunteers.delete().where(db.volunteers.c.id == volunteer_id))
        db.log_change(conn, "voluntario", volunteer_id, "eliminar", {"nombre": name})
