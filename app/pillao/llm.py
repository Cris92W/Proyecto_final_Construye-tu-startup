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
from dataclasses import dataclass, field
from pathlib import Path

from google import genai
from google.genai import errors, types

from .esquemas import Mensaje

# Flash-Lite lee una captura en 2 a 5 s y acertó igual que Flash en 14 capturas reales (2026-11-10),
# a una fracción del costo. Su plan gratuito permite unas 500 consultas al día; Flash, solo 20.
# Si Flash-Lite está saturado (503) o sin cuota (429), se usa Flash como respaldo.
MODELO_POR_DEFECTO = "gemini-3.5-flash-lite"
MODELO_RESPALDO = "gemini-3.5-flash"
CARPETA_PROMPTS = Path(__file__).resolve().parents[2] / "ai" / "prompts"

# Precio de lista del plan de pago, en US$ por millón de tokens: (entrada, salida con razonamiento).
# Según rastreadores de precios al 2026-11-10; confirmar en https://ai.google.dev/gemini-api/docs/pricing.
# El demo usa el plan gratuito; estos precios sirven para calcular el costo cuando haya clientes.
PRECIOS_USD_POR_MILLON = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.5-flash": (1.50, 9.00),
}

_REINTENTABLES = {429, 500, 503}


def _prompt(nombre: str) -> str:
    return (CARPETA_PROMPTS / f"{nombre}.md").read_text(encoding="utf-8")


@dataclass
class Uso:
    llamadas: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo: float = 0.0
    precio_conocido: bool = True
    modelos: list[str] = field(default_factory=list)

    def sumar(self, respuesta, modelo: str) -> None:
        meta = respuesta.usage_metadata
        entrada = (meta.prompt_token_count or 0) if meta else 0
        salida = ((meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0)) if meta else 0
        self.llamadas += 1
        self.tokens_entrada += entrada
        self.tokens_salida += salida
        if modelo not in self.modelos:
            self.modelos.append(modelo)
        precios = PRECIOS_USD_POR_MILLON.get(modelo)
        if precios is None:
            self.precio_conocido = False
        else:
            self.costo += (entrada * precios[0] + salida * precios[1]) / 1_000_000

    def costo_usd(self) -> float | None:
        return self.costo if self.precio_conocido else None


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
        modelos = [self.modelo] + ([MODELO_RESPALDO] if self.modelo != MODELO_RESPALDO else [])
        ultimo_error: Exception | None = None
        for modelo in modelos:
            for intento in range(2):
                try:
                    respuesta = self._cliente.models.generate_content(
                        model=modelo, contents=contenido, config=config)
                except errors.APIError as error:
                    # Saturación o límite del plan gratuito: esperar, reintentar y luego pasar al respaldo.
                    if error.code not in _REINTENTABLES:
                        raise
                    ultimo_error = error
                    if intento == 0:
                        time.sleep(2)
                    continue
                self.uso.sumar(respuesta, modelo)
                return respuesta
        raise RuntimeError("Los modelos no respondieron; intente en un minuto.") from ultimo_error

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
