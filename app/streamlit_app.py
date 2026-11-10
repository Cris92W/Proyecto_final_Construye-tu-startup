"""Pillao: ¿es estafa? Revisa un mensaje sospechoso y separa lo que se pudo comprobar de lo que no.

Correr en local:  uv run streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import hashlib
import html
import os
import re
from pathlib import Path
from urllib.parse import quote

import streamlit as st
from dotenv import load_dotenv

from pillao import verificar
from pillao.llm import ClienteLLM

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

REPO = "https://github.com/Cris92W/Proyecto_final_Construye-tu-startup"
TIPO_CAMBIO = 3.75  # soles por dólar, referencial

# Recreados a partir de modalidades de estafa difundidas públicamente; nombres, números y cuentas son ficticios.
EJEMPLOS = {
    "«Su cuenta será bloqueada» (banco)": (
        "BCP: Estimado cliente, detectamos un consumo inusual de S/ 1,850.00 con su tarjeta. Si no lo reconoce, "
        "valide su identidad en las próximas 2 horas en viabcp-validacion.com o su cuenta será bloqueada. "
        "Le llegará un código por SMS: ingréselo en la página para anular la operación."),
    "«Mamá, este es mi número nuevo»": (
        "Hola ma, soy yo, este es mi número nuevo, el otro se me malogró, guárdalo. Oye estoy en un apuro, "
        "¿me puedes yapear S/ 480 a este número 9XX XXX XXX? Es de un amigo, mañana sin falta te devuelvo. "
        "No le digas nada a papá todavía 🙏"),
    "Préstamo sin Infocorp": (
        "💰 PRÉSTAMOS RÁPIDOS SIN INFOCORP 💰 De S/ 1,000 a S/ 30,000 en 24 horas, sin aval y sin revisar tu "
        "historial. Solo necesitas tu DNI. Para activar tu préstamo deposita S/ 150 de gastos administrativos "
        "a nuestra cuenta BCP 191-XXXXXXX-0-XX. Préstamos Andinos Express S.A.C. RUC 20612345678. "
        "Escríbenos al +51 9XX XXX XXX"),
    "Paquete retenido (Serpost)": (
        "SERPOST: Su paquete N° PE2611093 está retenido por falta de pago de la tasa aduanera (S/ 8.90). "
        "Pague antes de 24 horas en serpost-pe.top/pagar o será devuelto al remitente."),
}

ICONO = {verificar.ROJO: "🔴", verificar.NARANJA: "🟠", verificar.AMARILLO: "🟡"}
FUERZA = {verificar.PRUEBA: "Prueba", verificar.REGLA: "Regla", verificar.SENAL: "Señal"}

st.set_page_config(page_title="Pillao · ¿Es estafa?", page_icon="🛡️", layout="centered")
st.markdown("""
<style>
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li { font-size: 1.15rem; }
.stButton button p, .stLinkButton a p { font-size: 1.2rem; font-weight: 600; }
.veredicto { border-radius: 18px; padding: 1.1rem 1.4rem; margin: .5rem 0 1rem 0; color: #111; }
.veredicto h2 { margin: 0; padding: 0; font-size: 2.2rem; color: #111; }
.veredicto p { margin: .35rem 0 0 0; font-size: 1.25rem !important; color: #111; }
.rojo { background: #fde2e1; border: 3px solid #c62828; }
.naranja { background: #ffe9cc; border: 3px solid #ef6c00; }
.amarillo { background: #fff7c2; border: 3px solid #b28704; }
</style>
""", unsafe_allow_html=True)


def _secreto(nombre: str) -> str | None:
    try:
        if nombre in st.secrets:
            return st.secrets[nombre]
    except Exception:  # sin secrets.toml en local
        pass
    return os.getenv(nombre)


def desactivar_links(texto: str) -> str:
    """Evita que un link del estafador se muestre como link que se puede tocar."""
    texto = texto.replace("://", ":/\u200b/")
    return re.sub(r"([A-Za-z0-9-])\.([A-Za-z])", "\\1.\u200b\\2", texto)


def seguro(texto: str) -> str:
    """Texto que viene del mensaje → markdown sin formato inyectado y sin links activos."""
    return desactivar_links(re.sub(r"([\\`*_\[\]()#<>|])", r"\\\1", texto))


@st.cache_resource
def entidades():
    return verificar.cargar_entidades()


@st.cache_resource
def registro_sbs():
    return verificar.cargar_registro_sbs()


def mostrar(mensaje, resultado, uso, modelo) -> None:
    v = resultado.veredicto
    st.markdown(
        f'<div class="veredicto {v.nivel}"><h2>{ICONO[v.nivel]} {html.escape(v.titulo)}</h2>'
        f'<p><b>{html.escape(v.subtitulo)}</b></p>'
        f'<p>Motivo principal: {desactivar_links(html.escape(v.razon))}</p></div>',
        unsafe_allow_html=True)

    st.markdown("### Qué hacer ahora")
    st.markdown("\n".join(f"{i}. {paso}" for i, paso in enumerate(resultado.pasos, 1)))

    aviso = (f"Me llegó un mensaje y lo revisé con Pillao: {ICONO[v.nivel]} {v.titulo}. "
             f"Motivo: {desactivar_links(v.razon)}. ¿Me ayudas a revisarlo?")
    st.link_button("📲 Avisar a mi familia por WhatsApp", f"https://wa.me/?text={quote(aviso)}",
                   use_container_width=True)

    st.markdown("### Lo que comprobamos")
    if not resultado.hallazgos:
        st.markdown("No encontramos datos que se puedan comprobar en este mensaje.")
    for h in resultado.hallazgos:
        icono = "❌" if h.resultado == verificar.EN_CONTRA else "✅"
        with st.container(border=True):
            st.markdown(f"{icono} **{seguro(h.titulo)}**  \n{seguro(h.detalle)}")
            st.caption(f"{FUERZA[h.fuerza]} · Fuente: {h.fuente}")

    if resultado.no_comprobables:
        st.markdown("### Lo que no podemos comprobar (y cómo hacerlo usted)")
        for n in resultado.no_comprobables:
            with st.container(border=True):
                st.markdown(f"❔ **{seguro(n.que)}**  \n{seguro(n.por_que)}  \n👉 **Qué hacer:** {seguro(n.que_hacer)}")

    with st.expander("Lo que leyó la IA en el mensaje"):
        st.text(desactivar_links(mensaje.transcripcion))
        campos = {
            "Tipo de mensaje": mensaje.tipo.value.replace("_", " "),
            "Dice ser": mensaje.entidad_que_dice_ser,
            "Remitente": mensaje.remitente,
            "Links": ", ".join(mensaje.links),
            "Teléfonos": ", ".join(mensaje.telefonos),
            "RUC": ", ".join(mensaje.rucs),
            "Cuentas o Yape": ", ".join(mensaje.cuentas_o_numeros_de_pago),
            "Monto": mensaje.monto,
            "Le piden": ", ".join(p.value.replace("_", " ") for p in mensaje.te_piden),
        }
        st.table({"Campo": list(campos), "Valor": [desactivar_links(x) or "—" for x in campos.values()]})

    with st.expander("Cómo decidimos"):
        st.markdown(
            "La IA (Gemini) **solo lee** el mensaje y copia sus datos con las frases exactas. "
            "El veredicto lo deciden **reglas escritas en Python** que se pueden revisar:\n\n"
            "- 🔴 **Es una estafa:** hay una *prueba* (por ejemplo, el link no es del banco) o algo que una entidad "
            "formal *nunca* hace (pedir el código SMS, cobrar por adelantado un préstamo).\n"
            "- 🟠 **Muy sospechoso:** hay *señales* típicas de estafa, pero ninguna prueba.\n"
            "- 🟡 **No pudimos comprobarlo:** no hay pruebas ni señales. **Nunca decimos que algo es seguro.**\n\n"
            f"El detalle de qué comprobamos y qué no está en [docs/alcance.md]({REPO}/blob/main/docs/alcance.md).")

    with st.expander("Cuánto costó esta revisión"):
        costo = uso.costo_usd(modelo)
        st.markdown(f"{uso.llamadas} llamada al modelo `{modelo}`: {uso.tokens_entrada:,} tokens de entrada y "
                    f"{uso.tokens_salida:,} de salida.")
        if costo is not None:
            st.markdown(f"Con el precio de lista del plan de pago: **US$ {costo:.4f}** "
                        f"(S/ {costo * TIPO_CAMBIO:.3f}). Las comprobaciones (dominios, RUC, RDAP) no cuestan.")


# --- Página ------------------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 🛡️ Pillao")
    st.markdown("Revisa mensajes sospechosos y le dice **qué pudo comprobar y qué no**, en palabras simples.")
    st.markdown(f"[Qué comprobamos y qué no]({REPO}/blob/main/docs/alcance.md)  \n[Código en GitHub]({REPO})")
    st.caption("Proyecto final de la Diplomatura de Ciencia de Datos (Q-Lab PUCP, 2026). "
               "Pillao no reemplaza a su banco ni a la policía.")

st.title("🛡️ Pillao")
st.markdown("### ¿Le llegó un mensaje raro? Revíselo antes de responder.")
st.markdown("Suba la captura de pantalla o pegue el texto. Le decimos qué tiene de sospechoso, "
            "qué pudimos comprobar y qué no.")

forma = st.radio("¿Cómo quiere revisar el mensaje?",
                 ["📷 Subir una captura", "✍️ Pegar el texto", "🧪 Ver un ejemplo"], horizontal=True)
imagen, tipo_imagen, texto = None, "image/png", ""
if forma.startswith("📷"):
    archivo = st.file_uploader("Captura de pantalla del mensaje", type=["png", "jpg", "jpeg", "webp"])
    if archivo is not None:
        imagen, tipo_imagen = archivo.getvalue(), archivo.type or "image/png"
        st.image(imagen, width=300)
elif forma.startswith("✍️"):
    texto = st.text_area("Texto del mensaje", height=180, placeholder="Copie y pegue aquí el mensaje que le llegó")
else:
    elegido = st.selectbox("Elija un ejemplo", list(EJEMPLOS))
    texto = EJEMPLOS[elegido]
    st.info(desactivar_links(texto))
    st.caption("Ejemplos recreados a partir de modalidades de estafa difundidas públicamente. "
               "Los nombres, números y cuentas son ficticios.")

st.caption("🔒 El mensaje se revisa en memoria y no se guarda. Si puede, tape los números de otras personas.")

clave = _secreto("GEMINI_API_KEY")
if not clave:
    st.warning("Falta la clave `GEMINI_API_KEY`: póngala en `.env` (local) o en los Secrets de Streamlit Cloud.")

huella = hashlib.sha256((imagen or b"") + texto.encode()).hexdigest()
listo = bool(clave) and (imagen is not None or bool(texto.strip()))
if st.button("🔍 Revisar el mensaje", type="primary", use_container_width=True, disabled=not listo):
    with st.spinner("Leyendo el mensaje y comprobando cada dato…"):
        cliente = ClienteLLM(api_key=clave, modelo=_secreto("GEMINI_MODEL"))
        try:
            mensaje = cliente.leer(imagen, tipo_imagen, texto)
        except Exception as error:  # se muestra a la persona en vez de romper la página
            st.error(f"No pudimos leer el mensaje. Intente de nuevo en un minuto. ({type(error).__name__})")
            st.stop()
        resultado = verificar.analizar(mensaje, entidades(), registro_sbs())
    st.session_state["revision"] = (huella, mensaje, resultado, cliente.uso, cliente.modelo)

revision = st.session_state.get("revision")
if revision and revision[0] == huella:
    mostrar(*revision[1:])
