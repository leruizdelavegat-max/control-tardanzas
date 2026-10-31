"""Asistente de configuración: conecta la app con Supabase y define la contraseña del administrador.

Uso:  python configurar.py

Escribe .streamlit/secrets.toml (que nunca se sube a GitHub), crea las tablas en
Supabase y comprueba la conexión. Las contraseñas se escriben sin mostrarse en pantalla.
"""

import getpass
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

import auth

ROOT = Path(__file__).resolve().parent
SECRETS = ROOT / ".streamlit" / "secrets.toml"
PLACEHOLDER = "[YOUR-PASSWORD]"


def ask_url_template() -> str:
    print("\n1) Pega la dirección de Supabase (Connect → Direct → Session pooler), tal como aparece,")
    print(f"   con {PLACEHOLDER} incluido. Ejemplo:")
    print(f"   postgresql://postgres.abcd:{PLACEHOLDER}@aws-0-sa-east-1.pooler.supabase.com:5432/postgres")
    while True:
        url = input("   Dirección: ").strip().strip('"')
        if url.startswith(("postgresql://", "postgres://")):
            return url
        print("   Debe empezar con postgresql://  Inténtalo de nuevo.")


def ask_db_password() -> str:
    print("\n   Contraseña de la base de datos de Supabase (la de «Database Password»).")
    print("   Si pegar no funciona, escríbela con el teclado.")
    while True:
        value = getpass.getpass("   Contraseña (no se verá al escribir): ").strip()
        if value:
            print(f"   Recibí una contraseña de {len(value)} caracteres.")
            return value
        print("   No recibí nada. Escríbela con el teclado y pulsa Enter.")


def test_connection(url: str) -> int:
    """Devuelve el número de tardanzas, o lanza la excepción de conexión."""
    os.environ["DATABASE_URL"] = url
    import database as db
    import sqlalchemy as sa

    db._engine_for.cache_clear()
    with db.get_engine().connect() as conn:
        return conn.execute(sa.select(sa.func.count()).select_from(db.tardies)).scalar_one()


def ask_admin_password() -> str:
    print("\n2) Elige la contraseña con la que entrarás a la app (mínimo 8 caracteres).")
    while True:
        first = getpass.getpass("   Contraseña (no se verá al escribir): ")
        if len(first) < 8:
            print("   Muy corta, usa al menos 8 caracteres.")
            continue
        if getpass.getpass("   Repítela: ") == first:
            return first
        print("   No coinciden. Inténtalo de nuevo.")


def main() -> None:
    print("=== Configuración de Control de Tardanzas ===")
    template = ask_url_template()
    while True:
        url = template
        if PLACEHOLDER in template:
            url = template.replace(PLACEHOLDER, quote(ask_db_password(), safe=""))
        print("   Probando la conexión con Supabase...")
        try:
            n = test_connection(url)
            break
        except Exception as exc:
            text = str(exc).splitlines()[0] if str(exc) else repr(exc)
            if "password authentication failed" in text:
                print("   ✗ Supabase dice que la contraseña es incorrecta. Inténtalo otra vez.")
                print("     (Si no la recuerdas: Supabase → Project Settings → Database → Reset database password)")
            else:
                print(f"   ✗ No se pudo conectar: {text}")
            if PLACEHOLDER not in template or input("   ¿Reintentar? [S/n]: ").strip().lower() == "n":
                sys.exit(1)
    print(f"   ✓ Conexión correcta. Tablas listas ({n} tardanzas registradas).")

    user = input("\n   Usuario administrador [admin]: ").strip() or "admin"
    password_hash = auth.hash_password(ask_admin_password())

    if SECRETS.exists():
        shutil.copy(SECRETS, SECRETS.with_name("secrets.prueba.toml"))
    SECRETS.parent.mkdir(exist_ok=True)
    SECRETS.write_text(
        f'DATABASE_URL = "{url}"\nADMIN_USER = "{user}"\nADMIN_PASSWORD_HASH = "{password_hash}"\n',
        encoding="utf-8",
    )
    print(f"\n3) Configuración guardada en {SECRETS}")
    print("   Ese archivo NO se sube a GitHub. Su contenido es el que pegarás en Streamlit Cloud → Secrets.")


if __name__ == "__main__":
    main()
