"""Panel principal: indicadores y gráficos."""

import altair as alt
import pandas as pd
import streamlit as st

import reports
import tardiness
import ui
from config import get_settings


def render():
    settings = get_settings()
    ui.header("Inicio", f"Resumen de tardanzas y cobranzas · {settings['org_name']}")

    c1, c2 = st.columns(2)
    if c1.button("Registrar tardanza", icon=":material/alarm_add:", type="primary", width="stretch"):
        ui.go("registrar")
    if c2.button("Registrar un pago", icon=":material/payments:", width="stretch"):
        ui.go("pagos")

    df = tardiness.fetch_records()
    if df.empty:
        st.info("Todavía no hay tardanzas registradas. Empieza en **Registrar tardanza**.")
        return

    df, period = ui.period_filter(df, "home_period")
    k = reports.kpis(df)
    r1 = st.columns(3)
    r1[0].metric("Tardanzas", k["tardies"], border=True)
    r1[1].metric("Voluntarios con tardanzas", k["volunteers"], border=True)
    r1[2].metric("Penalidades generadas", ui.money(k["generated"]), border=True)
    r2 = st.columns(3)
    r2[0].metric("Total recaudado", ui.money(k["collected"]), border=True)
    r2[1].metric("Pendiente de cobro", ui.money(k["pending"]), border=True)
    r2[2].metric("Cobranza", f"{k['collection_rate']:.0f} %", border=True)

    if df.empty:
        st.info("No hay registros en el periodo seleccionado.")
        return

    tab1, tab2, tab3, tab4 = st.tabs(["Evolución mensual", "Pagado vs. pendiente", "Voluntarios", "Actividades"])
    monthly = reports.monthly_summary(df)
    order = monthly["Mes"].tolist()

    with tab1:
        a, b = st.columns(2)
        a.altair_chart(_bar(monthly, "Mes", "Tardanzas", "Tardanzas por mes", order), width="stretch")
        b.altair_chart(_bar(monthly, "Mes", "Penalidades", "Penalidades generadas (S/)", order, money=True),
                       width="stretch")

    with tab2:
        long = monthly.melt(id_vars="Mes", value_vars=["Recaudado", "Pendiente"], var_name="Estado", value_name="Monto")
        chart = (
            alt.Chart(long, title="Montos pagados y pendientes por mes (S/)")
            .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(
                x=alt.X("Mes:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("Monto:Q", title=None, stack=True),
                color=alt.Color("Estado:N", scale=alt.Scale(domain=["Recaudado", "Pendiente"],
                                                            range=[ui.PAID_COLOR, ui.PENDING_COLOR]),
                                legend=alt.Legend(orient="top", title=None)),
                tooltip=["Mes", "Estado", alt.Tooltip("Monto:Q", format=",.2f")],
            )
            .properties(height=300)
        )
        st.altair_chart(chart, width="stretch")

    with tab3:
        top = reports.volunteer_summary(df).sort_values("Tardanzas", ascending=False).head(10)
        st.altair_chart(_hbar(top, "volunteer", "Tardanzas", "Voluntarios con más tardanzas"), width="stretch")

    with tab4:
        acts = (
            df.groupby("activity").agg(Penalidades=("penalty", "sum"), Tardanzas=("id", "count")).reset_index()
            .sort_values("Penalidades", ascending=False).head(10)
        )
        st.altair_chart(_hbar(acts, "activity", "Penalidades", "Actividades con mayores penalidades (S/)", money=True),
                        width="stretch")


def _bar(data: pd.DataFrame, x: str, y: str, title: str, order: list[str], money: bool = False):
    fmt = ",.2f" if money else "d"
    return (
        alt.Chart(data, title=title)
        .mark_bar(color=ui.PRIMARY, cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X(f"{x}:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y(f"{y}:Q", title=None),
            tooltip=[x, alt.Tooltip(f"{y}:Q", format=fmt)],
        )
        .properties(height=280)
    )


def _hbar(data: pd.DataFrame, label: str, value: str, title: str, money: bool = False):
    fmt = ",.2f" if money else "d"
    return (
        alt.Chart(data, title=title)
        .mark_bar(color=ui.PRIMARY, cornerRadiusTopRight=3, cornerRadiusBottomRight=3)
        .encode(
            y=alt.Y(f"{label}:N", sort="-x", title=None),
            x=alt.X(f"{value}:Q", title=None),
            tooltip=[alt.Tooltip(f"{label}:N", title="Nombre"), alt.Tooltip(f"{value}:Q", format=fmt)],
        )
        .properties(height=max(160, 32 * len(data)))
    )
