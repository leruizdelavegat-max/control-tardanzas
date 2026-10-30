"""Componentes visuales compartidos: estilos, formatos, tablas y filtros."""

from __future__ import annotations

from datetime import date, time

import pandas as pd
import streamlit as st

import reports
from config import CURRENCY, today_lima

PAID_COLOR = "#15803D"
PENDING_COLOR = "#C2410C"
PRIMARY = "#0F766E"

CSS = """
<style>
.block-container {padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1150px;}
h1 {font-size: 1.7rem !important; font-weight: 700 !important; margin-bottom: 0 !important;}
.page-sub {color: #64748B; margin: 0 0 1rem 0; font-size: .95rem;}
div[data-testid="stMetricValue"] {font-size: 1.45rem;}
.pill {display:inline-block; padding: .15rem .6rem; border-radius: 999px; font-size: .82rem; font-weight: 600;}
.pill-pending {background:#FFF1E7; color:#C2410C;}
.pill-paid {background:#E7F6EC; color:#15803D;}
.pill-neutral {background:#EEF2F6; color:#334155;}
.calc-box {border-radius: 10px; padding: .75rem 1rem; margin: .3rem 0 .6rem 0; background:#F1F5F9;}
.calc-box b {font-size: 1.25rem;}
.activity-card {border-left: 4px solid #0F766E; background:#F0FDFA; border-radius: 8px;
                padding: .7rem 1rem; margin-bottom: .8rem;}
.activity-card .t {font-weight: 700; font-size: 1.05rem;}
.activity-card .s {color:#475569; font-size: .9rem;}
@media (max-width: 640px) {
  .block-container {padding-left: .8rem; padding-right: .8rem; padding-top: 1.2rem;}
  h1 {font-size: 1.35rem !important;}
  div[data-testid="stMetricValue"] {font-size: 1.2rem;}
}
</style>
"""


# Páginas registradas por app.py (url_path → st.Page), para navegar con botones.
PAGES: dict = {}


def go(url_path: str) -> None:
    st.switch_page(PAGES[url_path])


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str | None = None) -> None:
    st.title(title)
    if subtitle:
        st.markdown(f"<p class='page-sub'>{subtitle}</p>", unsafe_allow_html=True)


def money(value: float) -> str:
    return f"{CURRENCY} {value:,.2f}"


