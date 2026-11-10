# Qué comprueba Pillao y qué no

Pillao nunca dice «es seguro». Separa tres cosas y se las muestra a la persona por separado:

| Nivel | Qué significa | Ejemplo | Efecto en el veredicto |
|---|---|---|---|
| **Prueba** | Lo comprobamos contra un dato público o un cálculo exacto. | El link `viabcp-seguridad.com` no es el dominio oficial del BCP (`viabcp.com`). | 🔴 Es estafa |
| **Regla** | Algo que ninguna entidad formal hace nunca. | Le piden el código que llegó por SMS. | 🔴 Es estafa |
| **Señal** | Un patrón típico de estafa que no prueba nada por sí solo. | «Su cuenta será bloqueada en 2 horas». | 🟠 Muy sospechoso |
| **No comprobable** | No hay datos públicos o está fuera de nuestro alcance. Le decimos cómo comprobarlo él o ella. | ¿De quién es el número de Yape? | Se muestra aparte |

Si no hay pruebas, reglas ni señales, el veredicto es 🟡 **«No pudimos comprobarlo»**, nunca 🟢.

**Quién decide:** la IA (Gemini) solo **lee** la captura y extrae los campos con citas textuales. El veredicto lo calculan reglas escritas en Python ([`app/pillao/verificar.py`](../app/pillao/verificar.py)), que se pueden auditar y probar.

## Campo por campo

| Campo del mensaje | Lo que **sí** comprobamos | Con qué dato | Nivel | Lo que **no** podemos comprobar | Por qué no | Qué le decimos que haga |
|---|---|---|---|---|---|---|
| **Link** | Si el dominio es el oficial de la entidad que dice ser, o la imita (`bcp-seguro.com`). | Lista de dominios oficiales, curada a mano y revisada el 2026-11-09 ([`data/entidades_oficiales.csv`](../data/entidades_oficiales.csv)). | Prueba | Qué hay dentro del link. | No abrimos links sospechosos, por seguridad. | No abrirlo; escribir usted mismo la dirección oficial. |
| **Link que imita a WhatsApp** (`whatsapp-premios.xyz`) | Si usa el nombre de WhatsApp sin ser `whatsapp.com` ni `wa.me`. | Lista de dominios oficiales. | Prueba | — | — | No abrirlo. |
| **Link de una entidad del Estado** | Si termina en `.gob.pe`, el dominio reservado para el Estado peruano. | Regla del dominio `.gob.pe`. | Prueba | — | — | Entrar usted mismo a gob.pe. |
| **Antigüedad del dominio** | Cuántos días tiene el dominio (.com, .net, .xyz, .top, etc.). Uno de pocos días es típico de estafa. | RDAP, el registro público de dominios, en vivo. | Señal | La antigüedad de dominios `.pe`. | NIC.pe no ofrece consulta RDAP. | — |
| **Link acortado** | Si usa un acortador (bit.ly, cutt.ly…) que esconde el destino. | Lista de acortadores. | Señal | El destino real. | Para verlo habría que abrirlo. | No abrirlo. |
| **RUC** | Si el número es válido o inventado (dígito verificador de SUNAT). | Algoritmo módulo 11 de SUNAT. | Prueba | Si la empresa existe y está activa. | La consulta RUC tiene captcha y el padrón completo pesa más de 1 GB (versión 2). | Consultarlo en la web de SUNAT. |
| **Entidad que dice ser (préstamos e inversiones)** | Si figura en el registro de la SBS. | Registro de la SBS descargado a mano, con fecha. | Señal | Si el mensaje lo mandó de verdad esa entidad. | Los estafadores usan nombres de entidades reales. | Llamar a la central oficial. |
| **Lo que le piden** | Clave, PIN, código por SMS o datos de tarjeta. | Regla: los bancos, Yape y el Estado nunca los piden por mensaje. | Regla | — | — | No darlos nunca. |
| **Código de WhatsApp «enviado por error»** | Que le piden el código de 6 dígitos que llegó a su celular. Con él le roban la cuenta de WhatsApp y escriben a sus contactos. | Regla: nadie necesita su código, ni un amigo. | Regla | Si el amigo que se lo pide es de verdad su amigo. | Su cuenta pudo ser robada antes. | No pasarlo y activar la verificación en dos pasos. |
| **Trabajo por «tareas» (me gusta, reseñas, suscripciones)** | Que ofrece pagar por tareas de un minuto y, si lo hay, que cobra un depósito para «tareas VIP». | Lectura con cita; regla del pago adelantado. | Señal (sin depósito) o Regla (con depósito) | — | — | Bloquear el número. |
| **«Le yapeé por error, devuélvamelo»** | Que le piden devolver un dinero que «le enviaron por error». | Lectura con cita. | Señal | Si el dinero de verdad le llegó y de quién es. | Puede venir de una cuenta robada; solo su banco lo sabe. | Revisar su app y llamar a su banco; no devolver por su cuenta. |
| **Pago adelantado** | Pagar para recibir un préstamo, un premio o un trabajo. | Regla: ninguna entidad formal cobra por adelantado para eso. | Regla | — | — | No pagar. |
| **Teléfono** | Si es un celular personal (las empresas no escriben desde ahí) o un número del extranjero. | Formato del número peruano (+51 9…). | Señal | De quién es el número. | No hay registro público: es dato personal. OSIPTEL solo le muestra sus propias líneas. | Colgar y llamar al número que está detrás de su tarjeta. |
| **Cuenta, CCI o número de Yape** | — | — | No comprobable | De quién es la cuenta. | Secreto bancario. | No depositar. |
| **Voucher de Yape, Plin o transferencia («Yape falso»)** | — | — | No comprobable | Si el pago es real. | No hay acceso a los bancos, y hay apps y webs que generan pantallas «¡Yapeaste!» falsas. | No entregar nada hasta ver el dinero en su propia app. |
| **Nombre del «asesor»** | — | — | No comprobable | Si trabaja en el banco. | No hay registro público de empleados. | Colgar y llamar a la central. |
| **«Mamá, cambié de número»** | Que tiene la forma de una estafa conocida. | Lectura del mensaje por la IA, con cita. | Señal | Si su familiar de verdad cambió de número. | Solo su familiar lo sabe. | Llamarlo a su número de siempre o preguntarle algo que solo él o ella sabría. |
| **Urgencia, amenaza, premio inesperado, «no le diga a nadie»** | Que el mensaje usa esa presión, con la frase exacta. | Lectura del mensaje por la IA, con cita. | Señal | — | — | Tomarse 10 minutos y consultar con alguien. |

## Fuera del alcance de la primera versión

- **Llamadas y audios:** la versión 1 lee capturas y texto. La versión 2 podría transcribir audios con Whisper.
- **Imágenes editadas:** no detectamos si una foto de DNI o un voucher fue editado.
- **Empresas reales con productos abusivos** (un préstamo legal pero carísimo): eso no es estafa, es un tema de consumo. Lo ve Indecopi.
- **Estafas por redes sociales sin texto** (solo video o imagen sin texto legible).
