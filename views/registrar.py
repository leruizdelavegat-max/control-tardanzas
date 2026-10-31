"""Registro de tardanzas por actividad: se arma una lista de voluntarios y se guarda junta."""

import uuid
from datetime import datetime, timedelta

import streamlit as st

import tardiness
import ui
import volunteers
from config import get_settings, parse_time, today_lima
from database import normalize_key

ACTIVITY_KEY = "reg_activity_id"
DRAFT_KEY = "reg_draft"


def render():
    ui.header("Registrar tardanza", "Elige la fecha y la actividad, agrega a todos los que llegaron tarde y guarda.")
    ui.show_flash()
    settings = get_settings()

    activity = None
    if st.session_state.get(ACTIVITY_KEY):
        activity = tardiness.get_activity(st.session_state[ACTIVITY_KEY])
    if activity is None:
        _choose_activity(settings)
        return

    _activity_banner(activity)
    records = tardiness.fetch_records()
    saved = records[records["activity_id"] == activity["id"]].sort_values("arrival_time")
    _entry_form(activity, settings, set(saved["volunteer"]))
    _draft_list(activity)
    _saved_list(activity, saved)


# ------------------------------------------------------------- paso 1


def _choose_activity(settings: dict) -> None:
    today = today_lima()
    with st.container(border=True):
        st.markdown("**1 · Fecha y actividad**")
        c1, c2 = st.columns(2)
        activity_date = c1.date_input("Fecha de la actividad", value=today, max_value=today, format="DD/MM/YYYY",
                                      help="Puedes elegir una fecha anterior para registrar tardanzas pasadas.")
        start = c2.time_input("Hora de inicio", value=parse_time(settings["default_start_time"]), step=60)
        name = st.selectbox(
            "Nombre o tipo de actividad",
            tardiness.activity_names(),
            index=None,
            accept_new_options=True,
            placeholder="Busca una actividad o escribe una nueva",
        )
        if activity_date < today:
            st.caption(f":material/history: Registrarás tardanzas del **{ui.fmt_date(activity_date)}**. "
                       f"La fecha de registro será hoy ({ui.fmt_date(today)}).")
        if st.button("Comenzar registro", type="primary", icon=":material/play_arrow:", width="stretch",
                     disabled=not name):
            try:
                act_id, created, real_start = tardiness.get_or_create_activity(name, activity_date, start)
            except tardiness.TardyError as exc:
                st.error(str(exc))
                return
            _open_activity(act_id)
            if not created and real_start != start:
                ui.flash("warning", f"Esta actividad ya existía con hora de inicio {ui.fmt_time(real_start)}; "
                                    "se mantiene esa hora. Puedes corregirla en Historial de actividades.")
            elif not created:
                ui.flash("info", "Esta actividad ya existía: puedes agregar más voluntarios.")
            st.rerun()

    recent = tardiness.list_activities().head(5)
    if not recent.empty:
        st.markdown("**Continuar una actividad reciente**")
        for row in recent.itertuples():
            c1, c2 = st.columns([4, 1.3], vertical_alignment="center")
            c1.markdown(f"{row.name}  \n<span class='page-sub'>{ui.fmt_date(row.activity_date)} · inicio "
                        f"{ui.fmt_time(row.start_time)} · {row.tardies} tardanza(s)</span>", unsafe_allow_html=True)
            if c2.button("Continuar", key=f"cont_{row.id}", width="stretch"):
                _open_activity(int(row.id))
                st.rerun()


def _open_activity(activity_id: int) -> None:
    st.session_state[ACTIVITY_KEY] = activity_id
    st.session_state[DRAFT_KEY] = []
    st.session_state["reg_batch"] = uuid.uuid4().hex
    st.session_state.pop("reg_last_arrival", None)


# ------------------------------------------------------------- paso 2


def _activity_banner(activity: dict) -> None:
    past = activity["activity_date"] < today_lima()
    st.markdown(
        f"<div class='activity-card'><div class='t'>{ui.fmt_date(activity['activity_date'])} · {activity['name']}</div>"
        f"<div class='s'>Inicio {ui.fmt_time(activity['start_time'])}"
        f"{' · fecha anterior' if past else ''}</div></div>",
        unsafe_allow_html=True,
    )


