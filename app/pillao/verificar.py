"""Las reglas que deciden el veredicto de Pillao.

La IA solo lee el mensaje (llm.py). Aquí, con código que se puede auditar y probar, se comprueba
cada campo y se decide el veredicto. Cada hallazgo tiene una fuerza:

- prueba: comprobado contra un dato público o un cálculo exacto (dominio oficial, RUC, RDAP).
- regla:  algo que ninguna entidad formal hace nunca (pedir el código SMS, cobrar por un préstamo).
- señal:  patrón típico de estafa que no prueba nada por sí solo.

Lo que no se puede comprobar se devuelve aparte (NoComprobable), con lo que la persona puede hacer.
El veredicto nunca es «seguro». El detalle de qué se comprueba y qué no está en docs/alcance.md.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import requests

from .esquemas import Mensaje, Pedido, Tipo, TipoSenal

RAIZ = Path(__file__).resolve().parents[2]
RUTA_ENTIDADES = RAIZ / "data" / "entidades_oficiales.csv"
RUTA_REGISTRO_SBS = RAIZ / "data" / "registro_sbs.csv"

EN_CONTRA, A_FAVOR = "en_contra", "a_favor"
PRUEBA, REGLA, SENAL = "prueba", "regla", "señal"
ROJO, NARANJA, AMARILLO = "rojo", "naranja", "amarillo"

FUENTE_DOMINIOS = "Lista de dominios oficiales de Pillao (data/entidades_oficiales.csv)"
FUENTE_IA = "Lectura del mensaje por la IA, con la frase exacta"

# Sufijos de dos niveles más comunes en los links que llegan al Perú (para mostrar el dominio).
SUFIJOS_DOBLES = {"com.pe", "gob.pe", "org.pe", "edu.pe", "net.pe", "nom.pe", "mil.pe", "sld.pe",
                  "com.ar", "com.br", "com.co", "com.mx", "com.ec", "com.bo", "com.ve", "co.uk"}
ACORTADORES = {"bit.ly", "cutt.ly", "tinyurl.com", "t.ly", "is.gd", "rb.gy", "shorturl.at",
               "acortar.link", "ow.ly", "s.id", "t.co", "tiny.cc", "rebrand.ly", "bitly.com"}
DIAS_DOMINIO_NUEVO = 90


# --- Datos -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Entidad:
    nombre: str
    tipo: str
    dominios: tuple[str, ...]
    palabras: tuple[str, ...]


@dataclass(frozen=True)
class RegistroSBS:
    nombres: tuple[str, ...]
    fecha: str
    fuente: str


def cargar_entidades(ruta: Path = RUTA_ENTIDADES) -> list[Entidad]:
    with open(ruta, encoding="utf-8") as archivo:
        return [Entidad(nombre=f["entidad"], tipo=f["tipo"],
                        dominios=tuple(f["dominios"].split(";")),
                        palabras=tuple(f["palabras_clave"].split(";")))
                for f in csv.DictReader(archivo)]


def cargar_registro_sbs(ruta: Path = RUTA_REGISTRO_SBS) -> RegistroSBS | None:
    """Registro de la SBS descargado a mano (su web bloquea las consultas automáticas)."""
    if not ruta.exists():
        return None
    with open(ruta, encoding="utf-8") as archivo:
        filas = list(csv.DictReader(archivo))
    if not filas:
        return None
    return RegistroSBS(nombres=tuple(f["nombre"] for f in filas), fecha=filas[0]["fecha"],
                       fuente=filas[0]["fuente"])


# --- Resultado ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class Hallazgo:
    campo: str
    resultado: str  # en_contra | a_favor
    fuerza: str     # prueba | regla | señal
    titulo: str
    detalle: str
    fuente: str


@dataclass(frozen=True)
class NoComprobable:
    campo: str
    que: str
    por_que: str
    que_hacer: str


@dataclass(frozen=True)
class Veredicto:
    nivel: str
    titulo: str
    subtitulo: str
    razon: str


@dataclass(frozen=True)
class Resultado:
    veredicto: Veredicto
    hallazgos: list[Hallazgo]
    no_comprobables: list[NoComprobable]
    pasos: list[str]


# --- Utilidades --------------------------------------------------------------------------------

def normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", " ", sin_tildes.lower()).strip()


def buscar_entidad(nombre: str, entidades: list[Entidad]) -> Entidad | None:
    """La entidad de nuestra lista que el mensaje dice ser («Banco de Crédito BCP» → BCP)."""
    palabras = set(normalizar(nombre).split())
    compacto = normalizar(nombre).replace(" ", "")
    if not compacto:
        return None
    for entidad in entidades:
        if normalizar(entidad.nombre).replace(" ", "") in compacto:
            return entidad
        for clave in entidad.palabras:
            if clave in palabras or (len(clave) >= 5 and clave in compacto):
                return entidad
    return None


def host_de(url: str) -> str:
    url = url.strip().strip("<>()[]\"'")
    if not re.match(r"^[a-z]+://", url, re.I):
        url = "http://" + url
    try:
        return (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def dominio_registrable(host: str) -> str:
    partes = host.split(".")
    if len(partes) >= 3 and ".".join(partes[-2:]) in SUFIJOS_DOBLES:
        return ".".join(partes[-3:])
    return ".".join(partes[-2:])


def es_oficial(host: str, entidad: Entidad) -> bool:
    return any(host == d or host.endswith("." + d) for d in entidad.dominios)


def es_del_estado(host: str) -> bool:
    return host == "gob.pe" or host.endswith(".gob.pe")


def imita_a(host: str, entidades: list[Entidad]) -> Entidad | None:
    """Entidad cuyo nombre aparece en un dominio que no es suyo (viabcp-seguro.com → BCP)."""
    etiquetas = re.split(r"[.\-]", host)
    plano = re.sub(r"[.\-]", "", host)
    for entidad in entidades:
        if es_oficial(host, entidad):
            continue
        for clave in entidad.palabras:
            if len(clave) >= 5 and clave in plano:
                return entidad
            if len(clave) < 5 and any(e.startswith(clave) or e.endswith(clave) for e in etiquetas):
                return entidad
    return None


def ruc_valido(ruc: str) -> bool:
    """Dígito verificador del RUC de SUNAT (módulo 11)."""
    digitos = re.sub(r"\D", "", ruc)
    if len(digitos) != 11 or digitos[:2] not in {"10", "15", "16", "17", "20"}:
        return False
    suma = sum(int(d) * p for d, p in zip(digitos[:10], (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)))
    verificador = 11 - suma % 11
    verificador = {10: 0, 11: 1}.get(verificador, verificador)
    return verificador == int(digitos[10])


@lru_cache(maxsize=512)
def edad_dominio_dias(dominio: str, hoy: date | None = None) -> int | None:
    """Días desde que se registró el dominio, según RDAP (registro público de dominios).

    NIC.pe no ofrece RDAP, así que los dominios .pe devuelven None (no comprobable).
    """
    if dominio.endswith(".pe"):
        return None
    try:
        respuesta = requests.get(f"https://rdap.org/domain/{dominio}", timeout=8,
                                 headers={"Accept": "application/rdap+json"})
        if respuesta.status_code != 200:
            return None
        for evento in respuesta.json().get("events", []):
            if evento.get("eventAction") == "registration":
                registro = date.fromisoformat(evento["eventDate"][:10])
                return ((hoy or date.today()) - registro).days
    except (requests.RequestException, ValueError, KeyError):
        return None
    return None


# --- Revisión por campo ------------------------------------------------------------------------

def revisar_link(url: str, entidades: list[Entidad], dice_ser: Entidad | None, dice_ser_estado: bool,
                 edad: Callable[[str], int | None]) -> tuple[list[Hallazgo], list[NoComprobable]]:
    host = host_de(url)
    if not host or "." not in host:
        return [], []
    dominio = dominio_registrable(host)
    hallazgos: list[Hallazgo] = []
    oficial = False

    if dice_ser and es_oficial(host, dice_ser):
        oficial = True
        hallazgos.append(Hallazgo("Link", A_FAVOR, PRUEBA, f"El link es de la web oficial de {dice_ser.nombre}",
                                  "Aun así, es más seguro escribir usted mismo la dirección o usar la app oficial.",
                                  FUENTE_DOMINIOS))
    elif dice_ser_estado and not es_del_estado(host):
        hallazgos.append(Hallazgo("Link", EN_CONTRA, PRUEBA, "El link no es del Estado peruano",
                                  f"Las entidades del Estado usan direcciones que terminan en .gob.pe. "
                                  f"Este link lleva a {dominio}.", "Regla del dominio .gob.pe"))
    elif dice_ser:
        hallazgos.append(Hallazgo("Link", EN_CONTRA, PRUEBA, f"El link no es de {dice_ser.nombre}",
                                  f"La web oficial de {dice_ser.nombre} es {dice_ser.dominios[0]}. "
                                  f"Este link lleva a {dominio}.", FUENTE_DOMINIOS))
    elif (imitada := imita_a(host, entidades)) is not None:
        hallazgos.append(Hallazgo("Link", EN_CONTRA, PRUEBA, f"El link imita a {imitada.nombre}",
                                  f"Usa el nombre de {imitada.nombre}, pero su web oficial es "
                                  f"{imitada.dominios[0]}. Este link lleva a {dominio}.", FUENTE_DOMINIOS))
    elif es_del_estado(host) or any(es_oficial(host, e) for e in entidades):
        oficial = True

    if oficial:
        return hallazgos, []

    if host in ACORTADORES or dominio in ACORTADORES:
        hallazgos.append(Hallazgo("Link", EN_CONTRA, SENAL, "El link está acortado",
                                  f"{host} esconde a qué página lo lleva.", "Lista de acortadores conocidos"))
    elif re.fullmatch(r"[\d.]+", host):
        hallazgos.append(Hallazgo("Link", EN_CONTRA, SENAL, "El link es un número, no una web",
                                  "Las entidades reales no usan direcciones numéricas.", "Formato del link"))
    else:
        dias = edad(dominio)
        if dias is not None and dias < DIAS_DOMINIO_NUEVO:
            hallazgos.append(Hallazgo("Link", EN_CONTRA, SENAL, f"La web {dominio} se creó hace {dias} días",
                                      "Las entidades reales tienen webs de años. Las estafas crean webs nuevas.",
                                      "RDAP, el registro público de dominios (consulta en vivo)"))

    por_que = "No abrimos links sospechosos, por seguridad."
    if dominio.endswith(".pe"):
        por_que += " Y NIC.pe no publica cuándo se creó un dominio .pe."
    return hallazgos, [NoComprobable("Link", f"Qué hay dentro de {dominio}", por_que,
                                     "No lo abra. Escriba usted mismo la dirección oficial.")]


def revisar_ruc(ruc: str) -> tuple[list[Hallazgo], list[NoComprobable]]:
    digitos = re.sub(r"\D", "", ruc)
    if not digitos:
        return [], []
    if not ruc_valido(digitos):
        return [Hallazgo("RUC", EN_CONTRA, PRUEBA, f"El RUC {digitos} es inventado",
                         "Todo RUC tiene 11 dígitos y el último se calcula con los otros diez. Este no cuadra.",
                         "Dígito verificador de SUNAT (módulo 11)")], []
    return ([Hallazgo("RUC", A_FAVOR, PRUEBA, f"El RUC {digitos} es un número válido",
                      "Pero eso no dice si la empresa existe ni si es la que le escribe.",
                      "Dígito verificador de SUNAT (módulo 11)")],
            [NoComprobable("RUC", f"Si la empresa del RUC {digitos} existe y está activa",
                           "La consulta de SUNAT tiene captcha; la sumaremos en la versión 2.",
                           "Consulte el RUC en la web de SUNAT.")])


def revisar_telefono(telefono: str, dice_ser: Entidad | None) -> tuple[list[Hallazgo], list[NoComprobable]]:
    digitos = re.sub(r"\D", "", telefono)
    if len(digitos) < 7:
        return [], []  # número tapado o incompleto
    hallazgos = []
    if telefono.strip().startswith("+") and not digitos.startswith("51"):
        hallazgos.append(Hallazgo("Teléfono", EN_CONTRA, SENAL, f"El número {telefono.strip()} es del extranjero",
                                  "Los bancos y entidades peruanas no le escriben desde números de otros países.",
                                  "Código de país del número"))
    else:
        local = digitos[2:] if len(digitos) == 11 and digitos.startswith("51") else digitos
        if dice_ser and len(local) == 9 and local.startswith("9"):
            hallazgos.append(Hallazgo("Teléfono", EN_CONTRA, SENAL,
                                      f"Dice ser {dice_ser.nombre}, pero escribe desde un celular",
                                      "Desconfíe: los bancos y el Estado no piden datos ni pagos desde un celular.",
                                      "Formato del número peruano (+51 9…)"))
    return hallazgos, [NoComprobable("Teléfono", f"De quién es el número {telefono.strip()}",
                                     "No hay un registro público de dueños de números: es un dato personal.",
                                     "Cuelgue y llame usted al número que está detrás de su tarjeta.")]


_PEDIDOS_PROHIBIDOS = {
    Pedido.clave_o_pin: "su clave o PIN",
    Pedido.codigo_por_sms: "el código que le llegó por SMS",
    Pedido.datos_de_tarjeta: "los datos de su tarjeta",
}
_PAGO_ADELANTADO = {Tipo.prestamo: "un préstamo", Tipo.premio_o_sorteo: "un premio", Tipo.trabajo: "un trabajo"}


def revisar_pedidos(mensaje: Mensaje) -> list[Hallazgo]:
    hallazgos = []
    for pedido, texto in _PEDIDOS_PROHIBIDOS.items():
        if pedido in mensaje.te_piden:
            hallazgos.append(Hallazgo("Lo que le piden", EN_CONTRA, REGLA, f"Le piden {texto}",
                                      "Ningún banco, Yape ni entidad del Estado le pide esto por mensaje o llamada. "
                                      "Con eso pueden vaciar su cuenta.", "Regla de los bancos y la SBS"))
    if Pedido.pago_o_deposito in mensaje.te_piden and mensaje.tipo in _PAGO_ADELANTADO:
        que = _PAGO_ADELANTADO[mensaje.tipo]
        hallazgos.append(Hallazgo("Lo que le piden", EN_CONTRA, REGLA, f"Le cobran por adelantado por {que}",
                                  "Ninguna entidad formal cobra por adelantado para darle un préstamo, "
                                  "un premio o un trabajo.", "Regla de las entidades formales"))
    if Pedido.instalar_una_app in mensaje.te_piden:
        hallazgos.append(Hallazgo("Lo que le piden", EN_CONTRA, SENAL, "Le piden instalar una aplicación",
                                  "Con algunas apps los estafadores controlan su celular.", FUENTE_IA))
    if Pedido.foto_de_dni_o_datos_personales in mensaje.te_piden:
        hallazgos.append(Hallazgo("Lo que le piden", EN_CONTRA, SENAL, "Le piden su DNI o datos personales",
                                  "Con su DNI pueden sacar préstamos o líneas a su nombre.", FUENTE_IA))
    return hallazgos


_SENALES = {
    TipoSenal.urgencia_o_amenaza: "Le meten prisa o lo amenazan",
    TipoSenal.premio_o_ganancia_inesperada: "Le ofrecen un premio o una ganancia que no buscó",
    TipoSenal.numero_nuevo_de_familiar: "Un «familiar» con número nuevo",
    TipoSenal.oferta_demasiado_buena: "Una oferta demasiado buena",
    TipoSenal.pide_secreto: "Le piden que no le cuente a nadie",
    TipoSenal.escribe_desde_numero_personal: "Una empresa que escribe desde un número personal",
}


def revisar_senales(mensaje: Mensaje) -> list[Hallazgo]:
    vistos, hallazgos = set(), []
    for senal in mensaje.senales:
        if senal.tipo in vistos:
            continue
        vistos.add(senal.tipo)
        hallazgos.append(Hallazgo("El mensaje", EN_CONTRA, SENAL, _SENALES[senal.tipo],
                                  f"«{senal.cita.strip()}»", FUENTE_IA))
    return hallazgos


def revisar_registro_sbs(mensaje: Mensaje, conocida: Entidad | None,
                         registro: RegistroSBS | None) -> tuple[list[Hallazgo], list[NoComprobable]]:
    nombre = mensaje.entidad_que_dice_ser.strip()
    if mensaje.tipo not in (Tipo.prestamo, Tipo.inversion) or not nombre or conocida is not None:
        return [], []
    if registro is None:
        return [], [NoComprobable("Empresa", f"Si «{nombre}» está registrada en la SBS",
                                  "Esta versión todavía no tiene cargado el registro de la SBS.",
                                  "Búsquela en la web de la SBS antes de pagar nada.")]
    buscado = normalizar(nombre)
    for candidato in registro.nombres:
        if SequenceMatcher(None, buscado, normalizar(candidato)).ratio() >= 0.85:
            return [Hallazgo("Empresa", A_FAVOR, PRUEBA, f"«{candidato}» figura en el registro de la SBS",
                             "Pero los estafadores usan nombres de empresas reales: llame a su central oficial.",
                             f"{registro.fuente} ({registro.fecha})")], []
    return [Hallazgo("Empresa", EN_CONTRA, SENAL, f"«{nombre}» no figura en el registro de la SBS",
                     "Las empresas que prestan dinero o reciben inversiones del público deben estar "
                     "registradas o autorizadas por la SBS.", f"{registro.fuente} ({registro.fecha})")], []


def otros_no_comprobables(mensaje: Mensaje, conocida: Entidad | None) -> list[NoComprobable]:
    lista = [NoComprobable("Cuenta o Yape", f"De quién es {cuenta}", "Secreto bancario: nadie puede consultarlo.",
                           "No deposite. Si conoce a la persona, llámela a su número de siempre.")
             for cuenta in mensaje.cuentas_o_numeros_de_pago]
    if mensaje.tipo == Tipo.comprobante_de_pago:
        lista.append(NoComprobable("Comprobante", "Si el pago del voucher es real",
                                   "No tenemos acceso a los bancos y los vouchers se editan fácil.",
                                   "Revise el movimiento en su propia app de Yape o del banco, no en la foto."))
    if mensaje.tipo == Tipo.familiar_en_apuros or any(
            s.tipo == TipoSenal.numero_nuevo_de_familiar for s in mensaje.senales):
        lista.append(NoComprobable("Familiar", "Si su familiar de verdad cambió de número", "Solo su familiar lo sabe.",
                                   "Llámelo a su número de siempre o pregúntele algo que solo él o ella sabría."))
    if mensaje.tipo == Tipo.aviso_de_banco_o_billetera and conocida is not None:
        lista.append(NoComprobable("Asesor", f"Si quien le escribe trabaja de verdad en {conocida.nombre}",
                                   "No hay un registro público de empleados.",
                                   "Cuelgue y llame a la central oficial."))
    return lista


# --- Veredicto y pasos -------------------------------------------------------------------------

_ORDEN = {(EN_CONTRA, PRUEBA): 0, (EN_CONTRA, REGLA): 0, (EN_CONTRA, SENAL): 1,
          (A_FAVOR, PRUEBA): 2, (A_FAVOR, REGLA): 2, (A_FAVOR, SENAL): 2}


def decidir(hallazgos: list[Hallazgo]) -> Veredicto:
    en_contra = [h for h in hallazgos if h.resultado == EN_CONTRA]
    fuertes = [h for h in en_contra if h.fuerza in (PRUEBA, REGLA)]
    if fuertes:
        return Veredicto(ROJO, "Es una estafa", "No haga nada de lo que le piden.", fuertes[0].titulo)
    if en_contra:
        return Veredicto(NARANJA, "Muy sospechoso", "No pague ni dé datos hasta comprobarlo.", en_contra[0].titulo)
    return Veredicto(AMARILLO, "No pudimos comprobarlo",
                     "No encontramos pruebas de estafa, pero eso no quiere decir que sea seguro.",
                     "Revise abajo lo que no podemos comprobar y cómo hacerlo usted.")


def pasos(mensaje: Mensaje, veredicto: Veredicto, conocida: Entidad | None) -> list[str]:
    lista = []
    if veredicto.nivel in (ROJO, NARANJA):
        lista.append("No responda, no pague y no dé claves ni códigos.")
    if mensaje.links:
        lista.append("No abra el link. Para entrar a su banco, use la app oficial o escriba usted la dirección.")
    if mensaje.tipo == Tipo.familiar_en_apuros:
        lista.append("Antes de enviar dinero, llame a su familiar a su número de siempre.")
    if mensaje.tipo == Tipo.aviso_de_banco_o_billetera or (conocida and conocida.tipo in ("banco", "billetera", "caja")):
        lista.append("Si tiene dudas, llame al número que está detrás de su tarjeta.")
    if mensaje.tipo == Tipo.entidad_del_estado:
        lista.append("Entre usted mismo a gob.pe para ver si tiene algún trámite pendiente.")
    if mensaje.tipo in (Tipo.prestamo, Tipo.inversion):
        lista.append("Busque la empresa en la web de la SBS antes de pagar nada.")
    if mensaje.tipo == Tipo.trabajo:
        lista.append("Un trabajo serio no le cobra por inscripción, capacitación ni uniforme.")
    if mensaje.tipo == Tipo.comprobante_de_pago:
        lista.append("Revise en su propia app si de verdad le llegó el dinero.")
    lista = lista[:3]
    lista.append("Si ya pagó o dio datos: llame de inmediato a su banco para bloquear y denuncie en la comisaría.")
    return lista


def analizar(mensaje: Mensaje, entidades: list[Entidad], registro: RegistroSBS | None = None,
             edad: Callable[[str], int | None] = edad_dominio_dias) -> Resultado:
    conocida = buscar_entidad(mensaje.entidad_que_dice_ser, entidades) if mensaje.entidad_que_dice_ser else None
    dice_ser_estado = mensaje.tipo == Tipo.entidad_del_estado or (conocida is not None and conocida.tipo == "estado")

    hallazgos: list[Hallazgo] = []
    no_comprobables: list[NoComprobable] = []

    def sumar(resultado: tuple[list[Hallazgo], list[NoComprobable]]) -> None:
        hallazgos.extend(resultado[0])
        no_comprobables.extend(resultado[1])

    for url in dict.fromkeys(mensaje.links):
        sumar(revisar_link(url, entidades, conocida, dice_ser_estado, edad))
    for ruc in dict.fromkeys(mensaje.rucs):
        sumar(revisar_ruc(ruc))
    for telefono in dict.fromkeys(mensaje.telefonos):
        sumar(revisar_telefono(telefono, conocida))
    hallazgos.extend(revisar_pedidos(mensaje))
    hallazgos.extend(revisar_senales(mensaje))
    sumar(revisar_registro_sbs(mensaje, conocida, registro))
    no_comprobables.extend(otros_no_comprobables(mensaje, conocida))

    hallazgos.sort(key=lambda h: _ORDEN[(h.resultado, h.fuerza)])
    veredicto = decidir(hallazgos)
    return Resultado(veredicto, hallazgos, no_comprobables, pasos(mensaje, veredicto, conocida))
