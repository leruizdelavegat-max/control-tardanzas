"""Filtros, indicadores y resúmenes calculados a partir de los registros."""

from __future__ import annotations

from datetime import date

import pandas as pd

MONTHS_ES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
             "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def month_label(period: pd.Period) -> str:
    return f"{MONTHS_ES[period.month - 1]} {period.year}"


def filter_records(
    df: pd.DataFrame,
    volunteers: list[str] | None = None,
    activities: list[str] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    months: list[pd.Period] | None = None,
    status: list[str] | None = None,
) -> pd.DataFrame:
    """Aplica los filtros indicados. Los filtros vacíos no restringen nada."""
    mask = pd.Series(True, index=df.index)
    if volunteers:
        mask &= df["volunteer"].isin(volunteers)
    if activities:
        mask &= df["activity"].isin(activities)
    if date_from:
        mask &= df["activity_date"] >= pd.Timestamp(date_from)
    if date_to:
        mask &= df["activity_date"] <= pd.Timestamp(date_to)
    if months:
        mask &= df["month"].isin(months)
    if status:
        mask &= df["status"].isin(status)
    return df[mask]


def kpis(df: pd.DataFrame) -> dict:
    generated = float(df["penalty"].sum())
    collected = float(df["paid"].sum())
    return {
        "tardies": int(len(df)),
        "volunteers": int(df["volunteer_id"].nunique()),
        "generated": generated,
        "collected": collected,
        "pending": float(df["balance"].sum()),
        "pending_count": int((df["status"] == "Pendiente").sum()),
        "collection_rate": (collected / generated * 100) if generated else 0.0,
    }


def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["month", "Mes", "Tardanzas", "Penalidades", "Recaudado", "Pendiente"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    out = (
        df.groupby("month")
        .agg(Tardanzas=("id", "count"), Penalidades=("penalty", "sum"), Recaudado=("paid", "sum"), Pendiente=("balance", "sum"))
        .reset_index()
        .sort_values("month")
    )
    out["Mes"] = out["month"].map(month_label)
    return out[cols]


def activity_summary(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["activity_id", "Fecha", "Actividad", "Hora de inicio", "Tardanzas", "Penalidades", "Recaudado", "Pendiente"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    out = (
        df.groupby(["activity_id", "activity_date", "activity", "start_time"])
        .agg(Tardanzas=("id", "count"), Penalidades=("penalty", "sum"), Recaudado=("paid", "sum"), Pendiente=("balance", "sum"))
        .reset_index()
        .rename(columns={"activity_date": "Fecha", "activity": "Actividad", "start_time": "Hora de inicio"})
        .sort_values(["Fecha", "Actividad"], ascending=[False, True])
    )
    return out[cols]


def volunteer_summary(df: pd.DataFrame, all_volunteers: pd.DataFrame | None = None) -> pd.DataFrame:
    """Totales por voluntario. Si se pasa la lista completa, incluye a quienes no tienen tardanzas."""
    agg = (
        df.groupby(["volunteer_id", "volunteer"])
        .agg(Tardanzas=("id", "count"), Total=("penalty", "sum"), Pagado=("paid", "sum"),
             Pendiente=("balance", "sum"), Ultima=("activity_date", "max"))
        .reset_index()
    )
    if all_volunteers is not None:
        base = all_volunteers[["id", "name"]].rename(columns={"id": "volunteer_id", "name": "volunteer"})
        agg = base.merge(agg.drop(columns=["volunteer"]), on="volunteer_id", how="left")
        for col in ("Tardanzas", "Total", "Pagado", "Pendiente"):
            agg[col] = agg[col].fillna(0)
        agg["Tardanzas"] = agg["Tardanzas"].astype(int)
    return agg.sort_values(["Pendiente", "Tardanzas"], ascending=False).reset_index(drop=True)
