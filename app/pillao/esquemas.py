"""Lo que la IA extrae de un mensaje sospechoso (salida estructurada, sesión 08).

La IA solo lee y extrae, con citas textuales. No decide si es estafa: eso lo hacen las reglas de
verificar.py. Los campos no tienen valores por defecto para que Gemini acepte el esquema.
"""
from enum import Enum

from pydantic import BaseModel, Field


class Tipo(str, Enum):
    prestamo = "prestamo"
    trabajo = "trabajo"
    premio_o_sorteo = "premio_o_sorteo"
    aviso_de_banco_o_billetera = "aviso_de_banco_o_billetera"
    familiar_en_apuros = "familiar_en_apuros"
    entidad_del_estado = "entidad_del_estado"
    paquete_o_envio = "paquete_o_envio"
    inversion = "inversion"
    compra_venta = "compra_venta"
    comprobante_de_pago = "comprobante_de_pago"
    otro = "otro"


class Pedido(str, Enum):
    clave_o_pin = "clave_o_pin"
    codigo_por_sms = "codigo_por_sms"
    datos_de_tarjeta = "datos_de_tarjeta"
    pago_o_deposito = "pago_o_deposito"
    abrir_un_link = "abrir_un_link"
    instalar_una_app = "instalar_una_app"
    foto_de_dni_o_datos_personales = "foto_de_dni_o_datos_personales"
    llamar_o_escribir_a_un_numero = "llamar_o_escribir_a_un_numero"


class TipoSenal(str, Enum):
    urgencia_o_amenaza = "urgencia_o_amenaza"
    premio_o_ganancia_inesperada = "premio_o_ganancia_inesperada"
    numero_nuevo_de_familiar = "numero_nuevo_de_familiar"
    oferta_demasiado_buena = "oferta_demasiado_buena"
    pide_secreto = "pide_secreto"
    escribe_desde_numero_personal = "escribe_desde_numero_personal"
    ganar_dinero_por_tareas = "ganar_dinero_por_tareas"
    devolver_pago_por_error = "devolver_pago_por_error"


class Senal(BaseModel):
    tipo: TipoSenal
    cita: str = Field(description="Frase copiada tal cual del mensaje que muestra la señal.")


class Mensaje(BaseModel):
    transcripcion: str = Field(description="Todo el texto del mensaje, copiado tal cual.")
    remitente: str = Field(description="Cómo aparece quien escribe: número, nombre de contacto o "
                                       "nombre de la entidad. Vacío si no se ve.")
    tipo: Tipo
    entidad_que_dice_ser: str = Field(description="Banco, empresa o entidad del Estado que el mensaje "
                                                  "dice ser o menciona como origen. Vacío si ninguna.")
    rucs: list[str]
    telefonos: list[str]
    links: list[str]
    cuentas_o_numeros_de_pago: list[str] = Field(description="Cuentas, CCI o números de Yape/Plin "
                                                              "a los que piden pagar.")
    monto: str = Field(description="Monto que piden pagar o que ofrecen, tal cual. Vacío si ninguno.")
    te_piden: list[Pedido]
    senales: list[Senal]
