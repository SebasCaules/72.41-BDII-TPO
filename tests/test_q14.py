import datetime
import json
import pathlib
import subprocess
import sys
import threading

import pytest
import redis
from pymongo.client_session import ClientSession
from pymongo.errors import PyMongoError

import snapshots
from farmared import claves, fechas, stock
from farmared.consultas import q14_registrar_venta as q14
from farmared.errores import NoEncontrado, StockInsuficiente, ValidacionError

RAIZ = pathlib.Path(__file__).resolve().parent.parent
# Se toma antes de que conftest fije "hoy": es la fecha que usa la línea de comandos en un subproceso.
FECHA_DEL_SISTEMA = fechas.hoy
VENTAS_PROVISTAS = 16
DETALLES_PROVISTOS = 22
HILOS = 10


def correr_cli(*argumentos):
    return subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                          text=True, timeout=60)


def unidades(r, id_lote):
    return int(r.hget(claves.lote(id_lote), "unidades"))


def contador(db, nombre):
    return db.contadores.find_one({"_id": nombre})["ultimo"]


def item(id_producto, cantidad):
    return {"id_producto": id_producto, "cantidad": cantidad}


def snapshot():
    return snapshots.mongo_snap(), snapshots.redis_snap()


def receta(db, id_receta):
    doc = db.recetas.find_one({"_id": id_receta})
    return doc["dispensas_realizadas"], doc["estado"], doc["proxima_dispensa"]


def venta_rc002():
    return q14.registrar_venta("C003", "F006", [item("PRD004", 1)], "Obra social", "RC002")


# Valores de control con los datos provistos

def test_exito_con_la_ultima_dispensa_de_un_tratamiento(datos_provistos, db, r):
    resultado = venta_rc002()
    venta_esperada = {
        "id_venta": "V017", "id_cliente": "C003", "id_farmaceutico": "F006", "id_receta": "RC002",
        "fecha": "2026-11-03", "tipo": "Con receta", "medio_pago": "Obra social", "total": 6200,
        "estado": "Completada",
        "items": [{"id_detalle": "D023", "id_producto": "PRD004", "cantidad": 1, "precio_unit": 6200}],
        "stock_descontado": True, "consumos": [{"id_lote": "L007", "id_producto": "PRD004", "unidades": 1}]}
    assert resultado == {
        "venta": venta_esperada,
        "receta": {"id_receta": "RC002", "dispensas_realizadas": 3, "estado": "Completada",
                   "proxima_dispensa": None},
        "consumos": [{"id_lote": "L007", "id_producto": "PRD004", "unidades": 1}]}
    guardada = db.ventas.find_one({"_id": "V017"})
    assert guardada["fecha"] == datetime.datetime(2026, 11, 3)
    assert {"id_venta": guardada.pop("_id"), **guardada, "fecha": "2026-11-03"} == venta_esperada
    assert receta(db, "RC002") == (3, "Completada", None)
    assert unidades(r, "L007") == 21
    assert (contador(db, "ventas"), contador(db, "detalle_ventas")) == (17, 23)


def test_tratamiento_prolongado_intermedio(datos_provistos, db, r):
    resultado = q14.registrar_venta("C006", "F001", [item("PRD003", 1)], "Obra social", "RC004")
    assert resultado["receta"] == {"id_receta": "RC004", "dispensas_realizadas": 2, "estado": "Vigente",
                                   "proxima_dispensa": "2026-12-03"}
    assert receta(db, "RC004") == (2, "Vigente", datetime.datetime(2026, 12, 3))
    assert resultado["consumos"] == [{"id_lote": "L005", "id_producto": "PRD003", "unidades": 1}]
    assert (unidades(r, "L005"), unidades(r, "L015")) == (39, 100)


def test_transicion_simple(datos_provistos, db, r):
    resultado = q14.registrar_venta("C007", "F006", [item("PRD007", 1)], "Obra social", "RC006")
    assert resultado["receta"] == {"id_receta": "RC006", "dispensas_realizadas": 1, "estado": "Completada",
                                   "proxima_dispensa": None}
    assert receta(db, "RC006") == (1, "Completada", None)
    assert unidades(r, "L014") == 44


