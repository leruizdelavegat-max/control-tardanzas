"""Historial de tardanzas: listado general, detalle por actividad y por voluntario."""

import streamlit as st

import reports
import tardiness
import ui
from config import today_lima


def render():
    ui.header("Historial de actividades", "Consulta, corrige o anula tardanzas registradas.")
    ui.show_flash()
    df = tardiness.fetch_records()
    if df.empty:
        st.info("Todavía no hay tardanzas registradas.")
        return

    tab_all, tab_act, tab_vol = st.tabs(["Todas las tardanzas", "Por actividad", "Por voluntario"])
    with tab_all:
        _all_records(df)
    with tab_act:
        _by_activity(df)
    with tab_vol:
        _by_volunteer(df)


def _all_records(df):
    fdf = ui.record_filters(df, "hist").reset_index(drop=True)
    k = reports.kpis(fdf)
    st.caption(f"{k['tardies']} registro(s) · penalidades {ui.money(k['generated'])} · "
               f"pendiente {ui.money(k['pending'])}")
    event = ui.table(ui.records_view(fdf), key="hist_table", selection="single-row")
    rows = ui.selected_rows(event, len(fdf))
    if not rows:
        st.caption(":material/touch_app: Selecciona una fila para corregirla o anularla.")
        return
    _edit_panel(fdf.iloc[rows[0]])


def _edit_panel(row):
    with st.container(border=True):
        st.markdown(f"**{row['volunteer']}** · {row['activity']} · {ui.fmt_date(row['activity_date'])}  \n"
                    f"Llegada {ui.fmt_time(row['arrival_time'])} · {row['delay_minutes']} min · "
                    f"{ui.money(row['penalty'])} · {ui.status_pill(row['status'])}", unsafe_allow_html=True)
        fix, void = st.tabs(["Corregir", "Anular"])
        with fix:
            with st.form(f"edit_{row['id']}"):
                arrival = st.time_input("Hora de llegada", value=row["arrival_time"], step=60)
                notes = st.text_input("Observaciones", value=row["notes"] or "")
                reason = st.text_input("Motivo de la corrección *")
                ok = st.form_submit_button("Guardar corrección", type="primary")
            st.caption("La penalidad se recalcula con las reglas que tenía este registro al crearse.")
            if ok:
                try:
                    tardiness.update_tardy(int(row["id"]), arrival, notes, reason)
                except tardiness.TardyError as exc:
                    st.error(str(exc))
                else:
                    ui.flash("success", "Registro corregido. El cambio quedó en el historial de cambios.")
                    st.rerun()
        with void:
            with st.form(f"void_{row['id']}"):
                reason = st.text_input("Motivo de la anulación *")
                ok = st.form_submit_button("Anular registro", type="primary")
            st.caption("El registro no se borra: queda anulado y deja de contar en deudas y reportes.")
            if ok:
                try:
                    tardiness.void_tardy(int(row["id"]), reason)
                except tardiness.TardyError as exc:
                    st.error(str(exc))
                else:
                    ui.flash("success", "Registro anulado.")
                    st.rerun()


def _by_activity(df):
    summary = reports.activity_summary(df).reset_index(drop=True)
    event = ui.table(summary.drop(columns=["activity_id"]), key="act_table", selection="single-row")
    rows = ui.selected_rows(event, len(summary))
    if not rows:
        st.caption(":material/touch_app: Selecciona una actividad para ver su detalle.")
        return
    act = summary.iloc[rows[0]]
    detail = df[df["activity_id"] == act["activity_id"]].sort_values("arrival_time")
    with st.container(border=True):
        st.markdown(f"#### {act['Actividad']}")
        st.caption(f"{ui.fmt_date(act['Fecha'])} · inicio {ui.fmt_time(act['Hora de inicio'])}")
        c = st.columns(3)
        c[0].metric("Llegaron tarde", len(detail))
        c[1].metric("Total penalidades", ui.money(detail["penalty"].sum()))
        c[2].metric("Pendiente", ui.money(detail["balance"].sum()))
        ui.table(ui.records_view(detail, ["Voluntario", "Llegada", "Retraso (min)", "Penalidad", "Estado",
                                          "Pagado", "Fecha de pago", "Medio de pago"]))
        with st.expander("Corregir datos de la actividad", icon=":material/edit:"):
            info = tardiness.get_activity(int(act["activity_id"]))
            with st.form(f"act_edit_{info['id']}"):
                name = st.text_input("Nombre", value=info["name"])
                c1, c2 = st.columns(2)
                day = c1.date_input("Fecha", value=info["activity_date"], max_value=today_lima(), format="DD/MM/YYYY")
                start = c2.time_input("Hora de inicio", value=info["start_time"], step=60)
                ok = st.form_submit_button("Guardar cambios", type="primary")
            st.caption("Si cambias la hora de inicio se recalcula el retraso de cada persona con sus reglas originales.")
            if ok:
                try:
                    n = tardiness.update_activity(info["id"], name, day, start)
                except tardiness.TardyError as exc:
                    st.error(str(exc))
                else:
                    ui.flash("success", "Actividad actualizada" + (f"; {n} tardanza(s) recalculadas." if n else "."))
                    st.rerun()


def _by_volunteer(df):
    names = sorted(df["volunteer"].unique())
    name = st.selectbox("Voluntario", names, index=None, placeholder="Busca un voluntario", key="hist_by_volunteer")
    if not name:
        return
    vdf = df[df["volunteer"] == name]
    k = reports.kpis(vdf)
    c = st.columns(4)
    c[0].metric("Tardanzas", k["tardies"])
    c[1].metric("Total", ui.money(k["generated"]))
    c[2].metric("Pagado", ui.money(k["collected"]))
    c[3].metric("Pendiente", ui.money(k["pending"]))
    ui.table(ui.records_view(vdf, ["Fecha actividad", "Actividad", "Llegada", "Retraso (min)", "Penalidad", "Estado",
                                   "Fecha de pago", "Medio de pago"]))
