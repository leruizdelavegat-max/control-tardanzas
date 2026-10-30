"""Acceso del administrador.

La contraseña nunca se guarda en el código: se define en los secretos de
Streamlit (o variables de entorno) como hash PBKDF2. Para generar el hash:

    python auth.py "mi-contraseña-segura"
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sys
import time

ITERATIONS = 310_000
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 60


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(candidate, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def _secret(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st

        return st.secrets.get(name)
    except Exception:
        return None


def check_credentials(username: str, password: str) -> bool:
    expected_user = _secret("ADMIN_USER") or "admin"
    user_ok = hmac.compare_digest(username.strip().lower(), expected_user.strip().lower())
    stored_hash = _secret("ADMIN_PASSWORD_HASH")
    if stored_hash:
        return user_ok and verify_password(password, stored_hash)
    plain = _secret("ADMIN_PASSWORD")
    if plain:
        return user_ok and hmac.compare_digest(password, plain)
    return False


def credentials_configured() -> bool:
    return bool(_secret("ADMIN_PASSWORD_HASH") or _secret("ADMIN_PASSWORD"))


def require_login(app_name: str) -> bool:
    """Muestra el formulario de acceso si hace falta. Devuelve True si hay sesión."""
    import streamlit as st

    if st.session_state.get("auth_ok"):
        return True

    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.markdown("<div style='height:6vh'></div>", unsafe_allow_html=True)
        st.title(app_name)
        st.caption("Acceso exclusivo para el administrador")
        if not credentials_configured():
            st.error(
                "No hay credenciales configuradas. Define `ADMIN_PASSWORD_HASH` (recomendado) o "
                "`ADMIN_PASSWORD` en los secretos de Streamlit. Consulta el README."
            )
            return False

        locked_until = st.session_state.get("auth_locked_until", 0)
        if time.time() < locked_until:
            st.warning(f"Demasiados intentos. Espera {int(locked_until - time.time()) + 1} segundos.")
            return False

        with st.form("login", border=True):
            username = st.text_input("Usuario", value="admin", autocomplete="username")
            password = st.text_input("Contraseña", type="password", autocomplete="current-password")
            submitted = st.form_submit_button("Ingresar", type="primary", width="stretch")
        if submitted:
            if check_credentials(username, password):
                st.session_state["auth_ok"] = True
                st.session_state.pop("auth_attempts", None)
                st.rerun()
            attempts = st.session_state.get("auth_attempts", 0) + 1
            st.session_state["auth_attempts"] = attempts
            if attempts >= MAX_ATTEMPTS:
                st.session_state["auth_locked_until"] = time.time() + LOCKOUT_SECONDS
                st.session_state["auth_attempts"] = 0
            st.error("Usuario o contraseña incorrectos.")
    return False


def logout() -> None:
    import streamlit as st

    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('Uso: python auth.py "contraseña"')
        sys.exit(1)
    print(hash_password(sys.argv[1]))