def test_transicion_archivada(datos_provistos, db, r):
    db.recetas.insert_one({
        "_id": "RC010", "id_cliente": "C002", "medico": "Dra. Laura Cifuentes", "matricula_medico": "MP-52311",
        "fecha_emision": datetime.datetime(2026, 11, 1), "tipo": "Archivada", "dispensas_autorizadas": 1,
        "dispensas_realizadas": 0, "proxima_dispensa": None, "estado": "Vigente"})
    resultado = q14.registrar_venta("C002", "F005", [item("PRD008", 1)], "Obra social", "RC010")
    assert resultado["receta"] == {"id_receta": "RC010", "dispensas_realizadas": 1, "estado": "Completada",
                                   "proxima_dispensa": None}
    assert receta(db, "RC010") == (1, "Completada", None)
    assert resultado["consumos"] == [{"id_lote": "L010", "id_producto": "PRD008", "unidades": 1}]
    assert unidades(r, "L010") == 11


def test_venta_libre_sin_receta(datos_provistos, db, r):
    resultado = q14.registrar_venta("C005", "F001", [item("PRD002", 1)], "Efectivo")
    assert (resultado["venta"]["tipo"], resultado["venta"]["id_receta"], resultado["receta"]) == (
        "Venta libre", None, None)
    assert unidades(r, "L004") == 89


def test_total_es_la_suma_a_precio_de_lista(datos_provistos, db):
    # V001 guarda un precio del momento distinto del de lista: la venta nueva usa el de lista vigente
    db.productos.update_one({"_id": "PRD011"}, {"$set": {"precio_unit": 2350}})
    resultado = q14.registrar_venta("C001", "F001", [item("PRD001", 2), item("PRD011", 3), item("PRD001", 1)],
                                    "Débito")
    venta = resultado["venta"]
    assert venta["items"] == [
        {"id_detalle": "D023", "id_producto": "PRD001", "cantidad": 2, "precio_unit": 2800},
        {"id_detalle": "D024", "id_producto": "PRD011", "cantidad": 3, "precio_unit": 2350},
        {"id_detalle": "D025", "id_producto": "PRD001", "cantidad": 1, "precio_unit": 2800}]
    assert venta["total"] == 2 * 2800 + 3 * 2350 + 1 * 2800 == 15450
    assert db.ventas.find_one({"_id": "V017"})["total"] == 15450
    # el stock agrupa por producto
    assert resultado["consumos"] == [{"id_lote": "L001", "id_producto": "PRD001", "unidades": 3},
                                     {"id_lote": "L013", "id_producto": "PRD011", "unidades": 3}]


def test_dispensa_anterior_a_la_proxima_estimada_se_acepta(datos_provistos, db, monkeypatch):
    # RC004 espera la próxima dispensa el 2026-10-20; "hoy" se mueve antes, después de la carga
    monkeypatch.setattr(fechas, "hoy", lambda: datetime.date(2026, 10, 15))
    resultado = q14.registrar_venta("C006", "F001", [item("PRD003", 1)], "Obra social", "RC004")
    assert resultado["venta"]["fecha"] == "2026-10-15"
    assert resultado["receta"] == {"id_receta": "RC004", "dispensas_realizadas": 2, "estado": "Vigente",
                                   "proxima_dispensa": "2026-11-14"}


def test_resultado_serializable_en_json(datos_provistos):
    resultado = venta_rc002()
    assert json.loads(json.dumps(resultado)) == resultado


# Rechazos: cada código deja Mongo (contadores incluidos) y Redis como estaban

def sucursal_inexistente(db):
    db.farmaceuticos.update_one({"_id": "F001"}, {"$set": {"id_sucursal": "S999"}})


def sucursal_inactiva(db):
    db.sucursales.update_one({"_id": "S001"}, {"$set": {"activo": False}})


