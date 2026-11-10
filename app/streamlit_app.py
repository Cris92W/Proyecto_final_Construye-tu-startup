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

# Colores y tipografía base en .streamlit/config.toml; aquí, las piezas propias de la página.
ESTILOS = """
:root { --tinta:#14212B; --suave:#5B6670; --borde:#E3DDD1; --marca:#0E5E6F; }
.block-container { padding-top:2.2rem; padding-bottom:3rem; }
header[data-testid="stHeader"] { background:transparent; }

.hero { position:relative; overflow:hidden; border-radius:26px; padding:2rem 2rem 1.7rem; margin:0 0 1.1rem;
  color:#fff; background:radial-gradient(120% 140% at 100% 0%, #1C8C9E 0%, #0E5E6F 45%, #0A3F4C 100%);
  box-shadow:0 22px 44px -24px rgba(10,63,76,.65); }
.marca { display:flex; align-items:center; gap:.5rem; font-weight:700; font-size:1.05rem; letter-spacing:.03em; }
.marca svg { width:28px; height:28px; }
.hero-titulo { font-family:"Fraunces", Georgia, serif; font-weight:700; font-size:2.4rem; line-height:1.12;
  margin:1.1rem 0 .7rem; letter-spacing:-.01em; color:#fff; }
.hero-titulo em { font-style:normal; color:#FFD49A; }
.hero-texto { font-size:1.12rem; line-height:1.55; color:rgba(255,255,255,.9); margin:0 0 1.2rem; max-width:33rem; }
.chips { display:flex; flex-wrap:wrap; gap:.5rem; position:relative; z-index:1; }
.chip { display:inline-flex; align-items:center; gap:.45rem; padding:.38rem .85rem; border-radius:999px;
  font-size:.9rem; color:#fff; background:rgba(255,255,255,.12); border:1px solid rgba(255,255,255,.24); }
.chip:before { content:""; width:7px; height:7px; border-radius:50%; background:#FFD49A; }
.marca-agua { position:absolute; right:-36px; bottom:-46px; width:230px; height:230px; opacity:.09; color:#fff; }
.marca-agua svg { width:100%; height:100%; }

.como { display:grid; grid-template-columns:repeat(3, 1fr); gap:.75rem; margin:0 0 1.4rem; }
.paso { background:#fff; border:1px solid var(--borde); border-radius:18px; padding:1rem 1rem .95rem; }
.paso .n { display:inline-flex; align-items:center; justify-content:center; width:30px; height:30px;
  border-radius:50%; background:#E2EFF1; color:var(--marca); font-weight:800; margin-bottom:.55rem; }
.paso b { display:block; font-size:1.03rem; color:var(--tinta); margin-bottom:.2rem; }
.paso .t { font-size:.93rem; line-height:1.45; color:var(--suave); }

.st-key-entrada { background:#fff; box-shadow:0 14px 34px -26px rgba(20,33,43,.45); }
.sec { font-family:"Fraunces", Georgia, serif; font-weight:700; font-size:1.45rem; color:var(--tinta);
  margin:1.4rem 0 .6rem; }
.sec span { font-weight:600; color:var(--suave); font-size:1.05rem; }
.st-key-entrada .sec { margin-top:.2rem; }
button[data-testid="stBaseButton-primary"] { padding:.8rem 1rem; border-radius:14px; }
button[data-testid="stBaseButton-primary"]:not(:disabled) { box-shadow:0 12px 26px -14px rgba(14,94,111,.9); }
.stButton button p { font-size:1.15rem; font-weight:700; }

.veredicto { --c:#B3261E; position:relative; overflow:hidden; border-radius:24px; border:1px solid;
  padding:1.5rem 1.6rem 1.25rem 1.9rem; margin:1.6rem 0 .4rem; }
.veredicto:before { content:""; position:absolute; left:0; top:0; bottom:0; width:8px; background:var(--c); }
.v-rojo { --c:#B3261E; background:#FDECEA; border-color:#F2C3BF; }
.v-naranja { --c:#C25E00; background:#FFF1E0; border-color:#F4CFA2; }
.v-amarillo { --c:#8A6D00; background:#FFF8DC; border-color:#E9D899; }
.v-kicker { display:flex; align-items:center; gap:.55rem; font-size:.8rem; font-weight:700; letter-spacing:.09em;
  text-transform:uppercase; color:var(--c); }
.v-punto { width:11px; height:11px; border-radius:50%; background:var(--c); box-shadow:0 0 0 5px rgba(0,0,0,.06); }
.v-titulo { font-family:"Fraunces", Georgia, serif; font-weight:700; font-size:2.4rem; line-height:1.1;
  color:var(--tinta); margin:.55rem 0 .35rem; }
.v-sub { font-size:1.15rem; font-weight:700; color:var(--tinta); margin-bottom:.9rem; }
.v-motivo { background:rgba(255,255,255,.72); border-radius:14px; padding:.8rem 1rem; font-size:1.05rem;
  line-height:1.5; color:#23303A; }
.v-motivo b { display:block; font-size:.76rem; letter-spacing:.08em; text-transform:uppercase; color:var(--suave);
  margin-bottom:.2rem; }
.escala { display:flex; flex-wrap:wrap; gap:.4rem; margin-top:1rem; }
.escala span { flex:1; min-width:105px; text-align:center; padding:.42rem .5rem; border-radius:999px;
  font-size:.84rem; font-weight:700; color:#7B858D; background:rgba(255,255,255,.55);
  border:1px solid rgba(20,33,43,.08); }
.escala span.on { color:#fff; background:var(--c); border-color:var(--c); }
.escala-nota { margin-top:.55rem; font-size:.84rem; color:var(--suave); }

ol.pasos { list-style:none; counter-reset:paso; margin:0 0 1rem; padding:0; }
ol.pasos li { counter-increment:paso; position:relative; margin:0 0 .5rem; padding:.8rem 1rem .8rem 3.3rem;
  background:#fff; border:1px solid var(--borde); border-radius:14px; font-size:1.08rem; line-height:1.5;
  color:var(--tinta); }
ol.pasos li:before { content:counter(paso); position:absolute; left:.9rem; top:.78rem; width:1.75rem;
  height:1.75rem; border-radius:50%; display:flex; align-items:center; justify-content:center;
  background:var(--marca); color:#fff; font-weight:800; font-size:.95rem; }
.st-key-avisar a { background:#1F8F55; border-color:#1F8F55; border-radius:14px; padding:.8rem 1rem; }
.st-key-avisar a:hover { background:#18764A; border-color:#18764A; }
.st-key-avisar a p { color:#fff; font-size:1.12rem; font-weight:700; }

.tarjeta { display:flex; gap:.9rem; background:#fff; border:1px solid var(--borde); border-radius:16px;
  padding:1rem 1.1rem; margin-bottom:.6rem; }
.tarjeta > div:last-child { flex:1; min-width:0; overflow-wrap:anywhere; }
.t-icono { flex:0 0 2.1rem; height:2.1rem; border-radius:50%; display:flex; align-items:center;
  justify-content:center; font-weight:800; font-size:1.05rem; }
.t-contra .t-icono { background:#FDECEA; color:#B3261E; }
.t-favor .t-icono { background:#E7F4EC; color:#1E7A46; }
.t-nc .t-icono { background:#E9EFF6; color:#2F5D8A; }
.t-titulo { font-weight:700; font-size:1.07rem; line-height:1.35; color:var(--tinta); }
.t-detalle { margin-top:.2rem; line-height:1.5; color:#33414C; }
.t-meta { display:flex; flex-wrap:wrap; align-items:center; gap:.5rem; margin-top:.55rem; font-size:.84rem;
  color:#6B757D; }
.pill { padding:.12rem .6rem; border-radius:999px; font-size:.72rem; font-weight:800; letter-spacing:.06em;
  text-transform:uppercase; background:var(--tinta); color:#fff; }
.pill.senal { background:#ECE6DA; color:#3A444C; }
.t-hacer { margin-top:.6rem; padding:.55rem .75rem; border-radius:10px; background:#F1F5FA; color:#1F3A55;
  line-height:1.45; }
.vacio { padding:1rem; border:1px dashed var(--borde); border-radius:14px; color:var(--suave); }
[data-testid="stExpander"] details { background:#fff; border-radius:14px; }

.pie { margin-top:2.6rem; padding-top:1.3rem; border-top:1px solid var(--borde); color:var(--suave);
  font-size:.9rem; line-height:1.5; }
.pie-marca { display:flex; align-items:center; gap:.4rem; font-weight:700; color:var(--tinta); margin-bottom:.4rem; }
.pie-marca svg { width:20px; height:20px; color:var(--marca); }
.pie-links { display:flex; flex-wrap:wrap; gap:1.1rem; margin-bottom:.4rem; }
.pie-links a { color:var(--marca); font-weight:700; text-decoration:none; }

@media (max-width:640px) {
  .hero { padding:1.5rem 1.3rem 1.3rem; border-radius:20px; }
  .hero-titulo { font-size:1.85rem; }
  .como { grid-template-columns:1fr; }
  .v-titulo { font-size:1.9rem; }
}
"""


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
        return f"La línea `GEMINI_API_KEY` está en los **Secrets**, pero vacía: pegue la clave entre las comillas."
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


