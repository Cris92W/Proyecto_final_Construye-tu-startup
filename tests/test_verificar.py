"""Pruebas de las reglas de Pillao, sin red ni LLM: los mensajes se arman a mano."""
from pillao import verificar as v
from pillao.esquemas import Mensaje, Pedido, Senal, Tipo, TipoSenal

ENTIDADES = v.cargar_entidades()


def mensaje(**campos) -> Mensaje:
    base = dict(transcripcion="", remitente="", tipo=Tipo.otro, entidad_que_dice_ser="", rucs=[],
                telefonos=[], links=[], cuentas_o_numeros_de_pago=[], monto="", te_piden=[], senales=[])
    base.update(campos)
    return Mensaje(**base)


def sin_red(dias):
    return lambda dominio: dias


def titulos(resultado):
    return [h.titulo for h in resultado.hallazgos]


def test_ruc_digito_verificador():
    assert v.ruc_valido("20131312955")      # SUNAT
    assert v.ruc_valido("20100047218")      # Banco de Crédito del Perú
    assert not v.ruc_valido("20612345678")  # dígito final que no cuadra
    assert not v.ruc_valido("123")


def test_buscar_entidad_por_nombre_o_alias():
    assert v.buscar_entidad("Banco de Crédito del Perú", ENTIDADES).nombre == "BCP"
    assert v.buscar_entidad("BCP", ENTIDADES).nombre == "BCP"
    assert v.buscar_entidad("Caja Arequipa", ENTIDADES).nombre == "Caja Arequipa"
    assert v.buscar_entidad("Préstamos Andinos Express SAC", ENTIDADES) is None


def test_link_que_no_es_del_banco_y_pide_clave_es_estafa():
    m = mensaje(tipo=Tipo.aviso_de_banco_o_billetera, entidad_que_dice_ser="BCP",
                links=["https://viabcp-seguridad.com/validar"],
                te_piden=[Pedido.abrir_un_link, Pedido.clave_o_pin, Pedido.codigo_por_sms])
    r = v.analizar(m, ENTIDADES, edad=sin_red(4))
    assert r.veredicto.nivel == v.ROJO
    assert "El link no es de BCP" in titulos(r)
    assert "Le piden el código que le llegó por SMS" in titulos(r)
    assert "La web viabcp-seguridad.com se creó hace 4 días" in titulos(r)


def test_link_imitador_sin_entidad_declarada():
    m = mensaje(links=["yape-premios.xyz/cobrar"])
    r = v.analizar(m, ENTIDADES, edad=sin_red(None))
    assert r.veredicto.nivel == v.ROJO
    assert titulos(r) == ["El link imita a Yape"]


def test_link_oficial_nunca_da_verde():
    m = mensaje(tipo=Tipo.aviso_de_banco_o_billetera, entidad_que_dice_ser="Interbank",
                links=["https://interbank.pe/promociones"])
    r = v.analizar(m, ENTIDADES, edad=sin_red(3))  # no debe consultar la edad de un dominio oficial
    assert r.veredicto.nivel == v.AMARILLO
    assert titulos(r) == ["El link es de la web oficial de Interbank"]


def test_entidad_del_estado_fuera_de_gob_pe():
    falso = mensaje(tipo=Tipo.entidad_del_estado, entidad_que_dice_ser="SUNAT", links=["sunat-pagos.com/deuda"])
    assert "El link no es del Estado peruano" in titulos(v.analizar(falso, ENTIDADES, edad=sin_red(None)))
    real = mensaje(tipo=Tipo.entidad_del_estado, entidad_que_dice_ser="SUNAT", links=["https://www.gob.pe/sunat"])
    assert v.analizar(real, ENTIDADES, edad=sin_red(None)).veredicto.nivel == v.AMARILLO


def test_familiar_en_apuros_es_sospechoso_y_dice_que_no_se_puede_comprobar():
    m = mensaje(tipo=Tipo.familiar_en_apuros, cuentas_o_numeros_de_pago=["Yape 9XX XXX XXX"],
                te_piden=[Pedido.pago_o_deposito],
                senales=[Senal(tipo=TipoSenal.numero_nuevo_de_familiar, cita="este es mi número nuevo"),
                         Senal(tipo=TipoSenal.pide_secreto, cita="no le digas a papá")])
    r = v.analizar(m, ENTIDADES)
    assert r.veredicto.nivel == v.NARANJA
    campos = {n.campo for n in r.no_comprobables}
    assert {"Familiar", "Cuenta o Yape"} <= campos
    assert r.pasos[-1].startswith("Si ya pagó")