def receta_sin_dispensas(db):
    db.recetas.update_one({"_id": "RC004"}, {"$set": {"dispensas_realizadas": 3}})


def reabrir_rc008(db):
    # RC008 está completada: se reabre para que la validación llegue al stock
    db.recetas.update_one({"_id": "RC008"}, {"$set": {"estado": "Vigente", "dispensas_realizadas": 0}})


RECHAZOS = [
    ("ITEMS_VACIOS", ValidacionError, None, ("C001", "F001", [], "Efectivo", None)),
    ("CANTIDAD_INVALIDA", ValidacionError, None, ("C001", "F001", [item("PRD001", 0)], "Efectivo", None)),
    ("CANTIDAD_INVALIDA", ValidacionError, None, ("C001", "F001", [item("PRD001", -2)], "Efectivo", None)),
    ("CANTIDAD_INVALIDA", ValidacionError, None, ("C001", "F001", [item("PRD001", 1.5)], "Efectivo", None)),
    ("CANTIDAD_INVALIDA", ValidacionError, None, ("C001", "F001", [item("PRD001", "2")], "Efectivo", None)),
    ("CANTIDAD_INVALIDA", ValidacionError, None, ("C001", "F001", [item("PRD001", True)], "Efectivo", None)),
    ("CANTIDAD_INVALIDA", ValidacionError, None,
     ("C001", "F001", [item("PRD001", 1), {"id_producto": "PRD011"}], "Efectivo", None)),
    ("CLIENTE_INEXISTENTE", NoEncontrado, None, ("C999", "F001", [item("PRD001", 1)], "Efectivo", None)),
    ("CLIENTE_INACTIVO", ValidacionError, None, ("C008", "F001", [item("PRD001", 1)], "Efectivo", None)),
    ("FARMACEUTICO_INEXISTENTE", NoEncontrado, None, ("C001", "F999", [item("PRD001", 1)], "Efectivo", None)),
    ("FARMACEUTICO_INACTIVO", ValidacionError, None, ("C001", "F004", [item("PRD002", 1)], "Efectivo", None)),
    ("SUCURSAL_INEXISTENTE", NoEncontrado, sucursal_inexistente,
     ("C001", "F001", [item("PRD001", 1)], "Efectivo", None)),
    ("SUCURSAL_NO_FARMACIA", ValidacionError, None, ("C001", "F007", [item("PRD001", 1)], "Efectivo", None)),
    ("SUCURSAL_INACTIVA", ValidacionError, sucursal_inactiva,
     ("C001", "F001", [item("PRD001", 1)], "Efectivo", None)),
    ("PRODUCTO_INEXISTENTE", NoEncontrado, None,
     ("C001", "F001", [item("PRD001", 1), item("PRD999", 1)], "Efectivo", None)),
    ("PRODUCTO_INACTIVO", ValidacionError, None,
     ("C001", "F001", [item("PRD001", 1), item("PRD012", 1)], "Efectivo", None)),
    ("MEDIO_PAGO_INVALIDO", ValidacionError, None, ("C001", "F001", [item("PRD001", 1)], "Cheque", None)),
    ("MEDIO_PAGO_INVALIDO", ValidacionError, None, ("C001", "F001", [item("PRD001", 1)], "efectivo", None)),
    ("OBRA_SOCIAL_SIN_COBERTURA", ValidacionError, None,
     ("C005", "F001", [item("PRD001", 1)], "Obra social", None)),
    ("RECETA_REQUERIDA", ValidacionError, None, ("C003", "F006", [item("PRD004", 1)], "Obra social", None)),
    ("RECETA_REQUERIDA", ValidacionError, None,
     ("C005", "F005", [item("PRD001", 1), item("PRD008", 1)], "Efectivo", None)),
    ("RECETA_INEXISTENTE", NoEncontrado, None, ("C003", "F006", [item("PRD004", 1)], "Obra social", "RC999")),
    ("RECETA_OTRO_CLIENTE", ValidacionError, None,
     ("C001", "F006", [item("PRD004", 1)], "Obra social", "RC002")),
    ("RECETA_NO_VIGENTE", ValidacionError, None, ("C002", "F001", [item("PRD003", 1)], "Obra social", "RC009")),
    ("RECETA_NO_VIGENTE", ValidacionError, None, ("C001", "F001", [item("PRD003", 1)], "Obra social", "RC001")),
    ("RECETA_SIN_DISPENSAS", ValidacionError, receta_sin_dispensas,
     ("C006", "F001", [item("PRD003", 1)], "Obra social", "RC004")),
    ("RECETA_INNECESARIA", ValidacionError, None, ("C003", "F006", [item("PRD001", 1)], "Efectivo", "RC002")),
    ("STOCK_INSUFICIENTE", StockInsuficiente, None,
     ("C003", "F006", [item("PRD004", 23)], "Obra social", "RC002")),
    ("STOCK_INSUFICIENTE", StockInsuficiente, reabrir_rc008,
     ("C001", "F001", [item("PRD001", 5), item("PRD003", 141)], "Obra social", "RC008")),
]


