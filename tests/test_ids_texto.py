import pytest

import snapshots
from farmared import conexiones, fechas
from farmared.consultas import q03_historial_cliente as q03
from farmared.consultas import q10_clientes_por_sucursal as q10
from farmared.consultas import q13_abm_clientes as q13
from farmared.consultas import q14_registrar_venta as q14
from farmared.consultas import q15_descontar_stock as q15
from farmared.dominio import validar_id
from farmared.errores import FarmaRedError, ValidacionError

# Un diccionario en el filtro de MongoDB es un operador: {"$ne": None} coincide con el primer documento.
NO_SON_TEXTO = [{"$ne": None}, {"$gt": ""}, None, 1, 1.5, True, ["C001"], ("C001",), b"C001"]


def item(id_producto, cantidad=1):
    return {"id_producto": id_producto, "cantidad": cantidad}


def estado():
    return snapshots.mongo_snap(), snapshots.redis_snap()


def insertar_venta_sin_descuento(db):
    """Inserta a mano una venta 'Completada' que todavía no descontó stock, como una venta importada."""
    venta = {"_id": "V017", "id_cliente": "C001", "id_farmaceutico": "F001", "id_receta": None,
             "fecha": fechas.a_datetime(fechas.hoy()), "tipo": "Venta libre", "medio_pago": "Efectivo",
             "total": 2800, "estado": "Completada", "stock_descontado": False,
             "items": [{"id_detalle": "D023", "id_producto": "PRD001", "cantidad": 1, "precio_unit": 2800}]}
    db.ventas.insert_one(venta)


# La regla

@pytest.mark.parametrize("valor", NO_SON_TEXTO, ids=repr)
def test_un_id_que_no_es_texto_es_dato_invalido(valor):
    with pytest.raises(ValidacionError) as e:
        validar_id("id_cliente", valor)
    assert type(e.value) is ValidacionError
    assert e.value.codigo == "DATO_INVALIDO"
    assert e.value.mensaje == f"id_cliente inválido: {valor!r} (se espera un id de texto)"


@pytest.mark.parametrize("valor", ["C001", "C999", "", " "])
def test_un_id_de_texto_pasa_aunque_no_exista(valor):
    assert validar_id("id_cliente", valor) is None


# Cada consulta con parámetros: el id que no es texto se rechaza y nada cambia

OPERADORES = [
    ("q13-baja", q13.baja_cliente, ({"$ne": None},), "id_cliente"),
    ("q13-modificar", q13.modificar_cliente, ({"$gt": ""}, {"email": "otro@x.com"}), "id_cliente"),
    ("q14-cliente", q14.registrar_venta, ({"$ne": None}, "F001", [item("PRD001")], "Efectivo"), "id_cliente"),
    ("q14-farmaceutico", q14.registrar_venta, ("C001", {"$ne": None}, [item("PRD001")], "Efectivo"),
     "id_farmaceutico"),
    ("q14-receta", q14.registrar_venta, ("C003", "F006", [item("PRD004")], "Obra social", {"$in": ["RC002"]}),
     "id_receta"),
    ("q14-producto", q14.registrar_venta, ("C001", "F001", [item("PRD001"), item({"$ne": None})], "Efectivo"),
     "id_producto"),
    ("q14-item-sin-producto", q14.registrar_venta, ("C001", "F001", [{"cantidad": 1}], "Efectivo"), "id_producto"),
    ("q15", q15.descontar_stock_venta, ({"$gt": ""},), "id_venta"),
    ("q03", q03.historial_cliente, ({"$ne": None},), "id_cliente"),
    ("q10", q10.clientes_por_sucursal, ({"$ne": None},), "id_sucursal"),
]


@pytest.mark.parametrize("funcion,argumentos,campo", [c[1:] for c in OPERADORES], ids=[c[0] for c in OPERADORES])
def test_un_operador_en_lugar_del_id_se_rechaza_sin_cambiar_nada(datos_provistos, funcion, argumentos, campo):
    antes = estado()
    with pytest.raises(ValidacionError) as e:
        funcion(*argumentos)
    assert type(e.value) is ValidacionError
    assert e.value.codigo == "DATO_INVALIDO"
    assert e.value.mensaje.startswith(f"{campo} inválido: ")
    assert estado() == antes