def fmt_date(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return pd.Timestamp(value).strftime("%d/%m/%Y")


def fmt_time(value: time | None) -> str:
    if value is None or (not isinstance(value, time) and pd.isna(value)):
        return "—"
    suffix = "a. m." if value.hour < 12 else "p. m."
    return f"{value.hour % 12 or 12}:{value.minute:02d} {suffix}"


def status_pill(status: str) -> str:
    css = {"Pagado": "pill-paid", "Pendiente": "pill-pending"}.get(status, "pill-neutral")
    return f"<span class='pill {css}'>{status}</span>"


SELECTABLE_TABLES = ("hist_table", "act_table", "pend_table", "payhist", "vol_table")


def flash(kind: str, message: str) -> None:
    """Guarda un mensaje para mostrarlo después de st.rerun().

    Se usa tras cada cambio guardado, así que también limpia las filas seleccionadas:
    con los datos ya modificados, una selección antigua apuntaría a otro registro."""
    st.session_state["_flash"] = (kind, message)
    for key in SELECTABLE_TABLES:
        st.session_state.pop(key, None)


def show_flash() -> None:
    item = st.session_state.pop("_flash", None)
    if item:
        kind, message = item
        getattr(st, kind)(message)


# ----------------------------------------------------------------- tablas

COLUMN_CONFIG = {
    "Fecha actividad": st.column_config.DateColumn(format="DD/MM/YYYY"),
    "Fecha": st.column_config.DateColumn(format="DD/MM/YYYY"),
    "Fecha de pago": st.column_config.DateColumn(format="DD/MM/YYYY"),
    "Fecha registro": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
    "Registrado el": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
    "Última tardanza": st.column_config.DateColumn(format="DD/MM/YYYY"),
    "Inicio": st.column_config.TimeColumn(format="h:mm a"),
    "Hora de inicio": st.column_config.TimeColumn(format="h:mm a"),
    "Llegada": st.column_config.TimeColumn(format="h:mm a"),
    "Retraso (min)": st.column_config.NumberColumn(format="%d"),
    "Penalidad": st.column_config.NumberColumn(format="S/ %.2f"),
    "Penalidades": st.column_config.NumberColumn(format="S/ %.2f"),
    "Pagado": st.column_config.NumberColumn(format="S/ %.2f"),
    "Saldo": st.column_config.NumberColumn(format="S/ %.2f"),
    "Total": st.column_config.NumberColumn(format="S/ %.2f"),
    "Recaudado": st.column_config.NumberColumn(format="S/ %.2f"),
    "Pendiente": st.column_config.NumberColumn(format="S/ %.2f"),
    "Monto": st.column_config.NumberColumn(format="S/ %.2f"),
    "Observaciones": st.column_config.TextColumn(width="medium"),
}


def records_view(df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    """Convierte los registros internos a columnas en español para mostrar."""
    view = pd.DataFrame({
        "Fecha actividad": df["activity_date"],
        "Actividad": df["activity"],
        "Voluntario": df["volunteer"],
        "Inicio": df["start_time"],
        "Llegada": df["arrival_time"],
        "Retraso (min)": df["delay_minutes"],
        "Penalidad": df["penalty"],
        "Estado": df["status"],
        "Pagado": df["paid"],
        "Saldo": df["balance"],
        "Fecha registro": df["registered_at"],
        "Fecha de pago": df["payment_date"],
        "Medio de pago": df["payment_method"],
        "Observaciones": df["notes"],
    })
    if columns:
        view = view[columns]
    return view.reset_index(drop=True)


def _status_style(value) -> str:
    if value == "Pagado":
        return f"color: {PAID_COLOR}; font-weight: 600"
    if value == "Pendiente":
        return f"color: {PENDING_COLOR}; font-weight: 600"
    return ""


def table(view: pd.DataFrame, key: str | None = None, selection: str | None = None, height: int | str = "auto"):
    """Muestra una tabla con formato. ``selection`` puede ser 'single-row' o 'multi-row'."""
    data = view.style.map(_status_style, subset=["Estado"]) if "Estado" in view.columns else view
    kwargs = dict(hide_index=True, column_config=COLUMN_CONFIG, width="stretch", height=height)
    if selection:
        return st.dataframe(data, key=key, on_select="rerun", selection_mode=selection, **kwargs)
    st.dataframe(data, key=key, **kwargs)
    return None


def selected_rows(event, n_rows: int) -> list[int]:
    if event is None:
        return []
    return [r for r in event.selection.rows if r < n_rows]


# ---------------------------------------------------------------- filtros


def record_filters(df: pd.DataFrame, key: str, show_status: bool = True, expanded: bool = False) -> pd.DataFrame:
    """Panel de filtros reutilizable: voluntario, actividad, fecha, rango, mes y estado."""
    active = sum(
        bool(st.session_state.get(f"{key}_{name}"))
        for name in ("vol", "act", "status")
    ) + (st.session_state.get(f"{key}_mode", "Todas") != "Todas")
    label = "Filtros" + (f" · {active} activo(s)" if active else "")
    with st.expander(label, icon=":material/filter_list:", expanded=expanded):
        c1, c2 = st.columns(2)
        vols = c1.multiselect("Voluntario", sorted(df["volunteer"].unique()), key=f"{key}_vol",
                              placeholder="Todos")
        acts = c2.multiselect("Actividad", sorted(df["activity"].unique()), key=f"{key}_act",
                              placeholder="Todas")
        mode = st.segmented_control(
            "Fechas", ["Todas", "Fecha específica", "Rango", "Mes"], default="Todas", key=f"{key}_mode"
        ) or "Todas"
        date_from = date_to = None
        months = None
        if mode == "Fecha específica":
            day = st.date_input("Fecha de actividad", value=today_lima(), format="DD/MM/YYYY", key=f"{key}_day")
            date_from = date_to = day
        elif mode == "Rango":
            today = today_lima()
            rng = st.date_input("Rango de fechas", value=(today.replace(day=1), today), format="DD/MM/YYYY",
                                key=f"{key}_range")
            if isinstance(rng, (list, tuple)) and len(rng) == 2:
                date_from, date_to = rng
            elif isinstance(rng, (list, tuple)) and len(rng) == 1:
                date_from = rng[0]
        elif mode == "Mes":
            options = sorted(df["month"].dropna().unique(), reverse=True)
            months = st.multiselect("Mes", options, format_func=reports.month_label, key=f"{key}_months",
                                    placeholder="Elige uno o más meses") or None
        status = None
        if show_status:
            status = st.pills("Estado del pago", ["Pendiente", "Pagado"], selection_mode="multi", key=f"{key}_status")
    return reports.filter_records(df, vols, acts, date_from, date_to, months, status)


def period_filter(df: pd.DataFrame, key: str) -> tuple[pd.DataFrame, str]:
    """Selector rápido de periodo para el panel principal."""
    today = today_lima()
    choice = st.segmented_control(
        "Periodo", ["Todo", "Este mes", "Últimos 3 meses", "Este año", "Personalizado"],
        default="Todo", key=key, label_visibility="collapsed",
    ) or "Todo"
    start = end = None
    if choice == "Este mes":
        start = today.replace(day=1)
    elif choice == "Últimos 3 meses":
        start = (pd.Timestamp(today.replace(day=1)) - pd.DateOffset(months=2)).date()
    elif choice == "Este año":
        start = date(today.year, 1, 1)
    elif choice == "Personalizado":
        rng = st.date_input("Rango", value=(today.replace(day=1), today), format="DD/MM/YYYY", key=f"{key}_rng")
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            start, end = rng
    return reports.filter_records(df, date_from=start, date_to=end), choice