@pytest.mark.parametrize("codigo,clase,preparar,argumentos", RECHAZOS,
                         ids=[f"{i:02d}-{c[0].lower()}" for i, c in enumerate(RECHAZOS)])
def test_rechazo_deja_todo_como_estaba(datos_provistos, db, codigo, clase, preparar, argumentos):
    if preparar is not None:
        preparar(db)
    antes = snapshot()
    with pytest.raises(clase) as e:
        q14.registrar_venta(*argumentos)
    assert type(e.value) is clase
    assert e.value.codigo == codigo
    assert snapshot() == antes


def test_stock_insuficiente_informa_lo_pedido_y_lo_disponible(datos_provistos, db):
    antes = snapshot()
    with pytest.raises(StockInsuficiente) as e:
        q14.registrar_venta("C003", "F006", [item("PRD004", 23)], "Obra social", "RC002")
    assert (e.value.id_producto, e.value.requerido, e.value.disponible) == ("PRD004", 23, 22)
    assert snapshot() == antes
    assert receta(db, "RC002") == (2, "Vigente", datetime.datetime(2026, 9, 15))
    assert (contador(db, "ventas"), contador(db, "detalle_ventas")) == (16, 22)


def test_stock_insuficiente_por_lote_vencido(datos_provistos, db):
    db.recetas.insert_one({
        "_id": "RC010", "id_cliente": "C002", "medico": "Dra. Laura Cifuentes", "matricula_medico": "MP-52311",
        "fecha_emision": datetime.datetime(2026, 11, 1), "tipo": "Simple", "dispensas_autorizadas": 1,
        "dispensas_realizadas": 0, "proxima_dispensa": None, "estado": "Vigente"})
    antes = snapshot()
    with pytest.raises(StockInsuficiente) as e:
        q14.registrar_venta("C002", "F003", [item("PRD010", 1)], "Obra social", "RC010")
    assert (e.value.id_producto, e.value.requerido, e.value.disponible) == ("PRD010", 1, 0)
    assert snapshot() == antes


def test_receta_modificada_durante_la_venta(datos_provistos, db, monkeypatch):
    validar = q14._validar

    def validar_con_receta_desactualizada(*args):
        productos, leida = validar(*args)
        # la receta leída ya no coincide con la guardada: la actualización condicional no encuentra el documento
        return productos, {**leida, "dispensas_realizadas": leida["dispensas_realizadas"] - 1}

    monkeypatch.setattr(q14, "_validar", validar_con_receta_desactualizada)
    antes = snapshot()
    with pytest.raises(ValidacionError) as e:
        venta_rc002()
    assert e.value.codigo == "RECETA_MODIFICADA"
    assert snapshot() == antes


