import datetime
import json
import pathlib
import subprocess
import sys

from farmared import fechas
from farmared.consultas import q05_ventas_por_farmaceutico as q05

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def correr_cli(*argumentos):
    return subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                          text=True, timeout=60)


def hoy_del_sistema():
    salida = subprocess.run([sys.executable, "-c", "from farmared import fechas; print(fechas.hoy())"], cwd=RAIZ,
                            capture_output=True, text=True, timeout=60)
    return fechas.desde_iso(salida.stdout.strip())


def conteos(resultado):
    return [(f["id_farmaceutico"], f["cantidad_ventas"]) for f in resultado]


def fijar_hoy(monkeypatch, dia):
    monkeypatch.setattr(fechas, "hoy", lambda: dia)


def test_ventas_recientes_de_los_provistos(datos_provistos):
    resultado = q05.ventas_recientes_por_farmaceutico()
    assert conteos(resultado) == [("F005", 3), ("F001", 2), ("F002", 2), ("F003", 1), ("F006", 1), ("F007", 0)]
    assert resultado[0] == {"id_farmaceutico": "F005", "nombre": "Natalia", "apellido": "Giménez",
                            "matricula": "MN-18289", "id_sucursal": "S003", "cantidad_ventas": 3}
    assert resultado[-1] == {"id_farmaceutico": "F007", "nombre": "Romina", "apellido": "Acuña",
                             "matricula": "MN-18401", "id_sucursal": "S005", "cantidad_ventas": 0}


def test_ventas_recientes_con_datos_completos(datos_completos):
    assert conteos(q05.ventas_recientes_por_farmaceutico()) == [
        ("F005", 3), ("F008", 3), ("F010", 3), ("F001", 2), ("F002", 2), ("F003", 1), ("F006", 1), ("F009", 1),
        ("F012", 1), ("F015", 1), ("F017", 1), ("F018", 1), ("F007", 0), ("F011", 0), ("F013", 0), ("F016", 0)]


def test_el_empate_se_resuelve_por_id_y_no_por_orden_de_insercion(datos_provistos, db):
    # F001 y F002 empatan en 2 ventas; F001 vuelve a insertarse y queda después de F002 en el orden natural
    farmaceutico = db.farmaceuticos.find_one({"_id": "F001"})
    db.farmaceuticos.delete_one({"_id": "F001"})
    db.farmaceuticos.insert_one(farmaceutico)
    naturales = [f["_id"] for f in db.farmaceuticos.find()]
    assert naturales.index("F001") > naturales.index("F002")
    assert conteos(q05.ventas_recientes_por_farmaceutico()) == [
        ("F005", 3), ("F001", 2), ("F002", 2), ("F003", 1), ("F006", 1), ("F007", 0)]


def test_el_resultado_sigue_a_la_fecha_de_hoy(datos_provistos, monkeypatch):
    con_hoy_fijo = conteos(q05.ventas_recientes_por_farmaceutico())
    # V003 de F001 es del 2026-09-10: entra en la ventana mientras hoy sea a lo sumo 60 días después
    fijar_hoy(monkeypatch, datetime.date(2026, 11, 9))
    assert dict(conteos(q05.ventas_recientes_por_farmaceutico()))["F001"] == 2
    fijar_hoy(monkeypatch, datetime.date(2026, 11, 10))
    otro_dia = conteos(q05.ventas_recientes_por_farmaceutico())
    assert dict(otro_dia)["F001"] == 1
    assert otro_dia != con_hoy_fijo


def test_la_ventana_incluye_hoy_y_no_cuenta_ventas_posteriores(datos_provistos, monkeypatch):
    # V010 de F003 es del 2026-10-08
    fijar_hoy(monkeypatch, datetime.date(2026, 10, 8))
    assert dict(conteos(q05.ventas_recientes_por_farmaceutico()))["F003"] == 1
    fijar_hoy(monkeypatch, datetime.date(2026, 10, 7))
    assert dict(conteos(q05.ventas_recientes_por_farmaceutico()))["F003"] == 0


def test_no_cuenta_las_anuladas_y_si_las_pendientes(datos_provistos, db):
    db.ventas.update_one({"_id": "V015"}, {"$set": {"estado": "Completada"}})
    db.ventas.update_one({"_id": "V012"}, {"$set": {"estado": "Anulada"}})
    resultado = dict(conteos(q05.ventas_recientes_por_farmaceutico()))
    assert resultado["F002"] == 3
    assert resultado["F005"] == 2


def test_dias_es_un_argumento_real(datos_provistos):
    assert q05.ventas_recientes_por_farmaceutico(60) == q05.ventas_recientes_por_farmaceutico()
    # con hoy = 2026-11-03, 26 días alcanzan hasta el 2026-10-08, el día de V010 de F003
    assert conteos(q05.ventas_recientes_por_farmaceutico(dias=26)) == [
        ("F003", 1), ("F005", 1), ("F006", 1), ("F001", 0), ("F002", 0), ("F007", 0)]
    assert conteos(q05.ventas_recientes_por_farmaceutico(dias=25)) == [
        ("F005", 1), ("F006", 1), ("F001", 0), ("F002", 0), ("F003", 0), ("F007", 0)]


def test_lookup_usa_el_indice_de_farmaceutico_y_fecha(datos_provistos, db):
    hasta = fechas.a_datetime(fechas.hoy())
    pipeline = q05.pipeline(hasta - datetime.timedelta(days=60), hasta)
    plan = db.command("explain", {"aggregate": "farmaceuticos", "pipeline": pipeline, "cursor": {}},
                      verbosity="executionStats")
    lookup = next(s for s in plan["stages"] if "$lookup" in s)
    assert lookup["indexesUsed"] == ["id_farmaceutico_1_fecha_1"]
    assert lookup["collectionScans"] == 0
    cursor = next(s for s in plan["stages"] if "$cursor" in s)
    assert "COLLSCAN" in json.dumps(cursor, default=str)


def test_resultado_serializable_sin_conversiones(datos_completos):
    resultado = q05.ventas_recientes_por_farmaceutico()
    assert json.loads(json.dumps(resultado)) == resultado


def test_linea_de_comandos_igual_a_la_funcion(datos_completos, monkeypatch):
    fijar_hoy(monkeypatch, hoy_del_sistema())
    salida = correr_cli("q05")
    assert salida.returncode == 0, salida.stderr
    assert json.loads(salida.stdout) == q05.ventas_recientes_por_farmaceutico()
    salida = correr_cli("q05", "--dias", "400")
    assert salida.returncode == 0, salida.stderr
    assert json.loads(salida.stdout) == q05.ventas_recientes_por_farmaceutico(400)
    assert q05.ventas_recientes_por_farmaceutico(400) != q05.ventas_recientes_por_farmaceutico()


def test_linea_de_comandos_con_parametros_mal_formados():
    for argumentos in (("q05", "--dias", "sesenta"), ("q05", "--dias"), ("q05", "60")):
        salida = correr_cli(*argumentos)
        assert salida.returncode == 2
        assert salida.stdout == ""
