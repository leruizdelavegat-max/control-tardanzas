"""Prueba de humo: cada página se dibuja sin errores con datos de demostración."""

from datetime import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
PAGES = ["inicio", "registrar", "historial", "pagos", "voluntarios", "reportes", "configuracion"]


def _run_page(name):
    import importlib

    import ui

    ui.inject_css()
    importlib.import_module(f"views.{name}").render()


@pytest.fixture(scope="module")
def demo_db(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "demo.db"
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    mp.syspath_prepend(str(ROOT))
    mp.chdir(ROOT)
    import seed_demo

    seed_demo.main()
    yield
    mp.undo()


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(demo_db, page):
    at = AppTest.from_function(_run_page, args=(page,), default_timeout=60)
    at.run()
    assert not at.exception, [e.message for e in at.exception]


def test_register_flow_in_ui(demo_db):
    at = AppTest.from_function(_run_page, args=("registrar",), default_timeout=60)
    at.run()
    at.selectbox[0].set_value("Reunión general").run()  # con fecha de hoy: actividad nueva
    at.button[0].click().run()  # Comenzar registro
    assert not at.exception
    assert at.session_state["reg_activity_id"]
    for person, minute in (("Ana Torres", 12), ("Pedro Salas", 25)):
        n = at.session_state["reg_form_n"]
        at.selectbox(key=f"reg_vol_{n}").set_value(person)
        at.time_input(key=f"reg_arr_{n}").set_value(time(9, minute)).run()
        add = next(b for b in at.button if b.label == "Agregar a la lista")
        add.click().run()
        assert not at.exception, [e.message for e in at.exception]
        assert at.session_state["reg_form_n"] == n + 1  # formulario listo para el siguiente
    assert len(at.session_state["reg_draft"]) == 2
    assert "**Ya guardados en esta actividad · 0**" in [m.value for m in at.markdown]  # aún nada guardado

    save = next(b for b in at.button if b.label == "Guardar 2 registro(s)")
    save.click().run()
    assert not at.exception, [e.message for e in at.exception]
    assert at.session_state["reg_draft"] == []
    assert any("Se guardaron 2 tardanza(s) por S/ 3.00" in s.value for s in at.success)
    assert "**Ya guardados en esta actividad · 2**" in [m.value for m in at.markdown]