def test_un_rechazo_no_consume_ids(datos_provistos, db):
    with pytest.raises(ValidacionError):
        q14.registrar_venta("C008", "F001", [item("PRD001", 1)], "Efectivo")
    with pytest.raises(StockInsuficiente):
        q14.registrar_venta("C003", "F006", [item("PRD004", 23)], "Obra social", "RC002")
    resultado = q14.registrar_venta("C001", "F001", [item("PRD001", 1)], "Efectivo")
    assert resultado["venta"]["id_venta"] == "V017"
    assert resultado["venta"]["items"][0]["id_detalle"] == "D023"


# Fallos del commit

def test_fallo_del_commit_deja_todo_como_estaba(datos_provistos, monkeypatch):
    antes = snapshot()

    def falla(self):
        raise PyMongoError("fallo simulado del commit")

    monkeypatch.setattr(ClientSession, "commit_transaction", falla)
    with pytest.raises(PyMongoError) as e:
        venta_rc002()
    assert str(e.value) == "fallo simulado del commit"
    assert snapshot() == antes


def test_fallo_de_redis_despues_del_script_deja_todo_como_estaba(datos_provistos, monkeypatch):
    antes = snapshot()
    original = redis.client.Pipeline.execute
    reponer = stock.reponer
    repuestos = []

    def ejecutar(self, *args, **kwargs):
        if not self.transaction:
            raise redis.ConnectionError("conexión perdida al leer los lotes")
        return original(self, *args, **kwargs)

    def reponer_y_anotar(consumos):
        repuestos.append(consumos)
        reponer(consumos)

    monkeypatch.setattr(redis.client.Pipeline, "execute", ejecutar)
    monkeypatch.setattr(stock, "reponer", reponer_y_anotar)
    with pytest.raises(redis.ConnectionError):
        venta_rc002()
    monkeypatch.setattr(redis.client.Pipeline, "execute", original)
    assert repuestos == [[{"id_lote": "L007", "unidades": 1}]]
    assert snapshot() == antes


def test_commit_sin_confirmacion_que_no_se_aplico_repone(datos_provistos, monkeypatch):
    antes = snapshot()

    def falla(self):
        raise PyMongoError("sin respuesta del servidor", error_labels=["UnknownTransactionCommitResult"])

    monkeypatch.setattr(ClientSession, "commit_transaction", falla)
    with pytest.raises(PyMongoError):
        venta_rc002()
    assert snapshot() == antes


def test_commit_sin_confirmacion_que_se_aplico_no_repone(datos_provistos, db, r, monkeypatch):
    original = ClientSession.commit_transaction
    repuestos = []
    reponer = stock.reponer

    def aplica_y_pierde_la_respuesta(self):
        original(self)
        raise PyMongoError("se perdió la respuesta del commit", error_labels=["UnknownTransactionCommitResult"])

    def reponer_registrando(consumos):
        repuestos.append(consumos)
        reponer(consumos)

    monkeypatch.setattr(ClientSession, "commit_transaction", aplica_y_pierde_la_respuesta)
    monkeypatch.setattr(stock, "reponer", reponer_registrando)
    resultado = venta_rc002()
    assert repuestos == []
    assert resultado["venta"]["id_venta"] == "V017"
    assert db.ventas.find_one({"_id": "V017"})["stock_descontado"] is True
    assert receta(db, "RC002") == (3, "Completada", None)
    assert unidades(r, "L007") == 21


def test_reintenta_ante_un_error_transitorio(datos_provistos, db, r, monkeypatch):
    original = ClientSession.commit_transaction
    llamadas = []

    def falla_la_primera_vez(self):
        llamadas.append(1)
        if len(llamadas) == 1:
            raise PyMongoError("conflicto simulado", error_labels=["TransientTransactionError"])
        original(self)

    monkeypatch.setattr(q14.time, "sleep", lambda segundos: None)
    monkeypatch.setattr(ClientSession, "commit_transaction", falla_la_primera_vez)
    resultado = venta_rc002()
    assert len(llamadas) == 2
    assert resultado["venta"]["id_venta"] == "V017"
    assert unidades(r, "L007") == 21
    assert (contador(db, "ventas"), contador(db, "detalle_ventas")) == (17, 23)


