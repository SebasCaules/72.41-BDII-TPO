import datetime
import json
import pathlib
import subprocess
import sys

import pytest

from farmared import fechas, formato
from farmared.consultas import q03_historial_cliente as q03
from farmared.errores import NoEncontrado

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CAMPOS_VENTA = {"registro", "id", "fecha", "tipo", "estado", "total", "id_receta", "id_farmaceutico", "items"}
CAMPOS_RECETA = {"registro", "id", "fecha", "tipo", "estado", "medico", "dispensas_autorizadas",
                 "dispensas_realizadas", "proxima_dispensa"}


def correr_cli(*argumentos):
    return subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                          text=True, timeout=60)


def resumen(historial):
    return [(h["registro"], h["id"], h["fecha"]) for h in historial]


def test_historial_de_c001_con_los_provistos(datos_provistos):
    resultado = q03.historial_cliente("C001")
    assert resumen(resultado) == [
        ("receta", "RC001", "2026-09-10"), ("venta", "V003", "2026-09-10"), ("venta", "V015", "2026-09-25"),
        ("venta", "V013", "2026-10-02"), ("receta", "RC008", "2026-10-08"), ("venta", "V010", "2026-10-08")]
    assert [h["estado"] for h in resultado] == [
        "Completada", "Completada", "Anulada", "Completada", "Completada", "Completada"]


def test_historial_de_c006_con_los_provistos(datos_provistos):
    assert resumen(q03.historial_cliente("C006")) == [
        ("receta", "RC003", "2026-08-01"), ("venta", "V006", "2026-08-01"), ("venta", "V007", "2026-09-01"),
        ("receta", "RC004", "2026-09-20"), ("venta", "V008", "2026-09-20"), ("venta", "V016", "2026-10-07")]


def test_mismo_tipo_y_fecha_se_ordena_por_id(datos_provistos, db):
    # V013 pasa a la fecha de V015 y vuelve a insertarse, así queda después de V015 en el orden natural
    venta = db.ventas.find_one({"_id": "V013"})
    venta["fecha"] = fechas.a_datetime(datetime.date(2026, 9, 25))
    db.ventas.delete_one({"_id": "V013"})
    db.ventas.insert_one(venta)
    assert resumen(q03.historial_cliente("C001")) == [
        ("receta", "RC001", "2026-09-10"), ("venta", "V003", "2026-09-10"), ("venta", "V013", "2026-09-25"),
        ("venta", "V015", "2026-09-25"), ("receta", "RC008", "2026-10-08"), ("venta", "V010", "2026-10-08")]


def test_registros_traen_los_campos_de_cada_tipo(datos_provistos, db):
    resultado = q03.historial_cliente("C006")
    for registro in resultado:
        assert set(registro) == (CAMPOS_VENTA if registro["registro"] == "venta" else CAMPOS_RECETA)
    por_id = {h["id"]: h for h in resultado}
    assert por_id["RC004"] == {
        "registro": "receta", "id": "RC004", "fecha": "2026-09-20", "tipo": "Tratamiento prolongado",
        "estado": "Vigente", "medico": "Dr. Pablo Echeverría", "dispensas_autorizadas": 3,
        "dispensas_realizadas": 1, "proxima_dispensa": "2026-10-20"}
    assert por_id["V008"] == {
        "registro": "venta", "id": "V008", "fecha": "2026-09-20", "tipo": "Con receta", "estado": "Completada",
        "total": 8900, "id_receta": "RC004", "id_farmaceutico": "F002",
        "items": formato.a_json(db.ventas.find_one({"_id": "V008"})["items"])}
    assert por_id["V016"]["id_receta"] is None


def test_historial_con_datos_completos(datos_completos):
    assert resumen(q03.historial_cliente("C014")) == [
        ("receta", "RC010", "2026-04-10"), ("receta", "RC011", "2026-08-25"), ("venta", "V020", "2026-08-26"),
        ("venta", "V021", "2026-09-26"), ("receta", "RC012", "2026-10-14"), ("venta", "V022", "2026-10-14")]
    assert [h["id"] for h in q03.historial_cliente("C001")] == ["RC001", "V003", "V015", "V013", "RC008", "V010"]


def test_cliente_sin_ventas_ni_recetas_da_lista_vacia(datos_provistos):
    assert q03.historial_cliente("C008") == []


def test_cliente_inexistente_lanza_no_encontrado(datos_provistos):
    with pytest.raises(NoEncontrado) as capturado:
        q03.historial_cliente("C999")
    assert capturado.value.codigo == "CLIENTE_INEXISTENTE"


def test_id_cliente_es_un_argumento_real(datos_completos, db):
    for id_cliente in ("C001", "C006", "C014"):
        resultado = q03.historial_cliente(id_cliente)
        ventas = {v["_id"] for v in db.ventas.find({"id_cliente": id_cliente})}
        recetas = {r["_id"] for r in db.recetas.find({"id_cliente": id_cliente})}
        assert {h["id"] for h in resultado} == ventas | recetas
    assert q03.historial_cliente("C001") != q03.historial_cliente("C006")


def test_plan_usa_indices_en_ventas_y_recetas(datos_provistos, db):
    plan = db.command("explain", {"aggregate": "ventas", "pipeline": q03.pipeline("C001"), "cursor": {}},
                      verbosity="executionStats")
    assert "IXSCAN" in json.dumps(plan, default=str)
    cursor = next(s for s in plan["stages"] if "$cursor" in s)
    union = next(s for s in plan["stages"] if "$unionWith" in s)
    for etapa in (cursor, union):
        texto = json.dumps(etapa, default=str)
        assert "id_cliente_1_fecha" in texto
        assert "COLLSCAN" not in texto


def test_resultado_serializable_sin_conversiones(datos_completos):
    resultado = q03.historial_cliente("C014")
    assert json.loads(json.dumps(resultado)) == resultado


def test_linea_de_comandos_igual_a_la_funcion(datos_completos):
    for id_cliente in ("C001", "C014"):
        salida = correr_cli("q03", id_cliente)
        assert salida.returncode == 0, salida.stderr
        assert json.loads(salida.stdout) == q03.historial_cliente(id_cliente)


def test_linea_de_comandos_con_cliente_inexistente(datos_completos):
    salida = correr_cli("q03", "C999")
    assert salida.returncode == 1
    assert salida.stderr.startswith("Error [CLIENTE_INEXISTENTE]:")
    assert salida.stdout == ""


def test_linea_de_comandos_con_parametros_mal_formados():
    for argumentos in (("q03",), ("q03", "C001", "C006")):
        salida = correr_cli(*argumentos)
        assert salida.returncode == 2
        assert salida.stdout == ""
