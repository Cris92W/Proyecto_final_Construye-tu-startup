"""La página carga y muestra un veredicto completo, con el LLM reemplazado por un mensaje armado a mano."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from pillao.esquemas import Mensaje, Pedido, Senal, Tipo, TipoSenal
from pillao.llm import ClienteLLM

APP = str(Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py")


def test_la_pagina_carga_sin_clave(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("pillao.llm.ClienteLLM.__init__", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert at.button[0].disabled


def test_revision_completa_con_ejemplo(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave-de-prueba")
    leido = Mensaje(transcripcion="Hola ma, este es mi número nuevo. Yapéame S/ 480. No le digas a papá.",
                    remitente="+51 9XX XXX XXX", tipo=Tipo.familiar_en_apuros, entidad_que_dice_ser="", rucs=[],
                    telefonos=[], links=[], cuentas_o_numeros_de_pago=["9XX XXX XXX"], monto="S/ 480",
                    te_piden=[Pedido.pago_o_deposito],
                    senales=[Senal(tipo=TipoSenal.numero_nuevo_de_familiar, cita="este es mi número nuevo")])
    monkeypatch.setattr(ClienteLLM, "leer", lambda self, *a, **k: leido)

    at = AppTest.from_file(APP, default_timeout=60).run()
    at.radio[0].set_value("🧪 Ver un ejemplo").run()
    at.button[0].click().run()
    assert not at.exception

    # El resultado es un carrusel: se recorre con «Siguiente» hasta la última diapositiva.
    pagina, vistas = " ".join(m.value for m in at.markdown), 1
    while siguiente := [b for b in at.button if b.label.startswith("Siguiente")]:
        siguiente[0].click().run()
        assert not at.exception
        pagina += " ".join(m.value for m in at.markdown)
        vistas += 1
    assert vistas == 5  # veredicto, qué hacer, pruebas, lo que no se puede comprobar, cómo decidimos
    assert "Muy sospechoso" in pagina
    assert "Si su familiar de verdad cambió de número" in pagina

    # «Revisar otro mensaje» vuelve a la pantalla de entrada.
    [b for b in at.button if "Revisar otro mensaje" in b.label][-1].click().run()
    assert not at.exception
    assert at.radio and at.button[0].label == "🔍 Revisar el mensaje"
