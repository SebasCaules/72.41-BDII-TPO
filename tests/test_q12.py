import datetime
import json
import pathlib
import subprocess
import sys

import pytest

from farmared import fechas
from farmared.consultas import q12_clientes_sin_ventas as q12

RAIZ = pathlib.Path(__file__).resolve().parent.parent
# Se toma antes de que conftest fije "hoy": es la fecha que usa la consulta corrida en un subproceso.
FECHA_DEL_SISTEMA = fechas.hoy


def correr_cli(*argumentos):
    return subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                          text=True, timeout=60)


def resumen(resultado):
    return [(c["id_cliente"], c["ultima_venta"] and c["ultima_venta"]["id_venta"]) for c in resultado]


def test_valores_de_control_con_datos_provistos(datos_provistos, db):
    c004 = db.clientes.find_one({"_id": "C004"})
    c008 = db.clientes.find_one({"_id": "C008"})
    assert q12.clientes_sin_ventas() == [
        {"id_cliente": "C004", "nombre": c004["nombre"], "apellido": c004["apellido"], "activo": True,
         "ultima_venta": {"id_venta": "V001", "fecha": "2025-09-18", "estado": "Completada", "total": 3850}},
        {"id_cliente": "C008", "nombre": c008["nombre"], "apellido": c008["apellido"], "activo": False,
         "ultima_venta": None}]


# V001, la única venta de C004, es del 2025-09-18: deja de contar 366 días después.
@pytest.mark.parametrize("hoy,sale", [(datetime.date(2026, 9, 18), False), (datetime.date(2026, 9, 19), True)])
def test_el_ultimo_anio_incluye_el_dia_de_hace_365(datos_provistos, monkeypatch, hoy, sale):
    monkeypatch.setattr(fechas, "hoy", lambda: hoy)
    assert ("C004" in [c["id_cliente"] for c in q12.clientes_sin_ventas()]) is sale


def test_una_venta_reciente_en_cualquier_estado_lo_saca(datos_provistos, db):
    db.ventas.insert_one({"_id": "V900", "id_cliente": "C004", "id_farmaceutico": "F001", "id_receta": None,
                          "fecha": datetime.datetime(2026, 10, 1), "tipo": "Venta libre", "medio_pago": "Efectivo",
                          "total": 2800, "estado": "Anulada", "items": [], "stock_descontado": False})
    assert resumen(q12.clientes_sin_ventas()) == [("C008", None)]


def test_entre_ventas_del_mismo_dia_la_ultima_es_la_de_mayor_id(datos_provistos, db):
    db.ventas.insert_one({"_id": "V900", "id_cliente": "C004", "id_farmaceutico": "F001", "id_receta": None,
                          "fecha": datetime.datetime(2025, 9, 18), "tipo": "Venta libre", "medio_pago": "Efectivo",
                          "total": 1200, "estado": "Completada", "items": [], "stock_descontado": True})
    clientes = {c["id_cliente"]: c for c in q12.clientes_sin_ventas()}
    assert clientes["C004"]["ultima_venta"]["id_venta"] == "V900"


def test_datos_completos(datos_completos):
    assert resumen(q12.clientes_sin_ventas()) == [
        ("C004", "V001"), ("C008", None), ("C009", None), ("C010", None), ("C011", "V028"), ("C012", "V029"),
        ("C018", None)]


def test_datos_completos_activos_e_inactivos_con_su_ultima_venta(datos_completos):
    clientes = {c["id_cliente"]: c for c in q12.clientes_sin_ventas()}
    assert clientes["C012"]["activo"] is False
    assert clientes["C012"]["ultima_venta"] == {"id_venta": "V029", "fecha": "2025-05-06", "estado": "Completada",
                                                "total": 5900}
    assert clientes["C011"]["ultima_venta"]["fecha"] == "2025-07-14"
    assert "C013" not in clientes


def test_resultado_serializable_en_json(datos_completos):
    resultado = q12.clientes_sin_ventas()
    assert json.loads(json.dumps(resultado)) == resultado


def test_cli_da_lo_mismo_que_la_funcion(datos_completos, monkeypatch):
    resultado = correr_cli("q12")
    assert resultado.returncode == 0, resultado.stderr
    monkeypatch.setattr(fechas, "hoy", FECHA_DEL_SISTEMA)
    assert json.loads(resultado.stdout) == q12.clientes_sin_ventas()


def test_cli_con_un_argumento_de_mas_sale_con_2():
    assert correr_cli("q12", "C001").returncode == 2