def _entry_form(activity: dict, settings: dict, saved_names: set[str]) -> None:
    n = st.session_state.setdefault("reg_form_n", 0)
    draft = st.session_state.setdefault(DRAFT_KEY, [])
    start = activity["start_time"]
    default_arrival = st.session_state.get("reg_last_arrival") or (
        datetime.combine(activity["activity_date"], start) + timedelta(minutes=10)
    ).time()

    taken = saved_names | {d["name"] for d in draft}
    names = [v for v in volunteers.list_volunteers()["name"] if v not in taken]

    with st.container(border=True):
        st.markdown("**2 · Agrega a cada voluntario que llegó tarde**")
        name = st.selectbox(
            "Voluntario", names, index=None, accept_new_options=True, key=f"reg_vol_{n}",
            placeholder="Busca o escribe un nombre nuevo",
        )
        arrival = st.time_input("Hora real de llegada", value=default_arrival, step=60, key=f"reg_arr_{n}")
        calc = tardiness.calculate(start, arrival, settings["penalty_rules"])

        if calc.delay_minutes == 0:
            st.markdown("<div class='calc-box'>Llegó a tiempo: <b>sin retraso</b> · no se registra</div>",
                        unsafe_allow_html=True)
        else:
            css = "pill-pending" if calc.penalty > 0 else "pill-neutral"
            st.markdown(
                f"<div class='calc-box'>Retraso: <b>{calc.delay_minutes} min</b> &nbsp;·&nbsp; "
                f"Penalidad: <span class='pill {css}' style='font-size:1rem'>{ui.money(float(calc.penalty))}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        needs_confirmation = _new_name_check(name, names, taken, n)
        notes = st.text_input("Observaciones (opcional)", key=f"reg_notes_{n}")

        add = st.button("Agregar a la lista", icon=":material/playlist_add:", width="stretch",
                        type="secondary" if draft else "primary",
                        disabled=not name or calc.delay_minutes == 0 or needs_confirmation)
    if add:
        draft.append({"name": name.strip(), "arrival": arrival, "notes": notes,
                      "delay": calc.delay_minutes, "penalty": float(calc.penalty)})
        st.session_state["reg_form_n"] = n + 1
        st.session_state["reg_last_arrival"] = arrival
        st.rerun()


def _new_name_check(name: str | None, names: list[str], taken: set[str], n: int) -> bool:
    """Si el nombre escrito es nuevo pero se parece a uno existente, sugiere el existente
    y pide confirmación para evitar voluntarios duplicados. Devuelve True si falta confirmar."""
    if not name:
        return False
    key = normalize_key(name)
    if key in {normalize_key(v) for v in taken}:
        st.warning("Este voluntario ya está en la lista o registrado en esta actividad.")
        return True
    if key in {normalize_key(v) for v in names}:
        return False  # mismo nombre con otra escritura: se reutiliza el existente
    similar = [v for v in names if key in normalize_key(v) or normalize_key(v) in key][:4]
    if not similar:
        st.caption(f":material/person_add: Se agregará «{name.strip()}» a la lista de voluntarios.")
        return False

    def choose(value: str) -> None:
        st.session_state[f"reg_vol_{n}"] = value

    st.warning(f"«{name.strip()}» no está en la lista. ¿Quisiste decir…?")
    cols = st.columns(len(similar))
    for col, option in zip(cols, similar):
        col.button(option, key=f"sugg_{n}_{option}", on_click=choose, args=(option,), width="stretch")
    return not st.checkbox(f"No, «{name.strip()}» es una persona nueva", key=f"reg_new_{n}")


def _draft_list(activity: dict) -> None:
    draft = st.session_state.get(DRAFT_KEY, [])
    if not draft:
        return
    total = sum(d["penalty"] for d in draft)
    with st.container(border=True):
        st.markdown(f"**3 · Por guardar: {len(draft)} voluntario(s) · {ui.money(total)}**")
        for i, d in enumerate(draft):
            c1, c2 = st.columns([5, 1], vertical_alignment="center")
            c1.markdown(f"{d['name']}  \n<span class='page-sub'>Llegó {ui.fmt_time(d['arrival'])} · "
                        f"{d['delay']} min · {ui.money(d['penalty'])}</span>", unsafe_allow_html=True)
            if c2.button("Quitar", key=f"rm_{i}_{d['name']}", icon=":material/close:", width="stretch"):
                draft.pop(i)
                st.rerun()
        st.caption("Aún no están guardados. Revisa la lista y guarda.")
        if st.button(f"Guardar {len(draft)} registro(s)", type="primary", icon=":material/save:", width="stretch"):
            try:
                results = tardiness.register_tardies(activity["id"], draft, st.session_state.get("reg_batch"))
            except tardiness.TardyError as exc:
                st.error(f"No se guardó nada. {exc}")
                return
            except Exception as exc:  # error de red o de base de datos
                st.error("No se pudo guardar. Vuelve a presionar el botón: los registros no se duplicarán.")
                st.caption(str(exc))
                return
            st.session_state[DRAFT_KEY] = []
            st.session_state["reg_batch"] = uuid.uuid4().hex
            new = sum(not r["duplicate"] for r in results)
            ui.flash("success", f"Se guardaron {new} tardanza(s) por {ui.money(total)}, todas en estado «Pendiente».")
            st.rerun()


def _saved_list(activity: dict, saved) -> None:
    st.markdown(f"**Ya guardados en esta actividad · {len(saved)}**")
    if saved.empty:
        st.caption("Aún no hay tardanzas guardadas en esta actividad.")
    else:
        ui.table(ui.records_view(saved, ["Voluntario", "Llegada", "Retraso (min)", "Penalidad", "Estado"]))
        st.markdown(f"Total de penalidades: **{ui.money(saved['penalty'].sum())}**")

    draft = st.session_state.get(DRAFT_KEY, [])
    if draft:
        st.warning(f"Tienes {len(draft)} voluntario(s) sin guardar.")
        if st.button("Descartar la lista sin guardar", icon=":material/delete:"):
            st.session_state[DRAFT_KEY] = []
            st.rerun()
    c1, c2 = st.columns(2)
    if c1.button("Cambiar de actividad", icon=":material/swap_horiz:", width="stretch", disabled=bool(draft)):
        _close_activity()
    if c2.button("Finalizar registro", icon=":material/done_all:", width="stretch", disabled=bool(draft)):
        ui.flash("success", f"Registro finalizado: {len(saved)} tardanza(s) en «{activity['name']}» por "
                            f"{ui.money(saved['penalty'].sum())}.")
        _close_activity()


def _close_activity() -> None:
    for key in (ACTIVITY_KEY, DRAFT_KEY, "reg_last_arrival", "reg_batch"):
        st.session_state.pop(key, None)
    st.rerun()
