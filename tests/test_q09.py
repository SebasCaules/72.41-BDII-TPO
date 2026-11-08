import datetime
import json
import pathlib
import subprocess
import sys

import pytest

from farmared.consultas import q09_ventas_libres_menores as q09

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def correr_cli(*argumentos):
    return subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                          text=True, timeout=60)


def resumen(resultado):
    return [(v["id_venta"], v["total"]) for v in resultado]


def test_valores_de_control_con_datos_provistos(datos_provistos):
    assert resumen(q09.ventas_libres_menores()) == [("V013", 4400), ("V014", 4600)]


def test_cada_elemento_trae_los_campos_de_la_venta(datos_provistos):
    assert q09.ventas_libres_menores()[0] == {
        "id_venta": "V013", "fecha": "2026-10-02", "id_cliente": "C001", "id_farmaceutico": "F001",
        "total": 4400, "estado": "Completada", "medio_pago": "Efectivo"}


def test_la_anulada_no_sale_aunque_cumpla_el_monto(datos_provistos, db):
    v015 = db.ventas.find_one({"_id": "V015"})
    assert (v015["tipo"], v015["total"], v015["estado"]) == ("Venta libre", 3500, "Anulada")
    assert "V015" not in [v["id_venta"] for v in q09.ventas_libres_menores()]


def test_monto_es_un_argumento_real(datos_provistos):
    assert resumen(q09.ventas_libres_menores(4500)) == [("V013", 4400)]
    assert resumen(q09.ventas_libres_menores(4400)) == []


def test_datos_completos_sale_la_pendiente_y_no_la_anulada(datos_completos):
    resultado = q09.ventas_libres_menores()
    assert resumen(resultado) == [("V013", 4400), ("V014", 4600), ("V030", 4200), ("V025", 4000), ("V031", 2600)]
    assert next(v for v in resultado if v["id_venta"] == "V025")["estado"] == "Pendiente"
    assert "V026" not in [v["id_venta"] for v in resultado]


def test_datos_completos_ordenadas_por_fecha(datos_completos):
    fechas = [v["fecha"] for v in q09.ventas_libres_menores()]
    assert fechas == sorted(fechas)


@pytest.mark.parametrize("monto,sale", [(5000, False), (5001, True)])
def test_el_monto_es_exclusivo(datos_completos, monto, sale):
    assert ("V027" in [v["id_venta"] for v in q09.ventas_libres_menores(monto)]) is sale


@pytest.mark.parametrize("total,sale", [(4999, True), (5000, False)])
def test_el_monto_por_defecto_es_5000(datos_completos, db, total, sale):
    db.ventas.update_one({"_id": "V027"}, {"$set": {"total": total}})
    assert ("V027" in [v["id_venta"] for v in q09.ventas_libres_menores()]) is sale


def test_en_la_misma_fecha_desempata_por_id_venta(datos_provistos, db):
    for id_venta in ("V901", "V900"):
        db.ventas.insert_one({"_id": id_venta, "id_cliente": "C001", "id_farmaceutico": "F001", "id_receta": None,
                              "fecha": datetime.datetime(2026, 10, 20), "tipo": "Venta libre",
                              "medio_pago": "Efectivo", "total": 1000, "estado": "Completada", "items": [],
                              "stock_descontado": True})
    assert [v["id_venta"] for v in q09.ventas_libres_menores()] == ["V013", "V014", "V900", "V901"]


def test_resultado_serializable_en_json(datos_completos):
    resultado = q09.ventas_libres_menores()
    assert json.loads(json.dumps(resultado)) == resultado


@pytest.mark.parametrize("argumentos,monto", [([], 5000), (["--monto", "4300"], 4300)])
def test_cli_da_lo_mismo_que_la_funcion(datos_completos, argumentos, monto):
    resultado = correr_cli("q09", *argumentos)
    assert resultado.returncode == 0, resultado.stderr
    assert json.loads(resultado.stdout) == q09.ventas_libres_menores(monto)


def test_cli_con_monto_mal_formado_sale_con_2():
    assert correr_cli("q09", "--monto", "5.000").returncode == 2
