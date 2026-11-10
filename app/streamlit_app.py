"""Pillao: ¿es estafa? Revisa un mensaje sospechoso y separa lo que se pudo comprobar de lo que no.

Dos pantallas: la de entrada (subir la captura o pegar el texto) y la del resultado, en carrusel:
una diapositiva por paso (veredicto, qué hacer, pruebas, lo que no se puede comprobar, cómo decidimos).

Correr en local:  uv run streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import html
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

import streamlit as st
from dotenv import load_dotenv

from pillao import verificar
from pillao.llm import ClienteLLM

APP = Path(__file__).resolve().parent
RAIZ = APP.parent
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
    "WhatsApp: «te envié un código por error»": (
        "Holaa! Disculpa, te envié un código de 6 dígitos a tu número por error 😅 ¿me lo puedes pasar porfa? "
        "Es urgente, es para entrar a mi WhatsApp."),
    "WhatsApp: trabajo por dar «me gusta»": (
        "Hola, soy Andrea de una agencia de marketing digital. Tenemos un trabajo a tiempo parcial desde casa: "
        "gana de S/ 150 a S/ 500 al día dando «me gusta» a videos de YouTube. Te pagamos S/ 10 por cada tarea. "
        "Para pasar a las tareas VIP debes hacer un depósito de S/ 80, que se te devuelve con tu comisión. "
        "Escríbeme a +62 8XX XXXX XXXX"),
    "Yape: «le yapeé por error»": (
        "Hola señora, disculpe la molestia, le acabo de yapear S/ 250 por error, era para mi mamá 🙏 "
        "¿Me lo puede devolver a este número 9XX XXX XXX? Le mando la captura del yapeo. Gracias, Dios le bendiga."),
}

ICONO = {verificar.ROJO: "🔴", verificar.NARANJA: "🟠", verificar.AMARILLO: "🟡"}
ESCALA = {verificar.ROJO: "Estafa", verificar.NARANJA: "Muy sospechoso", verificar.AMARILLO: "No comprobado"}
FUERZA = {verificar.PRUEBA: "Prueba", verificar.REGLA: "Regla", verificar.SENAL: "Señal"}
CLASE_FUERZA = {verificar.PRUEBA: "prueba", verificar.REGLA: "regla", verificar.SENAL: "senal"}

ESCUDO = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
          'stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'
          '<path d="M12 8v4"/><path d="M12 16h.01"/></svg>')
BANDERA = '<span class="bandera" role="img" aria-label="Bandera del Perú"><i></i><i></i><i></i></span>'


def bloque(fragmento: str) -> None:
    """Muestra HTML propio en una sola línea, para que Markdown no lo confunda con un bloque de código."""
    st.markdown(" ".join(linea.strip() for linea in fragmento.splitlines() if linea.strip()),
                unsafe_allow_html=True)


def desactivar_links(texto: str) -> str:
    """Evita que un link del estafador se muestre como link que se puede tocar."""
    texto = texto.replace("://", ":/\u200b/")
    return re.sub(r"([A-Za-z0-9-])\.([A-Za-z])", "\\1.\u200b\\2", texto)


def limpio(texto: str | None) -> str:
    """Texto del mensaje o de las reglas → HTML sin etiquetas inyectadas y sin links activos."""
    return desactivar_links(html.escape(texto or ""))


# --- Clave de Gemini ---------------------------------------------------------------------------

def _buscar(secretos, nombre: str):
    """Busca la clave sin importar mayúsculas, también dentro de una sección como [gemini]."""
    for k, v in secretos.items():
        if hasattr(v, "items"):
            encontrado = _buscar(v, nombre)
            if encontrado is not None:
                return encontrado
        elif str(k).strip().upper() == nombre:
            return v
    return None


def _limpiar(valor, nombre: str) -> str | None:
    """Quita espacios, comillas y un «NOMBRE=» pegado por error dentro del valor."""
    if not isinstance(valor, str):
        return None
    valor = valor.strip().strip("\"'").strip()
    if valor.upper().startswith(nombre + "="):
        valor = valor.split("=", 1)[1].strip().strip("\"'").strip()
    return valor or None


def _secreto(nombre: str) -> str | None:
    try:
        valor = _buscar(st.secrets, nombre)
    except Exception:  # sin secrets.toml (normal en local) o con un error de formato
        valor = None
    return _limpiar(valor, nombre) or _limpiar(os.getenv(nombre), nombre)


def _problema_con_la_clave() -> str:
    """Dice qué arreglar cuando no hay clave, sin mostrar ningún valor."""
    formato = '`GEMINI_API_KEY = "su-clave"` (con comillas)'
    try:
        nombres = [str(k) for k in st.secrets.keys()]
    except Exception as error:
        if "pars" in str(error).lower():
            return f"Los **Secrets** de Streamlit tienen un error de formato. Escriba la línea así: {formato}."
        return ("Falta la clave de Gemini. En local va en el archivo `.env`; en Streamlit Cloud, en "
                f"**Manage app → ⋮ → Settings → Secrets**, así: {formato}.")
    if any(n.strip().upper() == "GEMINI_API_KEY" for n in nombres):
        return "La línea `GEMINI_API_KEY` está en los **Secrets**, pero vacía: pegue la clave entre las comillas."
    if not nombres:
        return f"Los **Secrets** de Streamlit están vacíos. Escriba: {formato}."
    return (f"En los **Secrets** no está `GEMINI_API_KEY` (encontramos: {', '.join(nombres)}). "
            f"Escriba la línea así: {formato}.")


@st.cache_resource
def entidades():
    return verificar.cargar_entidades()


@st.cache_resource
def registro_sbs():
    return verificar.cargar_registro_sbs()


# --- Navegación --------------------------------------------------------------------------------

def ir_a(diapo: int) -> None:
    st.session_state["diapo"] = diapo


def revisar_otro() -> None:
    st.session_state["vista"] = "entrada"
    st.session_state.pop("revision", None)


def volver_arriba() -> None:
    """Lleva la página arriba al cambiar de pantalla y activa el deslizar y las flechas del teclado."""
    st.session_state["_vuelta"] = st.session_state.get("_vuelta", 0) + 1
    st.html(f"<script>/* {st.session_state['_vuelta']} */\n{(APP / 'carrusel.js').read_text(encoding='utf-8')}"
            "</script>", unsafe_allow_javascript=True)


# --- Pantalla 1: entrada -----------------------------------------------------------------------

def pantalla_entrada() -> None:
    bloque(f"""
        <div class="hero">
          <div>
            <div class="marca">{ESCUDO}<span>Pillao</span>
              <span class="etiqueta">{BANDERA}Solo para el Perú</span></div>
            <div class="hero-titulo">¿Le llegó un mensaje raro?<br><em>Revíselo antes de responder.</em></div>
            <p class="hero-texto">Suba la captura del WhatsApp o del SMS que le llegó en el Perú. En segundos le
              decimos si es estafa, con la prueba concreta, y qué no se puede comprobar.</p>
            <div class="chips"><span class="chip">Respuesta en segundos</span>
              <span class="chip">No guardamos su mensaje</span>
              <span class="chip">Nunca le diremos «es seguro»</span></div>
          </div>
          <div class="maqueta" aria-hidden="true">
            <div class="tel"><div class="pantalla">
              <div class="tel-barra"></div>
              <div class="sms-de">+51 9•• ••• •••</div>
              <div class="sms">Su cuenta será bloqueada hoy. Valide sus datos aquí: <u>banco-validacion.com</u></div>
            </div></div>
            <div class="sello"><span class="sello-punto"></span>
              <div><b>Es una estafa</b><small>El link no es del banco</small></div></div>
          </div>
        </div>""")

    with st.container(border=True, key="entrada"):
        bloque('<div class="sec">Revise su mensaje</div>')
        forma = st.radio("¿Cómo quiere revisar el mensaje?",
                         ["📷 Subir una captura", "✍️ Pegar el texto", "🧪 Ver un ejemplo"], horizontal=True)
        imagen, tipo_imagen, texto = None, "image/png", ""
        if forma.startswith("📷"):
            archivo = st.file_uploader("Captura de pantalla del mensaje", type=["png", "jpg", "jpeg", "webp"])
            if archivo is not None:
                imagen, tipo_imagen = archivo.getvalue(), archivo.type or "image/png"
                st.image(imagen, width=300)
        elif forma.startswith("✍️"):
            texto = st.text_area("Texto del mensaje", height=180,
                                 placeholder="Copie y pegue aquí el mensaje que le llegó")
        else:
            elegido = st.selectbox("Elija un ejemplo", list(EJEMPLOS))
            texto = EJEMPLOS[elegido]
            st.info(desactivar_links(texto))
            st.caption("Ejemplos recreados a partir de modalidades de estafa difundidas públicamente. "
                       "Los nombres, números y cuentas son ficticios.")

        st.caption("🔒 El mensaje se revisa en memoria y no se guarda. Si puede, tape los números de otras personas.")

        clave = _secreto("GEMINI_API_KEY")
        if not clave:
            st.warning(_problema_con_la_clave())

        listo = bool(clave) and (imagen is not None or bool(texto.strip()))
        pulsado = st.button("🔍 Revisar el mensaje", type="primary", use_container_width=True, disabled=not listo)

    if pulsado:
        inicio = time.perf_counter()
        with st.spinner("Leyendo el mensaje y comprobando cada dato…"):
            cliente = ClienteLLM(api_key=clave, modelo=_secreto("GEMINI_MODEL"))
            try:
                mensaje = cliente.leer(imagen, tipo_imagen, texto)
            except Exception as error:  # se muestra a la persona en vez de romper la página
                st.error(f"No pudimos leer el mensaje. Intente de nuevo en un minuto. ({type(error).__name__})")
                st.stop()
            resultado = verificar.analizar(mensaje, entidades(), registro_sbs())
        st.session_state["revision"] = {
            "mensaje": mensaje, "resultado": resultado, "uso": cliente.uso,
            "modelo": ", ".join(cliente.uso.modelos), "segundos": time.perf_counter() - inicio,
            "imagen": imagen, "texto": texto,
        }
        st.session_state["vista"], st.session_state["diapo"] = "resultado", 0
        st.rerun()

    bloque("""
        <div class="como">
          <div class="paso"><span class="n">1</span><div><b>Suba la captura</b>
            <div class="t">Del WhatsApp, del SMS o del correo. También puede pegar el texto.</div></div></div>
          <div class="paso"><span class="n">2</span><div><b>Leemos y comprobamos</b>
            <div class="t">La IA lee el mensaje y nuestras reglas revisan cada link, RUC y pedido.</div></div></div>
          <div class="paso"><span class="n">3</span><div><b>Le decimos qué hacer</b>
            <div class="t">Con la prueba concreta y lo que nadie puede comprobar.</div></div></div>
        </div>
        <div class="fuentes">Comprobamos contra fuentes públicas del Perú:
          <span class="f">Dominios oficiales</span><span class="f">RDAP en vivo</span>
          <span class="f">Registro de la SBS</span><span class="f">Dígito verificador del RUC</span></div>""")


# --- Pantalla 2: resultado en carrusel ---------------------------------------------------------

def diapo_veredicto(r: dict) -> None:
    v = r["resultado"].veredicto
    escala = "".join(f'<span class="{"on" if nivel == v.nivel else ""}">{nombre}</span>'
                     for nivel, nombre in ESCALA.items())
    bloque(f"""
        <div class="veredicto v-{v.nivel}">
          <div class="v-kicker"><span class="v-punto"></span>Veredicto de Pillao</div>
          <div class="v-titulo">{limpio(v.titulo)}</div>
          <div class="v-sub">{limpio(v.subtitulo)}</div>
          <div class="v-motivo"><b>Motivo principal</b>{limpio(v.razon)}</div>
          <div class="escala">{escala}</div>
          <div class="escala-nota">Pillao nunca dice que un mensaje es seguro: solo lo que pudo comprobar.</div>
        </div>""")
    with st.expander("Ver el mensaje que revisamos"):
        if r["imagen"]:
            st.image(r["imagen"], width=320)
        else:
            st.text(desactivar_links(r["texto"]))


def diapo_que_hacer(r: dict) -> None:
    resultado = r["resultado"]
    v = resultado.veredicto
    bloque('<ol class="pasos">' + "".join(f"<li>{limpio(paso)}</li>" for paso in resultado.pasos) + "</ol>")
    aviso = (f"Me llegó un mensaje y lo revisé con Pillao: {ICONO[v.nivel]} {v.titulo}. "
             f"Motivo: {desactivar_links(v.razon)}. ¿Me ayudas a revisarlo?")
    with st.container(key="avisar"):
        st.link_button("📲 Avisar a mi familia por WhatsApp", f"https://wa.me/?text={quote(aviso)}",
                       use_container_width=True)


def diapo_pruebas(r: dict) -> None:
    hallazgos = r["resultado"].hallazgos
    if not hallazgos:
        bloque('<div class="vacio">No encontramos datos que se puedan comprobar en este mensaje.</div>')
        return
    tarjetas = []
    for h in hallazgos:
        contra = h.resultado == verificar.EN_CONTRA
        tarjetas.append(f"""
            <div class="tarjeta {'t-contra' if contra else 't-favor'}">
              <div class="t-icono">{'✕' if contra else '✓'}</div>
              <div><div class="t-titulo">{limpio(h.titulo)}</div>
                <div class="t-detalle">{limpio(h.detalle)}</div>
                <div class="t-meta"><span class="pill {CLASE_FUERZA[h.fuerza]}">{FUERZA[h.fuerza]}</span>
                  Fuente: {limpio(h.fuente)}</div></div>
            </div>""")
    bloque("".join(tarjetas))


def diapo_no_comprobable(r: dict) -> None:
    bloque("".join(f"""
        <div class="tarjeta t-nc">
          <div class="t-icono">?</div>
          <div><div class="t-titulo">{limpio(n.que)}</div>
            <div class="t-detalle">{limpio(n.por_que)}</div>
            <div class="t-hacer"><b>Qué hacer:</b> {limpio(n.que_hacer)}</div></div>
        </div>""" for n in r["resultado"].no_comprobables))


def diapo_como_decidimos(r: dict) -> None:
    uso, mensaje = r["uso"], r["mensaje"]
    costo = uso.costo_usd()
    costo_txt = f"US$ {costo:.4f}" if costo is not None else "—"
    costo_sub = f"S/ {costo * TIPO_CAMBIO:.3f} por esta revisión" if costo is not None else "precio no publicado"
    bloque(f"""
        <div class="cifras">
          <div class="cifra"><b>{r['segundos']:.1f} s</b><span>tardó esta revisión</span></div>
          <div class="cifra"><b>{costo_txt}</b><span>{costo_sub}</span></div>
          <div class="cifra"><b>{uso.tokens_entrada + uso.tokens_salida:,}</b><span>tokens de {limpio(r['modelo'])}</span></div>
        </div>
        <div class="reglas">
          <p>La IA (Gemini) <b>solo lee</b> el mensaje y copia sus datos con las frases exactas.
            El veredicto lo deciden <b>reglas escritas en Python</b> que cualquiera puede revisar:</p>
          <ul>
            <li><b>Es una estafa:</b> hay una <i>prueba</i> (por ejemplo, el link no es del banco) o algo que una
              entidad formal <i>nunca</i> hace (pedir el código SMS, cobrar por adelantado un préstamo).</li>
            <li><b>Muy sospechoso:</b> hay <i>señales</i> típicas de estafa, pero ninguna prueba.</li>
            <li><b>No pudimos comprobarlo:</b> no hay pruebas ni señales. <b>Nunca decimos que algo es seguro.</b></li>
          </ul>
          <p><b>Solo para el Perú:</b> las reglas comparan con los dominios de bancos, cajas, billeteras y entidades
            del Estado peruano, el registro de la SBS y el RUC de la SUNAT. Con mensajes de otros países no sirve.</p>
          <p>El detalle está en <a href="{REPO}/blob/main/docs/alcance.md" target="_blank">qué comprobamos y qué no</a>.</p>
        </div>""")
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


def diapositivas(r: dict) -> list[tuple[str, str, str, object]]:
    """(título, nombre corto para el botón, introducción, función que la dibuja)."""
    lista = [
        ("Veredicto", "Veredicto", "", diapo_veredicto),
        ("Qué hacer ahora", "Qué hacer", "Siga estos pasos, en este orden.", diapo_que_hacer),
        ("Lo que comprobamos", "Las pruebas", "Cada dato del mensaje, comprobado contra una fuente.", diapo_pruebas),
    ]
    if r["resultado"].no_comprobables:
        lista.append(("Lo que no podemos comprobar", "Lo que no sabemos",
                      "Nadie puede comprobar esto por mensaje. Así puede hacerlo usted:", diapo_no_comprobable))
    lista.append(("Cómo lo decidimos", "Cómo decidimos", "", diapo_como_decidimos))
    return lista


def pantalla_resultado(r: dict) -> None:
    with st.container(key="barra"):
        izquierda, derecha = st.columns([3, 2])
        with izquierda:
            bloque(f'<div class="marca-barra">{ESCUDO}<span>Pillao</span></div>')
        with derecha:
            st.button("← Otro mensaje", type="tertiary", on_click=revisar_otro)

    lista = diapositivas(r)
    i = min(st.session_state.get("diapo", 0), len(lista) - 1)
    titulo, _, intro, dibujar = lista[i]
    segmentos = "".join(f'<span class="{"lleno" if k <= i else ""}"></span>' for k in range(len(lista)))
    bloque(f"""
        <div class="progreso">
          <div class="segmentos">{segmentos}</div>
          <div class="progreso-texto"><span class="cual">Paso {i + 1} de {len(lista)}</span>
            <span class="ayuda">Use los botones, las flechas ← → o deslice con el dedo</span></div>
        </div>""")

    with st.container(key=f"diapo-{i}"):
        if i > 0:
            bloque(f'<div class="titulo-diapo">{titulo}</div>' + (f'<p class="intro-diapo">{intro}</p>' if intro else ""))
        dibujar(r)

    with st.container(key="nav"):
        atras, siguiente = st.columns([1, 2])
        with atras:
            st.button("← Atrás", use_container_width=True, disabled=i == 0, on_click=ir_a, args=(i - 1,))
        with siguiente:
            if i + 1 < len(lista):
                st.button(f"Siguiente: {lista[i + 1][1]} →", type="primary", use_container_width=True,
                          on_click=ir_a, args=(i + 1,))
            else:
                st.button("🔍 Revisar otro mensaje", type="primary", use_container_width=True, on_click=revisar_otro)


# --- Página ------------------------------------------------------------------------------------

st.set_page_config(page_title="Pillao · ¿Es estafa?", page_icon="🛡️", layout="centered")
st.markdown("<style>" + (APP / "estilos.css").read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)

revision = st.session_state.get("revision")
en_resultado = st.session_state.get("vista") == "resultado" and revision is not None
pantalla = ("resultado", st.session_state.get("diapo", 0)) if en_resultado else ("entrada", 0)
if st.session_state.get("_pantalla_previa", pantalla) != pantalla or en_resultado:
    volver_arriba()
st.session_state["_pantalla_previa"] = pantalla

if en_resultado:
    pantalla_resultado(revision)
else:
    pantalla_entrada()

bloque(f"""
    <div class="pie">
      <div class="pie-links"><a href="{REPO}/blob/main/docs/alcance.md" target="_blank">Qué comprobamos y qué no</a>
        <a href="{REPO}" target="_blank">Código en GitHub</a></div>
      <div class="solo-peru">{BANDERA}<span><b>Solo para el Perú.</b> Comparamos con bancos, cajas, billeteras y
        entidades peruanas.</span></div>
      <div>Pillao · Proyecto final de la Diplomatura de Ciencia de Datos (Q-Lab PUCP, 2026).
        No reemplaza a su banco ni a la policía.</div>
    </div>""")
