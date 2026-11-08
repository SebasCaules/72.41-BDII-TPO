import json
import pathlib
import subprocess
import sys
import threading

import pytest
from pymongo.collection import Collection
from pymongo.errors import OperationFailure

import snapshots
from farmared import claves, conexiones, fechas, ids, stock
from farmared.consultas import q15_descontar_stock as q15
from farmared.errores import NoEncontrado, StockInsuficiente, ValidacionError

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def correr_cli(*argumentos):
    return subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                          text=True, timeout=60)


def unidades(r, id_lote):
    return int(r.hget(claves.lote(id_lote), "unidades"))


def insertar_venta(db, id_cliente, id_farmaceutico, items, estado="Completada"):
    """Inserta a mano una venta sin descuento de stock, como una venta importada."""
    detalle = []
    for id_producto, cantidad in items:
        precio = db.productos.find_one({"_id": id_producto})["precio_unit"]
        detalle.append({"id_detalle": ids.siguiente_id("detalle_ventas", "D"), "id_producto": id_producto,
                        "cantidad": cantidad, "precio_unit": precio})
    venta = {"_id": ids.siguiente_id("ventas", "V"), "id_cliente": id_cliente, "id_farmaceutico": id_farmaceutico,
             "id_receta": None, "fecha": fechas.a_datetime(fechas.hoy()), "tipo": "Venta libre",
             "medio_pago": "Efectivo", "total": sum(d["cantidad"] * d["precio_unit"] for d in detalle),
             "estado": estado, "items": detalle, "stock_descontado": False}
    db.ventas.insert_one(venta)
    return venta["_id"]


def snapshot():
    return snapshots.mongo_snap(), snapshots.redis_snap()


def test_descuenta_y_marca_la_venta(datos_provistos, db, r):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD002", 1)])
    assert id_venta == "V017"
    resultado = q15.descontar_stock_venta(id_venta)
    consumos = [{"id_lote": "L004", "id_producto": "PRD002", "unidades": 1}]
    assert resultado == {"id_venta": "V017", "id_sucursal": "S001", "consumos": consumos}
    assert unidades(r, "L004") == 89
    assert r.zscore(claves.UNIDADES, "L004") == 89
    venta = db.ventas.find_one({"_id": "V017"})
    assert (venta["stock_descontado"], venta["consumos"]) == (True, consumos)


def test_segunda_llamada_no_toca_redis(datos_provistos, db, r):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD002", 1)])
    q15.descontar_stock_venta(id_venta)
    antes = snapshot()
    with pytest.raises(ValidacionError) as e:
        q15.descontar_stock_venta(id_venta)
    assert e.value.codigo == "STOCK_YA_DESCONTADO"
    assert snapshot() == antes
    assert unidades(r, "L004") == 89


def test_venta_cargada_como_completada_ya_descontada(datos_provistos):
    antes = snapshot()
    with pytest.raises(ValidacionError) as e:
        q15.descontar_stock_venta("V002")
    assert e.value.codigo == "STOCK_YA_DESCONTADO"
    assert snapshot() == antes


@pytest.mark.parametrize("id_venta", ["V012", "V015"])
def test_venta_pendiente_o_anulada(datos_provistos, id_venta):
    antes = snapshot()
    with pytest.raises(ValidacionError) as e:
        q15.descontar_stock_venta(id_venta)
    assert e.value.codigo == "VENTA_NO_COMPLETADA"
    assert snapshot() == antes


def test_venta_pendiente_insertada_sin_descuento(datos_provistos, db):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD002", 1)], estado="Pendiente")
    antes = snapshot()
    with pytest.raises(ValidacionError) as e:
        q15.descontar_stock_venta(id_venta)
    assert e.value.codigo == "VENTA_NO_COMPLETADA"
    assert snapshot() == antes


def test_venta_inexistente(datos_provistos):
    antes = snapshot()
    with pytest.raises(NoEncontrado) as e:
        q15.descontar_stock_venta("V999")
    assert e.value.codigo == "VENTA_INEXISTENTE"
    assert snapshot() == antes


def test_usa_la_sucursal_del_farmaceutico(datos_provistos, db, r):
    id_venta = insertar_venta(db, "C005", "F003", [("PRD001", 2)])
    resultado = q15.descontar_stock_venta(id_venta)
    assert resultado["id_sucursal"] == "S002"
    assert resultado["consumos"] == [{"id_lote": "L002", "id_producto": "PRD001", "unidades": 2}]
    assert (unidades(r, "L001"), unidades(r, "L002")) == (120, 33)


def test_agrupa_los_items_por_producto_y_respeta_fefo(datos_provistos, db, r):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD003", 30), ("PRD001", 1), ("PRD003", 12)])
    assert q15.descontar_stock_venta(id_venta)["consumos"] == [
        {"id_lote": "L005", "id_producto": "PRD003", "unidades": 40},
        {"id_lote": "L015", "id_producto": "PRD003", "unidades": 2},
        {"id_lote": "L001", "id_producto": "PRD001", "unidades": 1}]
    assert (unidades(r, "L005"), unidades(r, "L015"), unidades(r, "L001")) == (0, 98, 119)


