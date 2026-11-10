"""Costo por revisión y respaldo de modelo, sin llamar a la API."""
from types import SimpleNamespace

from google.genai import errors

from pillao import llm


def respuesta(entrada, salida):
    meta = SimpleNamespace(prompt_token_count=entrada, candidates_token_count=salida, thoughts_token_count=None)
    return SimpleNamespace(usage_metadata=meta, parsed=None, text="{}")


def test_costo_con_precio_de_lista():
    uso = llm.Uso()
    uso.sumar(respuesta(2_000_000, 0), "gemini-3.5-flash-lite")
    assert round(uso.costo_usd(), 6) == 0.60
    uso.sumar(respuesta(0, 0), "modelo-sin-precio")
    assert uso.costo_usd() is None


def test_pasa_al_modelo_de_respaldo_si_esta_saturado(monkeypatch):
    llamados = []

    def generar(model, contents, config):
        llamados.append(model)
        if model == llm.MODELO_POR_DEFECTO:
            raise errors.ServerError(503, {"error": {"message": "alta demanda"}})
        return respuesta(100, 10)

    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    cliente = llm.ClienteLLM(api_key="clave-de-prueba")
    monkeypatch.setattr(cliente._cliente.models, "generate_content", generar)
    cliente._generar("hola")
    assert llamados == [llm.MODELO_POR_DEFECTO, llm.MODELO_POR_DEFECTO, llm.MODELO_RESPALDO]
    assert cliente.uso.modelos == [llm.MODELO_RESPALDO]
