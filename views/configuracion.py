"""Configuración: datos generales, hora de inicio, reglas de penalidad y recálculos."""

import json

import pandas as pd
import sqlalchemy as sa
import streamlit as st

import database as db
import tardiness
import ui
from config import describe_rules, get_settings, parse_time, save_settings, validate_rules


def render():
    ui.header("Configuración", "Los cambios se aplican solo a los registros nuevos.")
    ui.show_flash()
    settings = get_settings()

    t1, t2, t3, t4 = st.tabs(["General", "Penalidades", "Recalcular registros", "Historial de cambios"])
    with t1:
        _general(settings)
    with t2:
        _rules(settings)
    with t3:
        _recalculate(settings)
    with t4:
        _audit()


def _general(settings):
    with st.form("general"):
        app_name = st.text_input("Nombre de la aplicación", value=settings["app_name"])
        org_name = st.text_input("Nombre del voluntariado", value=settings["org_name"])
        start = st.time_input("Hora de inicio predeterminada", value=parse_time(settings["default_start_time"]), step=60)
        ok = st.form_submit_button("Guardar", type="primary")
    if ok:
        try:
            save_settings({"app_name": app_name.strip() or "Control de Tardanzas",
                           "org_name": org_name.strip() or "Voluntariado",
                           "default_start_time": start.strftime("%H:%M")})
        except ValueError as exc:
            st.error(str(exc))
        else:
            ui.flash("success", "Configuración guardada.")
            st.rerun()
    st.divider()
    st.markdown("**Acceso del administrador**")
    st.caption("El usuario y la contraseña se definen en los *secrets* de Streamlit (`ADMIN_USER`, "
               "`ADMIN_PASSWORD_HASH`). Para cambiarlos genera un hash nuevo con `python auth.py \"nueva-clave\"` "
               "y actualiza el secreto. Consulta el README.")


def _rules(settings):
    start = parse_time(settings["default_start_time"])
    st.markdown("Cada tramo indica **desde cuántos minutos de retraso** se aplica un monto. "
                "La penalidad depende del tramo, no se multiplica por minuto.")
    current = pd.DataFrame(settings["penalty_rules"]).rename(columns={"desde_min": "Desde (min de retraso)",
                                                                      "monto": "Monto (S/)"})
    edited = st.data_editor(
        current, num_rows="dynamic", hide_index=True, width="stretch", key="rules_editor",
        column_config={
            "Desde (min de retraso)": st.column_config.NumberColumn(min_value=0, step=1, format="%d", required=True),
            "Monto (S/)": st.column_config.NumberColumn(min_value=0.0, step=0.5, format="S/ %.2f", required=True),
        },
    )
    rules = [{"desde_min": r["Desde (min de retraso)"], "monto": r["Monto (S/)"]}
             for r in edited.dropna().to_dict("records")]
    try:
        valid = validate_rules(rules)
    except ValueError as exc:
        st.error(str(exc))
        return
    st.markdown(f"**Vista previa** (con inicio a las {ui.fmt_time(start)}):")
    st.markdown("\n".join(f"- {line}" for line in describe_rules(valid, start)))
    changed = valid != validate_rules(settings["penalty_rules"])
    if st.button("Guardar reglas", type="primary", disabled=not changed):
        save_settings({"penalty_rules": valid})
        ui.flash("success", "Reglas guardadas. Se aplicarán a las tardanzas que registres desde ahora; "
                            "los registros anteriores conservan su penalidad.")
        st.rerun()


def _recalculate(settings):
    st.markdown("Aplica las **reglas vigentes** a tardanzas ya registradas. Solo hazlo si es necesario: "
                "por defecto, cada registro conserva la penalidad con la que se creó.")
    st.caption("Solo se recalculan deudas pendientes; las pagadas no se modifican para no descuadrar la caja.")
    df = tardiness.fetch_records()
    df = df[df["status"] == "Pendiente"]
    if df.empty:
        st.info("No hay deudas pendientes para recalcular.")
        return
    c1, c2 = st.columns(2)
    dmin, dmax = df["activity_date"].min().date(), df["activity_date"].max().date()
    rng = c1.date_input("Fechas de actividad", value=(dmin, dmax), format="DD/MM/YYYY", key="recalc_rng")
    acts = c2.multiselect("Actividades (opcional)", sorted(df["activity"].unique()), placeholder="Todas")
    if not (isinstance(rng, (list, tuple)) and len(rng) == 2):
        return
    subset = df[(df["activity_date"].dt.date >= rng[0]) & (df["activity_date"].dt.date <= rng[1])]
    if acts:
        subset = subset[subset["activity"].isin(acts)]
    preview = tardiness.preview_recalculation(subset["id"].tolist(), settings["penalty_rules"])
    changes = subset.merge(preview, on="id")
    changes = changes[changes["penalty_before"] != changes["penalty_after"]]
    if changes.empty:
        st.success("Con las reglas vigentes ninguna penalidad cambiaría.")
        return
    st.warning(f"{len(changes)} registro(s) cambiarían de penalidad.")
    st.dataframe(
        pd.DataFrame({"Fecha": changes["activity_date"], "Actividad": changes["activity"],
                      "Voluntario": changes["volunteer"], "Retraso (min)": changes["delay_minutes"],
                      "Antes": changes["penalty_before"], "Después": changes["penalty_after"]}),
        hide_index=True, width="stretch",
        column_config={"Fecha": st.column_config.DateColumn(format="DD/MM/YYYY"),
                       "Antes": st.column_config.NumberColumn(format="S/ %.2f"),
                       "Después": st.column_config.NumberColumn(format="S/ %.2f")},
    )
    confirm = st.checkbox("Confirmo que quiero recalcular estos registros")
    if st.button("Recalcular", type="primary", disabled=not confirm):
        n = tardiness.recalculate_with_rules(changes["id"].tolist(), settings["penalty_rules"])
        ui.flash("success", f"{n} registro(s) recalculados. El cambio quedó en el historial.")
        st.rerun()


def _audit():
    st.caption("Registro de todas las altas, correcciones, anulaciones, pagos y cambios de configuración.")
    with db.get_engine().connect() as conn:
        rows = conn.execute(
            sa.select(db.audit_log).order_by(db.audit_log.c.id.desc()).limit(300)
        ).mappings().all()
    if not rows:
        st.caption("Sin cambios registrados.")
        return
    log = pd.DataFrame(rows)
    log["details"] = log["details"].map(lambda d: _pretty(d))
    st.dataframe(
        log.rename(columns={"created_at": "Fecha", "entity": "Elemento", "entity_id": "ID", "action": "Acción",
                            "details": "Detalle"})[["Fecha", "Elemento", "ID", "Acción", "Detalle"]],
        hide_index=True, width="stretch",
        column_config={"Fecha": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
                       "Detalle": st.column_config.TextColumn(width="large")},
    )


def _pretty(details):
    if not details:
        return ""
    try:
        data = json.loads(details)
    except (TypeError, json.JSONDecodeError):
        return str(details)
    return "; ".join(f"{k}: {v}" for k, v in data.items()) if isinstance(data, dict) else str(data)