def test_no_reintenta_un_error_que_no_es_transitorio(datos_provistos, monkeypatch):
    llamadas = []

    def falla(self):
        llamadas.append(1)
        raise PyMongoError("fallo permanente")

    monkeypatch.setattr(ClientSession, "commit_transaction", falla)
    antes = snapshot()
    with pytest.raises(PyMongoError):
        venta_rc002()
    assert len(llamadas) == 1
    assert snapshot() == antes


def test_agota_los_reintentos_y_deja_todo_como_estaba(datos_provistos, monkeypatch):
    llamadas = []

    def falla_siempre(self):
        llamadas.append(1)
        raise PyMongoError("conflicto simulado", error_labels=["TransientTransactionError"])

    monkeypatch.setattr(q14.time, "sleep", lambda segundos: None)
    monkeypatch.setattr(ClientSession, "commit_transaction", falla_siempre)
    antes = snapshot()
    with pytest.raises(PyMongoError):
        venta_rc002()
    assert len(llamadas) == q14.INTENTOS
    assert snapshot() == antes


def test_un_rechazo_de_negocio_no_se_reintenta(datos_provistos, monkeypatch):
    llamadas = []
    validar = q14._validar

    def contar(*args):
        llamadas.append(1)
        return validar(*args)

    monkeypatch.setattr(q14, "_validar", contar)
    with pytest.raises(StockInsuficiente):
        q14.registrar_venta("C003", "F006", [item("PRD004", 23)], "Obra social", "RC002")
    assert len(llamadas) == 1


# Concurrencia

