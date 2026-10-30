"""Gestión de voluntarios."""

import streamlit as st

import reports
import tardiness
import ui
import volunteers
from volunteers import VolunteerError


def render():
    ui.header("Voluntarios", "Solo se registran las personas que llegaron tarde alguna vez (o que agregues aquí).")
    ui.show_flash()

    with st.expander("Agregar voluntario", icon=":material/person_add:"):
        with st.form("new_vol", clear_on_submit=True):
            name = st.text_input("Nombre completo")
            ok = st.form_submit_button("Agregar", type="primary")
        if ok:
            try:
                _, created = volunteers.create_volunteer(name)
            except VolunteerError as exc:
                st.error(str(exc))
            else:
                if created:
                    ui.flash("success", f"Voluntario «{name.strip()}» agregado.")
                else:
                    ui.flash("info", f"«{name.strip()}» ya estaba registrado.")
                st.rerun()

    vols = volunteers.list_volunteers()
    if vols.empty:
        st.info("Aún no hay voluntarios. Se agregan automáticamente al registrar una tardanza.")
        return
    df = tardiness.fetch_records()
    summary = reports.volunteer_summary(df, vols)

    search = st.text_input("Buscar voluntario", placeholder="Escribe parte del nombre", key="vol_search")
    if search:
        summary = summary[summary["volunteer"].str.contains(search.strip(), case=False, regex=False)]
    summary = summary.sort_values("volunteer").reset_index(drop=True)
    view = summary.rename(columns={"volunteer": "Voluntario", "Ultima": "Última tardanza"})
    st.caption(f"{len(view)} voluntario(s). Selecciona uno para ver su detalle.")
    event = ui.table(view[["Voluntario", "Tardanzas", "Total", "Pagado", "Pendiente", "Última tardanza"]],
                     key="vol_table", selection="single-row")
    rows = ui.selected_rows(event, len(summary))
    if rows:
        _detail(summary.iloc[rows[0]], df)


def _detail(row, df):
    vid = int(row["volunteer_id"])
    vdf = df[df["volunteer_id"] == vid]
    with st.container(border=True):
        st.markdown(f"#### {row['volunteer']}")
        c = st.columns(4)
        c[0].metric("Tardanzas", int(row["Tardanzas"]))
        c[1].metric("Total generado", ui.money(row["Total"]))
        c[2].metric("Pagado", ui.money(row["Pagado"]))
        c[3].metric("Pendiente", ui.money(row["Pendiente"]))
        if vdf.empty:
            st.caption("Sin tardanzas registradas.")
        else:
            ui.table(ui.records_view(vdf, ["Fecha actividad", "Actividad", "Llegada", "Retraso (min)", "Penalidad",
                                           "Estado", "Fecha de pago", "Medio de pago"]))

        with st.expander("Editar nombre", icon=":material/edit:"):
            with st.form(f"rename_{vid}"):
                new_name = st.text_input("Nombre", value=row["volunteer"])
                ok = st.form_submit_button("Guardar", type="primary")
            if ok:
                try:
                    volunteers.rename_volunteer(vid, new_name)
                except VolunteerError as exc:
                    st.error(str(exc))
                else:
                    ui.flash("success", "Nombre actualizado.")
                    st.rerun()
        if vdf.empty and st.button("Eliminar voluntario (creado por error)", icon=":material/delete:"):
            try:
                volunteers.delete_volunteer(vid)
            except VolunteerError as exc:
                st.error(str(exc))
            else:
                ui.flash("success", "Voluntario eliminado.")
                st.rerun()
