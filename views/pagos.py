"""Control de pagos y cobranzas."""

import pandas as pd
import streamlit as st

import payments
import reports
import tardiness
import ui
from config import PAYMENT_METHODS, today_lima


def render():
    ui.header("Control de pagos", "Las deudas solo cambian a «Pagado» cuando tú registras el pago.")
    ui.show_flash()
    df = tardiness.fetch_records()
    if df.empty:
        st.info("Todavía no hay deudas registradas.")
        return

    pending = df[df["status"] == "Pendiente"]
    k = reports.kpis(df)
    c = st.columns(3)
    c[0].metric("Total pendiente de cobro", ui.money(k["pending"]), border=True)
    c[1].metric("Deudas pendientes", f"{len(pending)} · {pending['volunteer_id'].nunique()} persona(s)", border=True)
    c[2].metric("Total recaudado", ui.money(k["collected"]), border=True)

    t1, t2, t3, t4 = st.tabs(["Pendientes", "Saldos por voluntario", "Pagadas", "Historial de pagos"])
    with t1:
        _pending(pending)
    with t2:
        _balances(df)
    with t3:
        paid = ui.record_filters(df[df["status"] == "Pagado"], "paid", show_status=False)
        st.caption(f"{len(paid)} deuda(s) pagada(s) · {ui.money(paid['paid'].sum())}")
        ui.table(ui.records_view(paid, ["Fecha actividad", "Actividad", "Voluntario", "Penalidad", "Pagado",
                                        "Fecha de pago", "Medio de pago", "Estado"]))
    with t4:
        _payment_history()


def _pending(pending: pd.DataFrame):
    if pending.empty:
        st.success("No hay deudas pendientes. ¡Todo al día!")
        return
    search = st.text_input("Buscar por nombre", placeholder="Escribe parte del nombre", key="pay_search",
                           label_visibility="collapsed")
    view = pending
    if search:
        view = view[view["volunteer"].str.contains(search.strip(), case=False, regex=False)]
    view = ui.record_filters(view, "pend", show_status=False).sort_values(["volunteer", "activity_date"])
    view = view.reset_index(drop=True)
    st.caption(f"{len(view)} deuda(s) · {ui.money(view['balance'].sum())} por cobrar. "
               "Selecciona una o varias filas para registrar el pago.")
    event = ui.table(
        ui.records_view(view, ["Voluntario", "Fecha actividad", "Actividad", "Retraso (min)", "Penalidad", "Pagado",
                               "Saldo"]),
        key="pend_table", selection="multi-row",
    )
    rows = ui.selected_rows(event, len(view))
    if rows:
        _payment_form(view.iloc[rows])


def _payment_form(selected: pd.DataFrame):
    total = float(selected["balance"].sum())
    names = ", ".join(sorted(selected["volunteer"].unique()))
    with st.container(border=True):
        st.markdown(f"**Registrar pago** · {len(selected)} deuda(s) de {names}")
        single = len(selected) == 1
        with st.form("pay_form"):
            c1, c2 = st.columns(2)
            pay_date = c1.date_input("Fecha del pago", value=today_lima(), max_value=today_lima(), format="DD/MM/YYYY")
            if single:
                amount = c2.number_input("Monto pagado (S/)", min_value=0.0, max_value=total, value=total, step=0.5,
                                         format="%.2f")
            else:
                c2.text_input("Monto pagado (S/)", value=f"{total:.2f}", disabled=True,
                              help="Con varias deudas se paga el saldo completo de cada una.")
                amount = total
            method = st.segmented_control("Medio de pago", PAYMENT_METHODS, default=None)
            notes = st.text_input("Observaciones (opcional)")
            ok = st.form_submit_button("Confirmar pago", type="primary", icon=":material/check:", width="stretch")
        if ok:
            if not method:
                st.error("Selecciona el medio de pago.")
                return
            try:
                if single:
                    status = payments.register_payment(int(selected.iloc[0]["id"]), pay_date, amount, method, notes)
                    msg = ("Pago registrado; la deuda quedó **pagada**." if status == "Pagado"
                           else f"Pago parcial registrado; queda saldo de {ui.money(total - amount)}.")
                else:
                    payments.register_payments([int(i) for i in selected["id"]], pay_date, method, notes)
                    msg = f"{len(selected)} deudas marcadas como **pagadas** ({ui.money(total)})."
            except payments.PaymentError as exc:
                st.error(str(exc))
            else:
                ui.flash("success", msg)
                st.rerun()


def _balances(df: pd.DataFrame):
    summary = reports.volunteer_summary(df)
    summary = summary.rename(columns={"volunteer": "Voluntario", "Ultima": "Última tardanza"})
    only_debt = st.toggle("Solo personas con saldo pendiente", value=True)
    if only_debt:
        summary = summary[summary["Pendiente"] > 0]
    ui.table(summary[["Voluntario", "Tardanzas", "Total", "Pagado", "Pendiente", "Última tardanza"]])


def _payment_history():
    show_void = st.toggle("Mostrar pagos anulados", value=False)
    pays = payments.fetch_payments(include_voided=show_void).reset_index(drop=True)
    if pays.empty:
        st.caption("Aún no hay pagos registrados.")
        return
    view = pd.DataFrame({
        "Fecha de pago": pays["payment_date"],
        "Voluntario": pays["volunteer"],
        "Actividad": pays["activity"],
        "Fecha actividad": pays["activity_date"],
        "Monto": pays["amount"],
        "Medio de pago": pays["method"],
        "Observaciones": pays["notes"],
        "Registrado el": pays["created_at"],
        "Estado": pays["voided"].map({True: "Anulado", False: "Válido"}),
    })
    st.caption(f"{(~pays['voided']).sum()} pago(s) válido(s) · {ui.money(pays.loc[~pays['voided'], 'amount'].sum())}")
    event = ui.table(view, key="payhist", selection="single-row")
    rows = ui.selected_rows(event, len(pays))
    if not rows:
        return
    pay = pays.iloc[rows[0]]
    if pay["voided"]:
        st.info(f"Pago anulado. Motivo: {pay['void_reason']}")
        return
    with st.container(border=True):
        st.markdown(f"**Anular pago** de {pay['volunteer']} por {ui.money(pay['amount'])} "
                    f"({pay['method']}, {ui.fmt_date(pay['payment_date'])})")
        with st.form(f"void_pay_{pay['payment_id']}"):
            reason = st.text_input("Motivo de la anulación *")
            ok = st.form_submit_button("Anular pago")
        st.caption("Úsalo solo para corregir errores. La deuda volverá a quedar pendiente.")
        if ok:
            try:
                payments.void_payment(int(pay["payment_id"]), reason)
            except payments.PaymentError as exc:
                st.error(str(exc))
            else:
                ui.flash("success", "Pago anulado; la deuda volvió a «Pendiente».")
                st.rerun()
