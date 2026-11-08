import datetime
import json
import pathlib
import subprocess
import sys

import pytest

from farmared import claves, fechas
from farmared.consultas import q08_lotes_stock_bajo as q08

RAIZ = pathlib.Path(__file__).resolve().parent.parent
# Se toma antes de que conftest fije "hoy": es la fecha que usa la consulta corrida en un subproceso.
FECHA_DEL_SISTEMA = fechas.hoy


def correr_cli(*argumentos):
    return subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                          text=True, timeout=60)


def resumen(resultado):
    return [(l["id_lote"], l["unidades"], l["vencido"]) for l in resultado]


def test_valores_de_control_con_datos_provistos(datos_provistos):
    assert resumen(q08.lotes_stock_bajo()) == [
        ("L010", 12, False), ("L018", 15, True), ("L003", 18, False), ("L007", 22, False), ("L012", 30, True),
        ("L002", 35, False), ("L005", 40, False), ("L014", 45, False), ("L011", 48, False)]


def test_lote_con_exactamente_el_umbral_no_sale(datos_provistos, r):
    r.hset(claves.lote("L011"), "unidades", 50)
    r.zadd(claves.UNIDADES, {"L011": 50})
    ids = [l["id_lote"] for l in q08.lotes_stock_bajo()]
    assert "L011" not in ids
    assert ids == ["L010", "L018", "L003", "L007", "L012", "L002", "L005", "L014"]


@pytest.mark.parametrize("unidades,sale", [(49, True), (50, False)])
def test_el_umbral_por_defecto_es_50(datos_provistos, r, unidades, sale):
    r.hset(claves.lote("L011"), "unidades", unidades)
    r.zadd(claves.UNIDADES, {"L011": unidades})
    assert ("L011" in [l["id_lote"] for l in q08.lotes_stock_bajo()]) is sale


def test_combina_el_lote_de_redis_con_los_nombres_de_mongo(datos_provistos, db, r):
    lote = r.hgetall(claves.lote("L007"))
    producto = db.productos.find_one({"_id": lote["id_producto"]})
    proveedor = db.proveedores.find_one({"_id": producto["id_proveedor"]})
    sucursal = db.sucursales.find_one({"_id": lote["id_sucursal"]})
    elemento = next(l for l in q08.lotes_stock_bajo() if l["id_lote"] == "L007")
    assert elemento == {
        "id_lote": "L007", "nro_lote": lote["nro_lote"], "unidades": 22, "vencimiento": lote["vencimiento"],
        "vencido": False, "id_producto": "PRD004", "producto": producto["nombre"], "id_sucursal": "S004",
        "sucursal": sucursal["nombre"], "id_proveedor": producto["id_proveedor"],
        "proveedor": proveedor["razon_social"]}


def test_las_unidades_salen_de_redis_y_los_nombres_de_mongo(datos_provistos, db, r):
    r.hset(claves.lote("L007"), "unidades", 21)
    r.zadd(claves.UNIDADES, {"L007": 21})
    db.productos.update_one({"_id": "PRD004"}, {"$set": {"nombre": "Losartán renombrado"}})
    elemento = next(l for l in q08.lotes_stock_bajo() if l["id_lote"] == "L007")
    assert (elemento["unidades"], elemento["producto"]) == (21, "Losartán renombrado")


def test_umbral_es_un_argumento_real(datos_provistos):
    assert resumen(q08.lotes_stock_bajo(20)) == [("L010", 12, False), ("L018", 15, True), ("L003", 18, False)]
    assert [l["id_lote"] for l in q08.lotes_stock_bajo(48)][-1] == "L014"


def test_incluye_los_lotes_de_la_drogueria(datos_provistos):
    lote = next(l for l in q08.lotes_stock_bajo(3000) if l["id_lote"] == "L017")
    assert (lote["id_sucursal"], lote["unidades"]) == ("S005", 2500)


@pytest.mark.parametrize("hoy,vencido", [(datetime.date(2026, 10, 31), False), (datetime.date(2026, 11, 1), True)])
def test_el_lote_que_vence_hoy_no_esta_vencido(datos_provistos, monkeypatch, hoy, vencido):
    monkeypatch.setattr(fechas, "hoy", lambda: hoy)
    lote = next(l for l in q08.lotes_stock_bajo() if l["id_lote"] == "L012")
    assert lote["vencimiento"] == "2026-10-31"
    assert lote["vencido"] is vencido


def test_sin_lotes_bajo_el_umbral_da_lista_vacia(datos_provistos):
    assert q08.lotes_stock_bajo(12) == []


def test_datos_completos(datos_completos):
    assert resumen(q08.lotes_stock_bajo()) == [
        ("L020", 8, False), ("L010", 12, False), ("L037", 12, True), ("L018", 15, True), ("L003", 18, False),
        ("L031", 18, False), ("L007", 22, False), ("L019", 25, True), ("L035", 25, False), ("L012", 30, True),
        ("L029", 30, False), ("L002", 35, False), ("L033", 36, False), ("L005", 40, False), ("L021", 40, False),
        ("L038", 40, False), ("L032", 44, False), ("L014", 45, False), ("L011", 48, False)]


def test_datos_completos_lote_de_50_afuera_y_sucursal_inactiva_adentro(datos_completos, db):
    resultado = {l["id_lote"]: l for l in q08.lotes_stock_bajo()}
    assert "L023" not in resultado
    assert resultado["L038"]["id_sucursal"] == "S011"
    assert db.sucursales.find_one({"_id": "S011"})["activo"] is False
    assert (resultado["L020"]["vencimiento"], resultado["L020"]["vencido"]) == ("2026-11-27", False)


def test_resultado_serializable_en_json(datos_completos):
    resultado = q08.lotes_stock_bajo()
    assert json.loads(json.dumps(resultado)) == resultado


@pytest.mark.parametrize("argumentos,umbral", [([], 50), (["--umbral", "20"], 20)])
def test_cli_da_lo_mismo_que_la_funcion(datos_completos, monkeypatch, argumentos, umbral):
    resultado = correr_cli("q08", *argumentos)
    assert resultado.returncode == 0, resultado.stderr
    monkeypatch.setattr(fechas, "hoy", FECHA_DEL_SISTEMA)
    assert json.loads(resultado.stdout) == q08.lotes_stock_bajo(umbral)


def test_cli_con_umbral_mal_formado_sale_con_2():
    assert correr_cli("q08", "--umbral", "cincuenta").returncode == 2