def test_stock_insuficiente_no_modifica_nada(datos_provistos, db):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD001", 5), ("PRD003", 141)])
    antes = snapshot()
    with pytest.raises(StockInsuficiente) as e:
        q15.descontar_stock_venta(id_venta)
    assert (e.value.id_producto, e.value.requerido, e.value.disponible) == ("PRD003", 141, 140)
    assert snapshot() == antes


def test_lote_vencido_no_se_consume(datos_provistos, db):
    id_venta = insertar_venta(db, "C005", "F003", [("PRD010", 1)])
    antes = snapshot()
    with pytest.raises(StockInsuficiente) as e:
        q15.descontar_stock_venta(id_venta)
    assert (e.value.id_producto, e.value.requerido, e.value.disponible) == ("PRD010", 1, 0)
    assert snapshot() == antes


def test_fallo_despues_del_script_restaura_redis(datos_provistos, db, monkeypatch):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD003", 42), ("PRD002", 1)])
    antes = snapshot()
    llamadas = []

    def falla(self, *args, **kwargs):
        llamadas.append(args[0])
        raise OperationFailure("fallo simulado al marcar la venta")

    monkeypatch.setattr(Collection, "update_one", falla)
    with pytest.raises(OperationFailure):
        q15.descontar_stock_venta(id_venta)
    assert llamadas == [{"_id": id_venta, "stock_descontado": False}]
    assert snapshot() == antes


def test_otra_llamada_marca_la_venta_mientras_tanto(datos_provistos, db, monkeypatch, r):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD002", 1)])
    original = stock.descontar_fefo

    def descontar_y_adelantarse(id_sucursal, items):
        consumos = original(id_sucursal, items)
        # otra llamada termina primero: descontó lo suyo y marcó la venta
        original(id_sucursal, items)
        db.ventas.update_one({"_id": id_venta}, {"$set": {"stock_descontado": True, "consumos": consumos}})
        return consumos

    monkeypatch.setattr(stock, "descontar_fefo", descontar_y_adelantarse)
    with pytest.raises(ValidacionError) as e:
        q15.descontar_stock_venta(id_venta)
    assert e.value.codigo == "STOCK_YA_DESCONTADO"
    assert unidades(r, "L004") == 89


def test_dos_llamadas_a_la_vez_descuentan_una_sola_vez(datos_provistos, db, r):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD002", 1)])
    barrera = threading.Barrier(2)
    resultados = []

    def descontar():
        barrera.wait()
        try:
            resultados.append(q15.descontar_stock_venta(id_venta)["consumos"])
        except ValidacionError as e:
            resultados.append(e.codigo)

    hilos = [threading.Thread(target=descontar) for _ in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert sorted(resultados, key=str) == sorted(
        [[{"id_lote": "L004", "id_producto": "PRD002", "unidades": 1}], "STOCK_YA_DESCONTADO"], key=str)
    assert unidades(r, "L004") == 89


def test_dentro_de_una_transaccion_abortada_la_marca_no_queda(datos_provistos, db, r):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD002", 1)])
    with conexiones.get_client().start_session() as s:
        s.start_transaction()
        consumos = q15.descontar_stock_venta(id_venta, session=s)["consumos"]
        s.abort_transaction()
    assert db.ventas.find_one({"_id": id_venta})["stock_descontado"] is False
    # el que llama compensa lo que q15 devolvió
    stock.reponer(consumos)
    assert unidades(r, "L004") == 90


def test_resultado_serializable_en_json(datos_provistos, db):
    resultado = q15.descontar_stock_venta(insertar_venta(db, "C005", "F001", [("PRD002", 1)]))
    assert json.loads(json.dumps(resultado)) == resultado


@pytest.mark.parametrize("id_venta,codigo", [
    ("V017", "STOCK_YA_DESCONTADO"),
    ("V024", "VENTA_NO_COMPLETADA"),
    ("V026", "VENTA_NO_COMPLETADA"),
])
def test_casos_con_datos_completos(datos_completos, id_venta, codigo):
    antes = snapshot()
    with pytest.raises(ValidacionError) as e:
        q15.descontar_stock_venta(id_venta)
    assert e.value.codigo == codigo
    assert snapshot() == antes


def test_cli_exito(datos_completos, db, r):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD002", 1)])
    assert id_venta == "V032"
    salida = correr_cli("q15", id_venta)
    assert salida.returncode == 0, salida.stderr
    assert json.loads(salida.stdout) == {
        "id_venta": "V032", "id_sucursal": "S001",
        "consumos": [{"id_lote": "L004", "id_producto": "PRD002", "unidades": 1}]}
    assert unidades(r, "L004") == 89
    assert db.ventas.find_one({"_id": "V032"})["stock_descontado"] is True


@pytest.mark.parametrize("id_venta,codigo", [
    ("V017", "STOCK_YA_DESCONTADO"),
    ("V024", "VENTA_NO_COMPLETADA"),
    ("V026", "VENTA_NO_COMPLETADA"),
    ("V999", "VENTA_INEXISTENTE"),
])
def test_cli_rechazo(datos_completos, id_venta, codigo):
    antes = snapshot()
    salida = correr_cli("q15", id_venta)
    assert salida.returncode == 1
    assert salida.stdout == ""
    assert salida.stderr.startswith(f"Error [{codigo}]: ")
    assert snapshot() == antes