# --- Resultado ---------------------------------------------------------------------------------

def mostrar(mensaje, resultado, uso, modelo) -> None:
    v = resultado.veredicto
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

    bloque('<div class="sec">Qué hacer ahora</div>')
    bloque('<ol class="pasos">' + "".join(f"<li>{limpio(paso)}</li>" for paso in resultado.pasos) + "</ol>")

    aviso = (f"Me llegó un mensaje y lo revisé con Pillao: {ICONO[v.nivel]} {v.titulo}. "
             f"Motivo: {desactivar_links(v.razon)}. ¿Me ayudas a revisarlo?")
    with st.container(key="avisar"):
        st.link_button("📲 Avisar a mi familia por WhatsApp", f"https://wa.me/?text={quote(aviso)}",
                       use_container_width=True)

    bloque('<div class="sec">Lo que comprobamos</div>')
    if not resultado.hallazgos:
        bloque('<div class="vacio">No encontramos datos que se puedan comprobar en este mensaje.</div>')
    tarjetas = []
    for h in resultado.hallazgos:
        contra = h.resultado == verificar.EN_CONTRA
        tarjetas.append(f"""
            <div class="tarjeta {'t-contra' if contra else 't-favor'}">
              <div class="t-icono">{'✕' if contra else '✓'}</div>
              <div><div class="t-titulo">{limpio(h.titulo)}</div>
                <div class="t-detalle">{limpio(h.detalle)}</div>
                <div class="t-meta"><span class="pill {CLASE_FUERZA[h.fuerza]}">{FUERZA[h.fuerza]}</span>
                  Fuente: {limpio(h.fuente)}</div></div>
            </div>""")
    if tarjetas:
        bloque("".join(tarjetas))

    if resultado.no_comprobables:
        bloque('<div class="sec">Lo que no podemos comprobar <span>(y cómo hacerlo usted)</span></div>')
        bloque("".join(f"""
            <div class="tarjeta t-nc">
              <div class="t-icono">?</div>
              <div><div class="t-titulo">{limpio(n.que)}</div>
                <div class="t-detalle">{limpio(n.por_que)}</div>
                <div class="t-hacer"><b>Qué hacer:</b> {limpio(n.que_hacer)}</div></div>
            </div>""" for n in resultado.no_comprobables))

    st.write("")
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
        costo = uso.costo_usd()
        st.markdown(f"{uso.llamadas} llamada al modelo `{modelo}`: {uso.tokens_entrada:,} tokens de entrada y "
                    f"{uso.tokens_salida:,} de salida.")
        if costo is not None:
            st.markdown(f"Con el precio de lista del plan de pago: **US$ {costo:.4f}** "
                        f"(S/ {costo * TIPO_CAMBIO:.3f}). Las comprobaciones (dominios, RUC, RDAP) no cuestan.")


