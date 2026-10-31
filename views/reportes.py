"""Reportes y descargas en Excel y PDF."""

import re

import streamlit as st

import excel_export
import payments
import pdf_export
import reports
import tardiness
import ui
from config import get_settings, today_lima
from views.historial import date_label, date_options

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
REPORT_TYPES = ["Fecha", "Actividad", "Mes", "Rango de fechas", "Voluntario", "Pagos pendientes", "Pagos realizados"]


def render():
    ui.header("Reportes y Excel", "Consulta y descarga la información en Excel o PDF.")
    df = tardiness.fetch_records()
    pays = payments.fetch_payments()
    org = get_settings()["org_name"]

    if not df.empty:
        with st.container(border=True):
            st.markdown("**Consultar y descargar**")
            kind = st.segmented_control("Tipo de reporte", REPORT_TYPES, default="Fecha", key="rep_kind") or "Fecha"
            subset, suffix, description = _filtered(df, kind)
            if subset is not None:
                _show_and_download(subset, pays, suffix, description, org)

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
        if not df.empty:
            st.download_button(
                "Descargar todos los registros en PDF",
                data=pdf_export.build_pdf(df, "Historial de tardanzas", "Todos los registros", org),
                file_name=excel_export.file_name("completo").replace(".xlsx", ".pdf"),
                mime="application/pdf", icon=":material/picture_as_pdf:", width="stretch",
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


def _show_and_download(subset, pays, suffix, description, org):
    k = reports.kpis(subset)
    if subset.empty:
        st.warning("No hay registros con ese filtro.")
        return
    c = st.columns(3)
    c[0].metric("Tardanzas", k["tardies"])
    c[1].metric("Total de deuda", ui.money(k["generated"]))
    c[2].metric("Pendiente", ui.money(k["pending"]))
    ui.table(ui.records_view(subset, ["Fecha actividad", "Actividad", "Voluntario", "Llegada", "Penalidad",
                                      "Estado", "Fecha de pago", "Medio de pago"]), height=min(420, 38 + 35 * len(subset)))
    c1, c2 = st.columns(2)
    name = excel_export.file_name(suffix)
    c1.download_button("Descargar Excel", data=excel_export.build_workbook(subset, pays), file_name=name,
                       mime=XLSX, icon=":material/table_view:", width="stretch", type="primary")
    c2.download_button("Descargar PDF",
                       data=pdf_export.build_pdf(subset, "Reporte de tardanzas", description, org),
                       file_name=name.replace(".xlsx", ".pdf"), mime="application/pdf",
                       icon=":material/picture_as_pdf:", width="stretch", type="primary")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def _filtered(df, kind):
    """Devuelve (registros, sufijo de archivo, descripción) o (None, "", "") si falta elegir algo."""
    if kind == "Fecha":
        day = st.selectbox("Fecha de actividad", date_options(df), format_func=lambda d: date_label(df, d),
                           key="rep_day")
        return df[df["activity_date"].dt.date == day], f"{day:%Y-%m-%d}", f"Fecha de actividad: {ui.fmt_date(day)}"
    if kind == "Actividad":
        acts = reports.activity_summary(df)
        labels = {f"{ui.fmt_date(r.Fecha)} · {r.Actividad}": r.activity_id for r in acts.itertuples()}
        choice = st.selectbox("Actividad", list(labels), index=None, placeholder="Elige una actividad")
        if not choice:
            return None, "", ""
        return df[df["activity_id"] == labels[choice]], "actividad-" + _slug(choice), f"Actividad: {choice}"
    if kind == "Mes":
        months = sorted(df["month"].unique(), reverse=True)
        month = st.selectbox("Mes", months, format_func=reports.month_label)
        return reports.filter_records(df, months=[month]), f"mes-{month}", f"Mes: {reports.month_label(month)}"
    if kind == "Rango de fechas":
        today = today_lima()
        rng = st.date_input("Rango de fechas de actividad", value=(today.replace(day=1), today), format="DD/MM/YYYY")
        if not (isinstance(rng, (list, tuple)) and len(rng) == 2):
            st.caption("Elige la fecha final del rango.")
            return None, "", ""
        return (reports.filter_records(df, date_from=rng[0], date_to=rng[1]), f"{rng[0]:%Y%m%d}-{rng[1]:%Y%m%d}",
                f"Del {ui.fmt_date(rng[0])} al {ui.fmt_date(rng[1])}")
    if kind == "Voluntario":
        name = st.selectbox("Voluntario", sorted(df["volunteer"].unique()), index=None, placeholder="Busca un voluntario")
        if not name:
            return None, "", ""
        return reports.filter_records(df, volunteers=[name]), "voluntario-" + _slug(name), f"Voluntario: {name}"
    if kind == "Pagos pendientes":
        return reports.filter_records(df, status=["Pendiente"]), "pendientes", "Deudas pendientes"
    return reports.filter_records(df, status=["Pagado"]), "pagados", "Deudas pagadas"
