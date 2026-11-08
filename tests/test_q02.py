import datetime
import json
import pathlib
import subprocess
import sys

from farmared import fechas
from farmared.consultas import q02_ventas_pendientes as q02

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def correr_cli(*argumentos):
    return subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                          text=True, timeout=60)


def test_ventas_pendientes_de_los_provistos(datos_provistos):
    assert q02.ventas_pendientes() == [
        {"id_venta": "V012", "fecha": "2026-10-11", "id_cliente": "C002", "tipo": "Venta libre", "total": 9200,
         "farmaceutico": {"id_farmaceutico": "F005", "nombre": "Natalia", "apellido": "Giménez",
                          "matricula": "MN-18289"},
         "sucursal": {"id_sucursal": "S003", "nombre": "Farmacia Rosario Centro"}},
        {"id_venta": "V011", "fecha": "2026-10-12", "id_cliente": "C007", "tipo": "Con receta", "total": 4800,
         "farmaceutico": {"id_farmaceutico": "F006", "nombre": "Matías", "apellido": "Sandoval",
                          "matricula": "MN-18340"},
         "sucursal": {"id_sucursal": "S004", "nombre": "Farmacia Nueva Córdoba"}},
    ]


def test_misma_fecha_se_ordena_por_id_venta(datos_provistos, db):
    # V011 pasa a la fecha de V012 y vuelve a insertarse, así queda después de V012 en el orden natural
    venta = db.ventas.find_one({"_id": "V011"})
    venta["fecha"] = fechas.a_datetime(datetime.date(2026, 10, 11))
    db.ventas.delete_one({"_id": "V011"})
    db.ventas.insert_one(venta)
    assert [(v["id_venta"], v["fecha"]) for v in q02.ventas_pendientes()] == [
        ("V011", "2026-10-11"), ("V012", "2026-10-11")]


def test_ventas_pendientes_con_datos_completos(datos_completos, db):
    resultado = q02.ventas_pendientes()
    assert [(v["id_venta"], v["fecha"]) for v in resultado] == [
        ("V012", "2026-10-11"), ("V011", "2026-10-12"), ("V025", "2026-10-28"), ("V024", "2026-10-30"),
        ("V023", "2026-10-31")]
    por_id = {v["id_venta"]: v for v in resultado}
    assert (por_id["V023"]["tipo"], por_id["V023"]["total"]) == ("Con receta", 8400)
    assert por_id["V023"]["farmaceutico"]["id_farmaceutico"] == "F012"
    assert por_id["V023"]["farmaceutico"]["matricula"] == "MN-18537"
    assert por_id["V023"]["sucursal"]["id_sucursal"] == "S010"
    assert (por_id["V024"]["tipo"], por_id["V024"]["total"]) == ("Venta libre", 7500)
    assert por_id["V024"]["farmaceutico"]["id_farmaceutico"] == "F008"
    assert por_id["V024"]["sucursal"]["id_sucursal"] == "S006"
    assert set(por_id) == {v["_id"] for v in db.ventas.find({"estado": "Pendiente"})}


def test_resultado_serializable_sin_conversiones(datos_completos):
    resultado = q02.ventas_pendientes()
    assert json.loads(json.dumps(resultado)) == resultado


def test_linea_de_comandos_igual_a_la_funcion(datos_completos):
    salida = correr_cli("q02")
    assert salida.returncode == 0, salida.stderr
    assert json.loads(salida.stdout) == q02.ventas_pendientes()


def test_linea_de_comandos_rechaza_argumentos_de_mas():
    salida = correr_cli("q02", "--estado", "Pendiente")
    assert salida.returncode == 2
    assert salida.stdout == ""