# --- Página ------------------------------------------------------------------------------------

st.set_page_config(page_title="Pillao · ¿Es estafa?", page_icon="🛡️", layout="centered")
st.markdown("<style>" + ESTILOS + "</style>", unsafe_allow_html=True)

bloque(f"""
    <div class="hero">
      <div class="marca">{ESCUDO}<span>Pillao</span></div>
      <div class="hero-titulo">¿Le llegó un mensaje raro?<br><em>Revíselo antes de responder.</em></div>
      <p class="hero-texto">Suba la captura del WhatsApp o del SMS. En segundos le decimos si es estafa,
        con la prueba concreta, y qué no se puede comprobar.</p>
      <div class="chips"><span class="chip">Respuesta en segundos</span>
        <span class="chip">No guardamos su mensaje</span>
        <span class="chip">Nunca le diremos «es seguro»</span></div>
      <div class="marca-agua">{ESCUDO}</div>
    </div>""")

bloque("""
    <div class="como">
      <div class="paso"><span class="n">1</span><b>Suba la captura</b>
        <div class="t">Del WhatsApp, del SMS o del correo. También puede pegar el texto.</div></div>
      <div class="paso"><span class="n">2</span><b>Leemos y comprobamos</b>
        <div class="t">La IA lee el mensaje y nuestras reglas revisan cada link, RUC y pedido.</div></div>
      <div class="paso"><span class="n">3</span><b>Le decimos qué hacer</b>
        <div class="t">Con la prueba concreta y lo que nadie puede comprobar.</div></div>
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

    huella = hashlib.sha256((imagen or b"") + texto.encode()).hexdigest()
    listo = bool(clave) and (imagen is not None or bool(texto.strip()))
    pulsado = st.button("🔍 Revisar el mensaje", type="primary", use_container_width=True, disabled=not listo)

if pulsado:
    with st.spinner("Leyendo el mensaje y comprobando cada dato…"):
        cliente = ClienteLLM(api_key=clave, modelo=_secreto("GEMINI_MODEL"))
        try:
            mensaje = cliente.leer(imagen, tipo_imagen, texto)
        except Exception as error:  # se muestra a la persona en vez de romper la página
            st.error(f"No pudimos leer el mensaje. Intente de nuevo en un minuto. ({type(error).__name__})")
            st.stop()
        resultado = verificar.analizar(mensaje, entidades(), registro_sbs())
    st.session_state["revision"] = (huella, mensaje, resultado, cliente.uso, ", ".join(cliente.uso.modelos))

revision = st.session_state.get("revision")
if revision and revision[0] == huella:
    mostrar(*revision[1:])

bloque(f"""
    <div class="pie">
      <div class="pie-marca">{ESCUDO}<span>Pillao</span></div>
      <div class="pie-links"><a href="{REPO}/blob/main/docs/alcance.md" target="_blank">Qué comprobamos y qué no</a>
        <a href="{REPO}" target="_blank">Código en GitHub</a></div>
      <div>Proyecto final de la Diplomatura de Ciencia de Datos (Q-Lab PUCP, 2026).
        Pillao no reemplaza a su banco ni a la policía.</div>
    </div>""")
