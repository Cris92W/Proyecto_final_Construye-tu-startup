"""Cliente del LLM (Gemini) de Pillao.

Una sola llamada por revisión: la captura (o el texto pegado) → JSON validado con `Mensaje`.
- Lee la imagen con un modelo de visión (Document AI, sesión 10).
- Devuelve campos y citas en un esquema fijo (salidas estructuradas, sesión 08).

La IA no decide el veredicto: eso lo hacen las reglas de verificar.py. Así cada «es estafa» se
puede explicar con una prueba o una regla, y no depende de lo que el modelo «opine».

Cada llamada suma sus tokens en `uso` para calcular el costo real por revisión.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from google import genai
from google.genai import errors, types

from .esquemas import Mensaje

MODELO_POR_DEFECTO = "gemini-2.5-flash"
CARPETA_PROMPTS = Path(__file__).resolve().parents[2] / "ai" / "prompts"

# Precio de lista del plan de pago, en US$ por millón de tokens: (entrada, salida con razonamiento).
# El demo usa el plan gratuito; estos precios sirven para calcular el costo cuando haya clientes.
PRECIOS_USD_POR_MILLON = {
    "gemini-2.5-flash": (0.30, 2.50),
}

_REINTENTABLES = {429, 500, 503}


def _prompt(nombre: str) -> str:
    return (CARPETA_PROMPTS / f"{nombre}.md").read_text(encoding="utf-8")


@dataclass
class Uso:
    llamadas: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0

    def sumar(self, respuesta) -> None:
        meta = respuesta.usage_metadata
        self.llamadas += 1
        if meta is not None:
            self.tokens_entrada += meta.prompt_token_count or 0
            self.tokens_salida += (meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0)

    def costo_usd(self, modelo: str) -> float | None:
        precios = PRECIOS_USD_POR_MILLON.get(modelo)
        if precios is None:
            return None
        return (self.tokens_entrada * precios[0] + self.tokens_salida * precios[1]) / 1_000_000


class ClienteLLM:
    def __init__(self, api_key: str | None = None, modelo: str | None = None):
        clave = api_key or os.getenv("GEMINI_API_KEY")
        if not clave:
            raise RuntimeError("Falta GEMINI_API_KEY (ponla en .env o en los Secrets de Streamlit).")
        self.modelo = modelo or os.getenv("GEMINI_MODEL") or MODELO_POR_DEFECTO
        self._cliente = genai.Client(api_key=clave)
        self.uso = Uso()

    def _generar(self, contenido, esquema=None):
        config = types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json" if esquema else None,
            response_schema=esquema,
        )
        for intento in range(4):
            try:
                respuesta = self._cliente.models.generate_content(
                    model=self.modelo, contents=contenido, config=config)
            except errors.APIError as error:
                # El plan gratuito limita las solicitudes por minuto: esperar y reintentar.
                if error.code in _REINTENTABLES and intento < 3:
                    time.sleep(3 * 2 ** intento)
                    continue
                raise
            self.uso.sumar(respuesta)
            return respuesta
        raise RuntimeError("El modelo no respondió después de 4 intentos.")

    def leer(self, imagen: bytes | None = None, tipo_imagen: str = "image/png", texto: str = "") -> Mensaje:
        """Lee una captura de pantalla, un texto pegado o ambos."""
        if not imagen and not texto.strip():
            raise ValueError("Suba una captura o pegue el texto del mensaje.")
        contenido: list = []
        if imagen:
            contenido.append(types.Part.from_bytes(data=imagen, mime_type=tipo_imagen))
        texto_pegado = texto.strip() or "(no hay texto pegado: el mensaje está en la imagen)"
        contenido.append(_prompt("leer_mensaje").replace("{texto}", texto_pegado))
        respuesta = self._generar(contenido, Mensaje)
        if isinstance(respuesta.parsed, Mensaje):
            return respuesta.parsed
        return Mensaje.model_validate_json(respuesta.text)
