"""Reportes y descargas en Excel."""

import re

import streamlit as st

import excel_export
import payments
import reports
import tardiness
import ui
from config import today_lima

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
REPORT_TYPES = ["Actividad", "Mes", "Rango de fechas", "Voluntario", "Pagos pendientes", "Pagos realizados"]


def render():
    ui.header("Reportes y Excel", "Descarga la información en archivos Excel listos para compartir.")
    df = tardiness.fetch_records()
    pays = payments.fetch_payments()

    with st.container(border=True):
        st.markdown("**Todos los registros**")
        st.caption(f"{len(df)} tardanza(s) y {len(pays)} pago(s). Hojas: registro general, resumen por actividad, "
                   "resumen mensual, pagos pendientes e historial de pagos.")
        st.download_button(
            "Descargar todos los registros en Excel",
            data=excel_export.build_workbook(df, pays),
            file_name=excel_export.file_name("completo"),
            mime=XLSX, type="primary", icon=":material/download:", width="stretch",
        )

    if df.empty:
        return

    with st.container(border=True):
        st.markdown("**Reporte filtrado**")
        kind = st.segmented_control("Tipo de reporte", REPORT_TYPES, default="Actividad", key="rep_kind") or "Actividad"
        subset, suffix = _filtered(df, kind)
        if subset is None:
            return
        k = reports.kpis(subset)
        st.caption(f"{k['tardies']} registro(s) · penalidades {ui.money(k['generated'])} · "
                   f"recaudado {ui.money(k['collected'])} · pendiente {ui.money(k['pending'])}")
        if subset.empty:
            st.warning("No hay registros con ese filtro.")
            return
        with st.expander("Vista previa"):
            ui.table(ui.records_view(subset, ["Fecha actividad", "Actividad", "Voluntario", "Penalidad", "Estado",
                                              "Saldo", "Fecha de pago"]))
        st.download_button(
            "Descargar reporte filtrado",
            data=excel_export.build_workbook(subset, pays),
            file_name=excel_export.file_name(suffix),
            mime=XLSX, icon=":material/download:", width="stretch",
        )

    with st.container(border=True):
        st.markdown("**Copia de seguridad**")
        st.caption("Descarga todas las tablas (incluido el historial de cambios) en CSV y JSON. "
                   "Recomendado una vez al mes, además de los respaldos automáticos de Supabase.")
        st.download_button(
            "Descargar respaldo completo (.zip)",
            data=excel_export.backup_zip(),
            file_name=f"respaldo_tardanzas_{today_lima():%Y-%m-%d}.zip",
            mime="application/zip", icon=":material/backup:", width="stretch",
        )


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def _filtered(df, kind):
    if kind == "Actividad":
        acts = reports.activity_summary(df)
        labels = {f"{ui.fmt_date(r.Fecha)} · {r.Actividad}": r.activity_id for r in acts.itertuples()}
        choice = st.selectbox("Actividad", list(labels), index=None, placeholder="Elige una actividad")
        if not choice:
            return None, ""
        return df[df["activity_id"] == labels[choice]], "actividad-" + _slug(choice)
    if kind == "Mes":
        months = sorted(df["month"].unique(), reverse=True)
        month = st.selectbox("Mes", months, format_func=reports.month_label)
        return reports.filter_records(df, months=[month]), f"mes-{month}"
    if kind == "Rango de fechas":
        today = today_lima()
        rng = st.date_input("Rango de fechas de actividad", value=(today.replace(day=1), today), format="DD/MM/YYYY")
        if not (isinstance(rng, (list, tuple)) and len(rng) == 2):
            st.caption("Elige la fecha final del rango.")
            return None, ""
        return reports.filter_records(df, date_from=rng[0], date_to=rng[1]), f"{rng[0]:%Y%m%d}-{rng[1]:%Y%m%d}"
    if kind == "Voluntario":
        name = st.selectbox("Voluntario", sorted(df["volunteer"].unique()), index=None, placeholder="Busca un voluntario")
        if not name:
            return None, ""
        return reports.filter_records(df, volunteers=[name]), "voluntario-" + _slug(name)
    if kind == "Pagos pendientes":
        return reports.filter_records(df, status=["Pendiente"]), "pendientes"
    return reports.filter_records(df, status=["Pagado"]), "pagados"