def test_q15_con_un_operador_no_descuenta_la_venta_que_coincide(datos_provistos, db):
    insertar_venta_sin_descuento(db)
    antes = estado()
    with pytest.raises(ValidacionError) as e:
        q15.descontar_stock_venta({"$in": ["V017"]})
    assert e.value.codigo == "DATO_INVALIDO"
    assert estado() == antes
    assert q15.descontar_stock_venta("V017")["consumos"] == [
        {"id_lote": "L001", "id_producto": "PRD001", "unidades": 1}]


UN_ARGUMENTO = [("q13-baja", q13.baja_cliente), ("q15", q15.descontar_stock_venta),
                ("q03", q03.historial_cliente), ("q10", q10.clientes_por_sucursal)]


@pytest.mark.parametrize("valor", [None, 1, ["C001"]], ids=repr)
@pytest.mark.parametrize("funcion", [c[1] for c in UN_ARGUMENTO], ids=[c[0] for c in UN_ARGUMENTO])
def test_un_id_de_otro_tipo_no_se_busca(datos_provistos, funcion, valor):
    with pytest.raises(FarmaRedError) as e:
        funcion(valor)
    assert e.value.codigo == "DATO_INVALIDO"


ANTES_DE_LA_BASE = [
    ("q13-baja", lambda: q13.baja_cliente({"$ne": None})),
    ("q13-modificar", lambda: q13.modificar_cliente({"$ne": None}, {"email": "otro@x.com"})),
    ("q15", lambda: q15.descontar_stock_venta({"$ne": None})),
    ("q03", lambda: q03.historial_cliente({"$ne": None})),
    ("q10", lambda: q10.clientes_por_sucursal({"$ne": None})),
]


@pytest.mark.parametrize("llamada", [c[1] for c in ANTES_DE_LA_BASE], ids=[c[0] for c in ANTES_DE_LA_BASE])
def test_el_rechazo_llega_antes_de_pedir_la_conexion(monkeypatch, llamada):
    def sin_base():
        raise AssertionError("se pidió la conexión antes de validar el id")

    monkeypatch.setattr(conexiones, "get_db", sin_base)
    monkeypatch.setattr(conexiones, "get_client", sin_base)
    with pytest.raises(ValidacionError) as e:
        llamada()
    assert e.value.codigo == "DATO_INVALIDO"


# Lo que no cambia

INEXISTENTES = [
    ("q13-baja", q13.baja_cliente, ("C999",), "CLIENTE_INEXISTENTE"),
    ("q13-baja-vacio", q13.baja_cliente, ("",), "CLIENTE_INEXISTENTE"),
    ("q13-modificar", q13.modificar_cliente, ("C999", {"email": "otro@x.com"}), "CLIENTE_INEXISTENTE"),
    ("q14-receta-vacia", q14.registrar_venta, ("C003", "F006", [item("PRD004")], "Obra social", ""),
     "RECETA_INEXISTENTE"),
    ("q15", q15.descontar_stock_venta, ("V999",), "VENTA_INEXISTENTE"),
    ("q03", q03.historial_cliente, ("C999",), "CLIENTE_INEXISTENTE"),
    ("q10", q10.clientes_por_sucursal, ("S999",), "SUCURSAL_INEXISTENTE"),
]


@pytest.mark.parametrize("funcion,argumentos,codigo", [c[1:] for c in INEXISTENTES], ids=[c[0] for c in INEXISTENTES])
def test_un_id_de_texto_que_no_existe_conserva_su_error(datos_provistos, funcion, argumentos, codigo):
    antes = estado()
    with pytest.raises(FarmaRedError) as e:
        funcion(*argumentos)
    assert e.value.codigo == codigo
    assert estado() == antes


@pytest.mark.parametrize("argumentos,codigo", [
    (({"$ne": None}, "F001", [], "Efectivo"), "ITEMS_VACIOS"),
    (("C001", "F001", [item({"$ne": None}, 0)], "Efectivo"), "CANTIDAD_INVALIDA"),
    (("C001", "F001", [{"id_producto": {"$ne": None}}], "Efectivo"), "CANTIDAD_INVALIDA"),
], ids=["sin-items", "cantidad-cero", "sin-cantidad"])
def test_en_q14_los_items_vacios_y_las_cantidades_se_informan_primero(datos_provistos, argumentos, codigo):
    with pytest.raises(ValidacionError) as e:
        q14.registrar_venta(*argumentos)
    assert e.value.codigo == codigo