def test_prestamo_con_cobro_adelantado_y_ruc_inventado():
    m = mensaje(tipo=Tipo.prestamo, entidad_que_dice_ser="Préstamos Andinos Express SAC",
                rucs=["20612345678"], te_piden=[Pedido.pago_o_deposito])
    r = v.analizar(m, ENTIDADES)
    assert r.veredicto.nivel == v.ROJO
    assert "Le cobran por adelantado por un préstamo" in titulos(r)
    assert "El RUC 20612345678 es inventado" in titulos(r)
    assert any(n.campo == "Empresa" for n in r.no_comprobables)  # sin registro SBS cargado


def test_registro_sbs_cuando_esta_cargado():
    registro = v.RegistroSBS(nombres=("Financiera Confianza S.A.A.",), fecha="2026-11-10", fuente="SBS")
    esta = mensaje(tipo=Tipo.prestamo, entidad_que_dice_ser="Financiera Confianza SAA")
    no_esta = mensaje(tipo=Tipo.prestamo, entidad_que_dice_ser="Préstamos Andinos Express")
    assert v.analizar(esta, ENTIDADES, registro).hallazgos[0].resultado == v.A_FAVOR
    r = v.analizar(no_esta, ENTIDADES, registro)
    assert r.veredicto.nivel == v.NARANJA
    assert "no figura en el registro de la SBS" in r.hallazgos[0].titulo


def test_telefono_extranjero_y_numero_tapado():
    r = v.analizar(mensaje(telefonos=["+62 812 3456 7890", "9XX XXX XXX"]), ENTIDADES)
    assert titulos(r) == ["El número +62 812 3456 7890 es del extranjero"]
    assert len([n for n in r.no_comprobables if n.campo == "Teléfono"]) == 1


def test_codigo_de_whatsapp_por_error_es_estafa():
    m = mensaje(tipo=Tipo.otro, te_piden=[Pedido.codigo_por_sms],
                senales=[Senal(tipo=TipoSenal.urgencia_o_amenaza, cita="Es urgente")])
    r = v.analizar(m, ENTIDADES)
    assert r.veredicto.nivel == v.ROJO
    assert r.veredicto.razon == "Le piden el código que le llegó por SMS"
    assert any("verificación en dos pasos" in p for p in r.pasos)


def test_trabajo_por_tareas_desde_el_extranjero():
    tareas = Senal(tipo=TipoSenal.ganar_dinero_por_tareas, cita="Te pagamos S/ 10 por cada tarea")
    sin_deposito = mensaje(tipo=Tipo.trabajo, telefonos=["+84 58 853 2741"], senales=[tareas])
    r = v.analizar(sin_deposito, ENTIDADES)
    assert r.veredicto.nivel == v.NARANJA
    assert "Le ofrecen pagarle por dar «me gusta», reseñas o hacer tareas" in titulos(r)
    con_deposito = mensaje(tipo=Tipo.trabajo, te_piden=[Pedido.pago_o_deposito], senales=[tareas])
    assert v.analizar(con_deposito, ENTIDADES).veredicto.razon == "Le cobran por adelantado por un trabajo"


def test_le_yapearon_por_error():
    m = mensaje(te_piden=[Pedido.pago_o_deposito], cuentas_o_numeros_de_pago=["9XX XXX XXX"],
                senales=[Senal(tipo=TipoSenal.devolver_pago_por_error, cita="le acabo de yapear S/ 250 por error")])
    r = v.analizar(m, ENTIDADES)
    assert r.veredicto.nivel == v.NARANJA
    assert any(p.startswith("No devuelva dinero") for p in r.pasos)


def test_voucher_de_yape_nunca_se_da_por_bueno():
    r = v.analizar(mensaje(tipo=Tipo.comprobante_de_pago, monto="S/ 100"), ENTIDADES)
    assert r.veredicto.nivel == v.AMARILLO
    assert any(n.campo == "Comprobante" for n in r.no_comprobables)
    assert any("SU propia app" in p for p in r.pasos)


def test_link_que_imita_a_whatsapp():
    r = v.analizar(mensaje(links=["https://whatsapp-premios.xyz/aniversario"]), ENTIDADES, edad=sin_red(None))
    assert titulos(r) == ["El link imita a WhatsApp"]
    oficial = v.analizar(mensaje(links=["https://wa.me/51999999999"]), ENTIDADES, edad=sin_red(1))
    assert oficial.hallazgos == []
