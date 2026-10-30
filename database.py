"""Conexión a la base de datos, definición de tablas y utilidades comunes.

La aplicación usa PostgreSQL (Supabase) en producción. Para pruebas locales
también funciona con SQLite (por ejemplo ``DATABASE_URL=sqlite:///local.db``).
"""

from __future__ import annotations

import json
import os
import unicodedata
import warnings
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

import sqlalchemy as sa
from sqlalchemy import exc as sa_exc

from config import now_lima

# SQLite no maneja Decimal de forma nativa; solo se usa para pruebas locales.
warnings.filterwarnings("ignore", message=".*does \\*not\\* support Decimal objects natively.*")

metadata = sa.MetaData()

STATUS_PENDING = "Pendiente"
STATUS_PAID = "Pagado"
STATUS_VOID = "Anulado"

volunteers = sa.Table(
    "volunteers",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("name", sa.String(120), nullable=False),
    # Nombre normalizado (minúsculas, sin tildes ni espacios dobles) para evitar duplicados.
    sa.Column("name_key", sa.String(120), nullable=False, unique=True),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.Column("updated_at", sa.DateTime, nullable=False),
)

activities = sa.Table(
    "activities",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("name", sa.String(150), nullable=False),
    sa.Column("name_key", sa.String(150), nullable=False),
    sa.Column("activity_date", sa.Date, nullable=False),
    sa.Column("start_time", sa.Time, nullable=False),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.UniqueConstraint("name_key", "activity_date", name="uq_activity_name_date"),
)

tardies = sa.Table(
    "tardies",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("activity_id", sa.Integer, sa.ForeignKey("activities.id"), nullable=False),
    sa.Column("volunteer_id", sa.Integer, sa.ForeignKey("volunteers.id"), nullable=False),
    # Copia de la hora de inicio y de las reglas vigentes al registrar: así los
    # cambios de configuración no alteran los registros históricos.
    sa.Column("start_time", sa.Time, nullable=False),
    sa.Column("arrival_time", sa.Time, nullable=False),
    sa.Column("delay_minutes", sa.Integer, nullable=False),
    sa.Column("penalty", sa.Numeric(10, 2), nullable=False),
    sa.Column("rules_snapshot", sa.Text, nullable=False),
    sa.Column("status", sa.String(20), nullable=False, default=STATUS_PENDING),
    sa.Column("notes", sa.Text),
    sa.Column("registered_at", sa.DateTime, nullable=False),
    sa.Column("updated_at", sa.DateTime, nullable=False),
    sa.Column("void_reason", sa.Text),
    # Token único por envío del formulario: evita duplicados por doble clic o reintentos.
    sa.Column("client_token", sa.String(64), unique=True),
)

# Un voluntario solo puede tener una tardanza vigente por actividad.
sa.Index(
    "uq_tardy_activity_volunteer_active",
    tardies.c.activity_id,
    tardies.c.volunteer_id,
    unique=True,
    postgresql_where=tardies.c.status != STATUS_VOID,
    sqlite_where=tardies.c.status != STATUS_VOID,
)

payments = sa.Table(
    "payments",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("tardy_id", sa.Integer, sa.ForeignKey("tardies.id"), nullable=False, index=True),
    sa.Column("payment_date", sa.Date, nullable=False),
    sa.Column("amount", sa.Numeric(10, 2), nullable=False),
    sa.Column("method", sa.String(30), nullable=False),
    sa.Column("notes", sa.Text),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.Column("voided", sa.Boolean, nullable=False, default=False),
    sa.Column("void_reason", sa.Text),
    sa.Column("voided_at", sa.DateTime),
)

settings = sa.Table(
    "settings",
    metadata,
    sa.Column("key", sa.String(60), primary_key=True),
    sa.Column("value", sa.Text, nullable=False),
    sa.Column("updated_at", sa.DateTime, nullable=False),
)

audit_log = sa.Table(
    "audit_log",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.Column("entity", sa.String(30), nullable=False),
    sa.Column("entity_id", sa.Integer),
    sa.Column("action", sa.String(30), nullable=False),
    sa.Column("details", sa.Text),
)


class DatabaseConfigError(RuntimeError):
    """No se encontró la cadena de conexión a la base de datos."""


def _read_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        try:
            import streamlit as st

            url = st.secrets.get("DATABASE_URL") or st.secrets.get("database", {}).get("url")
        except Exception:
            url = None
    if not url:
        raise DatabaseConfigError(
            "Falta DATABASE_URL. Configúrala en .streamlit/secrets.toml o como variable de entorno."
        )
    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


@lru_cache(maxsize=4)
def _engine_for(url: str) -> sa.Engine:
    if url.startswith("sqlite"):
        engine = sa.create_engine(url, connect_args={"check_same_thread": False})

        @sa.event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # pragma: no cover - configuración de SQLite
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    else:
        engine = sa.create_engine(
            url,
            pool_pre_ping=True,
            pool_size=3,
            max_overflow=2,
            pool_recycle=300,
            connect_args={"connect_timeout": 10},
        )
    metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        # En Supabase, sin RLS las tablas quedarían expuestas por su API pública (clave anon).
        # La app se conecta como dueña de las tablas, así que RLS no la afecta.
        with engine.begin() as conn:
            for table in metadata.sorted_tables:
                conn.execute(sa.text(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY'))
    return engine


def get_engine() -> sa.Engine:
    return _engine_for(_read_database_url())


@contextmanager
def transaction() -> Iterator[sa.Connection]:
    """Abre una transacción: o se guarda todo, o no se guarda nada."""
    with get_engine().begin() as conn:
        yield conn


def normalize_key(text: str) -> str:
    """Normaliza nombres para comparar: sin tildes, minúsculas y espacios simples."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().split())


def clean_name(text: str) -> str:
    return " ".join((text or "").split())


def log_change(conn: sa.Connection, entity: str, entity_id: int | None, action: str, details: Any = None) -> None:
    """Registra un cambio en el historial de auditoría (dentro de la misma transacción)."""
    conn.execute(
        audit_log.insert().values(
            created_at=now_lima(),
            entity=entity,
            entity_id=entity_id,
            action=action,
            details=json.dumps(details, ensure_ascii=False, default=str) if details is not None else None,
        )
    )


IntegrityError = sa_exc.IntegrityError
OperationalError = sa_exc.OperationalError
