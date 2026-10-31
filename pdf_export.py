"""Reportes en PDF: listado de tardanzas con monto y estado de pago."""

from __future__ import annotations

import pandas as pd
from fpdf import FPDF
from fpdf.fonts import FontFace

import reports
from config import now_lima

HEADER_BG = (31, 78, 95)
PAID = (6, 118, 71)
PENDING = (180, 35, 24)


class _Report(FPDF):
    def __init__(self, org: str):
        super().__init__(orientation="L", format="A4")
        self.org = org
        self.set_auto_page_break(True, margin=15)
        self.set_margins(12, 12, 12)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", size=8)
        self.set_text_color(120)
        self.cell(self.epw / 2, 6, f"{self.org} · generado el {now_lima():%d/%m/%Y %H:%M}", align="L")
        self.cell(0, 6, f"Página {self.page_no()} de {{nb}}", align="R")


def _money(value: float) -> str:
    return f"S/ {value:,.2f}"


def _fmt_time(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"{value.hour % 12 or 12}:{value.minute:02d} {'a. m.' if value.hour < 12 else 'p. m.'}"


def build_pdf(records: pd.DataFrame, title: str, subtitle: str, org: str) -> bytes:
    """PDF con resumen y tabla: fecha, actividad, voluntario, llegada, retraso, monto, pagado y estado."""
    records = records.sort_values(["activity_date", "activity", "arrival_time"])
    pdf = _Report(org)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 9, title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.set_text_color(90)
    pdf.cell(0, 6, f"{org} · {subtitle}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    k = reports.kpis(records)
    pdf.set_text_color(15, 23, 42)
    pdf.set_font("Helvetica", "B", 10)
    summary = (f"Tardanzas: {k['tardies']}    Voluntarios: {k['volunteers']}    "
               f"Total de deuda: {_money(k['generated'])}    Pagado: {_money(k['collected'])}    "
               f"Pendiente: {_money(k['pending'])}")
    pdf.cell(0, 7, summary, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("Helvetica", size=9)
    headings = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=HEADER_BG)
    with pdf.table(
        col_widths=(22, 60, 62, 24, 20, 25, 25, 25),
        text_align=("CENTER", "LEFT", "LEFT", "CENTER", "CENTER", "RIGHT", "RIGHT", "CENTER"),
        headings_style=headings, line_height=6.5, cell_fill_color=(244, 247, 249), cell_fill_mode="ROWS",
    ) as table:
        header = table.row()
        for h in ("Fecha", "Actividad", "Voluntario", "Llegada", "Retraso", "Monto", "Pagado", "Estado"):
            header.cell(h)
        for r in records.itertuples():
            row = table.row()
            row.cell(f"{r.activity_date:%d/%m/%Y}")
            row.cell(str(r.activity))
            row.cell(str(r.volunteer))
            row.cell(_fmt_time(r.arrival_time))
            row.cell(f"{r.delay_minutes} min")
            row.cell(_money(r.penalty))
            row.cell(_money(r.paid))
            color = PAID if r.status == "Pagado" else PENDING
            row.cell(str(r.status), style=FontFace(color=color, emphasis="BOLD"))

    if not records.empty and records["month"].nunique() > 1:
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Resumen por actividad", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=9)
        acts = reports.activity_summary(records).sort_values(["Fecha", "Actividad"])
        with pdf.table(col_widths=(25, 90, 25, 35, 35, 35),
                       text_align=("CENTER", "LEFT", "CENTER", "RIGHT", "RIGHT", "RIGHT"),
                       headings_style=headings, line_height=6.5) as table:
            header = table.row()
            for h in ("Fecha", "Actividad", "Tardanzas", "Total", "Recaudado", "Pendiente"):
                header.cell(h)
            for a in acts.itertuples():
                row = table.row()
                row.cell(f"{pd.Timestamp(a.Fecha):%d/%m/%Y}")
                row.cell(str(a.Actividad))
                row.cell(str(a.Tardanzas))
                row.cell(_money(a.Penalidades))
                row.cell(_money(a.Recaudado))
                row.cell(_money(a.Pendiente))

    return bytes(pdf.output())
