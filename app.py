"""Control de Tardanzas · aplicación principal y navegación.

Ejecutar localmente:  streamlit run app.py
"""

import streamlit as st

st.set_page_config(page_title="Control de Tardanzas", page_icon="⏱️", layout="wide")

import auth  # noqa: E402
import database as db  # noqa: E402
import ui  # noqa: E402
from config import get_settings  # noqa: E402
from views import configuracion, historial, inicio, pagos, registrar, reportes, voluntarios  # noqa: E402

ui.inject_css()

try:
    db.get_engine()
    settings = get_settings()
except db.DatabaseConfigError as exc:
    st.error(f"**Base de datos no configurada.** {exc}")
    st.stop()
except Exception as exc:  # conexión rechazada, credenciales erróneas, red, etc.
    st.error("**No se pudo conectar con la base de datos.** Revisa `DATABASE_URL` y tu conexión a internet.")
    with st.expander("Detalle técnico"):
        st.code(str(exc))
    st.stop()

if not auth.require_login(settings["app_name"]):
    st.stop()

pages = [
    st.Page(inicio.render, title="Inicio", icon=":material/space_dashboard:", url_path="inicio", default=True),
    st.Page(registrar.render, title="Registrar tardanza", icon=":material/alarm_add:", url_path="registrar"),
    st.Page(historial.render, title="Historial de actividades", icon=":material/history:", url_path="historial"),
    st.Page(pagos.render, title="Control de pagos", icon=":material/payments:", url_path="pagos"),
    st.Page(voluntarios.render, title="Voluntarios", icon=":material/group:", url_path="voluntarios"),
    st.Page(reportes.render, title="Reportes y Excel", icon=":material/table_view:", url_path="reportes"),
    st.Page(configuracion.render, title="Configuración", icon=":material/settings:", url_path="configuracion"),
]
ui.PAGES.update({p.url_path: p for p in pages})
page = st.navigation(pages)

with st.sidebar:
    st.markdown(f"**{settings['app_name']}**  \n<span style='color:#64748B'>{settings['org_name']}</span>",
                unsafe_allow_html=True)
    if st.button("Cerrar sesión", icon=":material/logout:", width="stretch"):
        auth.logout()

try:
    page.run()
except db.OperationalError:
    st.error("Se perdió la conexión con la base de datos. Recarga la página e intenta de nuevo; "
             "los datos guardados no se pierden.")