def en_paralelo(n, funcion):
    barrera = threading.Barrier(n)
    resultados = []

    def correr():
        barrera.wait()
        try:
            resultados.append(funcion())
        except Exception as e:
            resultados.append(e)

    hilos = [threading.Thread(target=correr) for _ in range(n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    return resultados


def test_dos_hilos_sobre_la_ultima_dispensa(datos_provistos, db, r):
    resultados = en_paralelo(2, venta_rc002)
    exitos = [x for x in resultados if isinstance(x, dict)]
    rechazos = [x for x in resultados if not isinstance(x, dict)]
    assert len(exitos) == 1
    assert len(rechazos) == 1
    assert isinstance(rechazos[0], ValidacionError)
    assert rechazos[0].codigo in ("RECETA_NO_VIGENTE", "RECETA_MODIFICADA")
    assert receta(db, "RC002") == (3, "Completada", None)
    assert unidades(r, "L007") == 21
    assert contador(db, "ventas") == 17
    assert db.ventas.count_documents({"id_receta": "RC002", "estado": "Completada"}) == 3


@pytest.mark.parametrize("ronda", range(3))
def test_ventas_simultaneas_sobre_el_mismo_lote(datos_provistos, db, r, ronda):
    resultados = en_paralelo(HILOS, lambda: q14.registrar_venta("C001", "F001", [item("PRD001", 1)], "Efectivo"))
    errores = [x for x in resultados if not isinstance(x, dict)]
    exitos = [x for x in resultados if isinstance(x, dict)]
    assert errores == []
    n = len(exitos)
    assert n == HILOS
    assert unidades(r, "L001") == 120 - n
    assert r.zscore(claves.UNIDADES, "L001") == 120 - n
    assert contador(db, "ventas") == VENTAS_PROVISTAS + n
    assert contador(db, "detalle_ventas") == DETALLES_PROVISTOS + n
    ids_ventas = sorted(v["venta"]["id_venta"] for v in exitos)
    assert ids_ventas == [f"V{i:03d}" for i in range(VENTAS_PROVISTAS + 1, VENTAS_PROVISTAS + n + 1)]
    assert sorted(d["_id"] for d in db.ventas.find({}, {"_id": 1})) == [
        f"V{i:03d}" for i in range(1, VENTAS_PROVISTAS + n + 1)]
    detalles = sorted(v["venta"]["items"][0]["id_detalle"] for v in exitos)
    assert detalles == [f"D{i:03d}" for i in range(DETALLES_PROVISTOS + 1, DETALLES_PROVISTOS + n + 1)]
    assert db.ventas.count_documents({"_id": {"$in": ids_ventas}, "stock_descontado": True}) == n


# Casos de los datos completos (la primera venta nueva es V032 con el ítem D040)

ACEPTADAS = [
    ("cliente-sin-compras", ("C009", "F008", [item("PRD018", 1)], "Efectivo", None),
     2600, None, [("L025", 59)]),
    ("simple-vigente", ("C016", "F008", [item("PRD015", 1)], "Obra social", "RC014"),
     4300, ("RC014", 1, "Completada", None), [("L024", 119)]),
    ("prolongado-futura", ("C017", "F009", [item("PRD020", 1)], "Obra social", "RC013"),
     5100, ("RC013", 2, "Vigente", "2026-12-03"), [("L028", 69)]),
    ("prolongado-pasada", ("C014", "F010", [item("PRD015", 1)], "Obra social", "RC011"),
     4300, ("RC011", 3, "Completada", None), [("L030", 63)]),
    ("archivada-con-receta", ("C018", "F010", [item("PRD014", 1)], "Obra social", "RC015"),
     6900, ("RC015", 1, "Completada", None), [("L029", 29)]),
    ("receta-de-venta-pendiente", ("C019", "F012", [item("PRD019", 1)], "Obra social", "RC016"),
     8400, ("RC016", 1, "Completada", None), [("L035", 24)]),
    ("orden-por-vencimiento", ("C015", "F003", [item("PRD002", 50)], "Efectivo", None),
     175000, None, [("L019", 25), ("L020", 0), ("L021", 0), ("L022", 148)]),
]


@pytest.mark.parametrize("caso,argumentos,total,receta_final,lotes", ACEPTADAS, ids=[a[0] for a in ACEPTADAS])
def test_datos_completos_aceptadas(datos_completos, db, r, caso, argumentos, total, receta_final, lotes):
    resultado = q14.registrar_venta(*argumentos)
    venta = resultado["venta"]
    assert (venta["id_venta"], venta["items"][0]["id_detalle"]) == ("V032", "D040")
    assert (venta["fecha"], venta["total"], venta["stock_descontado"]) == ("2026-11-03", total, True)
    assert venta["tipo"] == ("Con receta" if argumentos[4] else "Venta libre")
    if receta_final is None:
        assert resultado["receta"] is None
    else:
        id_receta, hechas, estado, proxima = receta_final
        assert resultado["receta"] == {"id_receta": id_receta, "dispensas_realizadas": hechas, "estado": estado,
                                       "proxima_dispensa": proxima}
        doc = db.recetas.find_one({"_id": id_receta})
        assert (doc["dispensas_realizadas"], doc["estado"], fechas.a_iso(doc["proxima_dispensa"])) == (
            hechas, estado, proxima)
    assert [(id_lote, unidades(r, id_lote)) for id_lote, _ in lotes] == lotes
    assert (contador(db, "ventas"), contador(db, "detalle_ventas")) == (32, 40)


def test_datos_completos_orden_por_vencimiento(datos_completos):
    resultado = q14.registrar_venta("C015", "F003", [item("PRD002", 50)], "Efectivo")
    assert resultado["consumos"] == [{"id_lote": "L020", "id_producto": "PRD002", "unidades": 8},
                                     {"id_lote": "L021", "id_producto": "PRD002", "unidades": 40},
                                     {"id_lote": "L022", "id_producto": "PRD002", "unidades": 2}]


RECHAZOS_COMPLETOS = [
    ("cliente-inactivo", "CLIENTE_INACTIVO", ("C012", "F008", [item("PRD016", 1)], "Efectivo", None)),
    ("receta-vencida", "RECETA_NO_VIGENTE", ("C014", "F010", [item("PRD015", 1)], "Obra social", "RC010")),
    ("archivada-sin-receta", "RECETA_REQUERIDA", ("C018", "F010", [item("PRD014", 1)], "Efectivo", None)),
    ("producto-inactivo", "PRODUCTO_INACTIVO", ("C015", "F008", [item("PRD021", 1)], "Efectivo", None)),
    ("farmacia-inactiva", "SUCURSAL_INACTIVA", ("C015", "F013", [item("PRD016", 1)], "Efectivo", None)),
    ("farmaceutico-inactivo", "FARMACEUTICO_INACTIVO", ("C015", "F014", [item("PRD016", 1)], "Efectivo", None)),
    ("stock-vigente-insuficiente", "STOCK_INSUFICIENTE", ("C015", "F003", [item("PRD002", 199)], "Efectivo", None)),
]


@pytest.mark.parametrize("caso,codigo,argumentos", RECHAZOS_COMPLETOS, ids=[c[0] for c in RECHAZOS_COMPLETOS])
def test_datos_completos_rechazos(datos_completos, caso, codigo, argumentos):
    antes = snapshot()
    with pytest.raises((ValidacionError, StockInsuficiente)) as e:
        q14.registrar_venta(*argumentos)
    assert e.value.codigo == codigo
    assert snapshot() == antes


def test_datos_completos_stock_insuficiente_cuenta_solo_lotes_vigentes(datos_completos, r):
    with pytest.raises(StockInsuficiente) as e:
        q14.registrar_venta("C015", "F003", [item("PRD002", 199)], "Efectivo")
    assert (e.value.requerido, e.value.disponible) == (199, 198)
    assert [unidades(r, l) for l in ("L019", "L020", "L021", "L022")] == [25, 8, 40, 150]


# Línea de comandos

def test_cli_exito(datos_completos, db, r):
    salida = correr_cli("q14", "--cliente", "C009", "--farmaceutico", "F008", "--item", "PRD018:1",
                        "--medio-pago", "Efectivo")
    assert salida.returncode == 0, salida.stderr
    resultado = json.loads(salida.stdout)
    assert resultado["venta"]["id_venta"] == "V032"
    assert (resultado["venta"]["tipo"], resultado["venta"]["total"]) == ("Venta libre", 2600)
    assert resultado["venta"]["fecha"] == fechas.a_iso(FECHA_DEL_SISTEMA())
    assert resultado["consumos"] == [{"id_lote": "L025", "id_producto": "PRD018", "unidades": 1}]
    assert resultado["receta"] is None
    assert unidades(r, "L025") == 59


def test_cli_exito_con_receta(datos_completos, db):
    salida = correr_cli("q14", "--cliente", "C016", "--farmaceutico", "F008", "--item", "PRD015:1",
                        "--medio-pago", "Obra social", "--receta", "RC014")
    assert salida.returncode == 0, salida.stderr
    resultado = json.loads(salida.stdout)
    assert resultado["receta"] == {"id_receta": "RC014", "dispensas_realizadas": 1, "estado": "Completada",
                                   "proxima_dispensa": None}


@pytest.mark.parametrize("argumentos,codigo", [
    (["--cliente", "C012", "--farmaceutico", "F008", "--item", "PRD016:1", "--medio-pago", "Efectivo"],
     "CLIENTE_INACTIVO"),
    (["--cliente", "C015", "--farmaceutico", "F003", "--item", "PRD002:199", "--medio-pago", "Efectivo"],
     "STOCK_INSUFICIENTE"),
    (["--cliente", "C018", "--farmaceutico", "F010", "--item", "PRD014:1", "--medio-pago", "Efectivo"],
     "RECETA_REQUERIDA"),
])
def test_cli_rechazo(datos_completos, argumentos, codigo):
    antes = snapshot()
    salida = correr_cli("q14", *argumentos)
    assert salida.returncode == 1
    assert salida.stdout == ""
    assert salida.stderr.startswith(f"Error [{codigo}]: ")
    assert snapshot() == antes
