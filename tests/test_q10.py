import json
import pathlib
import subprocess
import sys

import pytest

from farmared.consultas import q10_clientes_por_sucursal as q10
from farmared.errores import NoEncontrado

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def correr_cli(*argumentos):
    return subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                          text=True, timeout=60)


def resumen(resultado):
    return [(c["id_cliente"], c["cantidad_ventas"]) for c in resultado]


def test_valores_de_control_s001(datos_provistos):
    assert resumen(q10.clientes_por_sucursal("S001")) == [("C001", 3), ("C006", 4)]


def test_valores_de_control_s002_incluye_la_venta_de_un_farmaceutico_inactivo(datos_provistos, db):
    assert db.farmaceuticos.find_one({"_id": "F004"})["activo"] is False
    assert resumen(q10.clientes_por_sucursal("S002")) == [("C001", 1), ("C004", 1)]


def test_cada_elemento_trae_los_datos_del_cliente(datos_provistos, db):
    c004 = db.clientes.find_one({"_id": "C004"})
    assert q10.clientes_por_sucursal("S002")[1] == {
        "id_cliente": "C004", "nombre": c004["nombre"], "apellido": c004["apellido"], "dni": c004["dni"],
        "activo": c004["activo"], "cantidad_ventas": 1}


def test_cuenta_ventas_en_cualquier_estado(datos_provistos, db):
    de_s001 = {"id_cliente": "C001", "id_farmaceutico": {"$in": ["F001", "F002"]}}
    estados = {v["estado"] for v in db.ventas.find(de_s001)}
    assert "Anulada" in estados
    assert dict(resumen(q10.clientes_por_sucursal("S001")))["C001"] == 3


def test_sucursal_sin_ventas_da_lista_vacia(datos_provistos):
    assert q10.clientes_por_sucursal("S005") == []


def test_sucursal_inexistente_lanza_no_encontrado(datos_provistos):
    with pytest.raises(NoEncontrado) as capturado:
        q10.clientes_por_sucursal("S999")
    assert capturado.value.codigo == "SUCURSAL_INEXISTENTE"


def test_id_sucursal_es_un_argumento_real(datos_provistos):
    assert q10.clientes_por_sucursal("S001") != q10.clientes_por_sucursal("S002")


@pytest.mark.parametrize("id_sucursal,esperado", [
    ("S001", [("C001", 3), ("C006", 4)]),
    ("S006", [("C011", 1), ("C012", 1), ("C015", 2), ("C016", 1)]),
    ("S009", []),
])
def test_datos_completos(datos_completos, id_sucursal, esperado):
    assert resumen(q10.clientes_por_sucursal(id_sucursal)) == esperado


def test_datos_completos_s006_incluye_al_cliente_inactivo(datos_completos):
    clientes = {c["id_cliente"]: c for c in q10.clientes_por_sucursal("S006")}
    assert clientes["C012"]["activo"] is False


def test_resultado_serializable_en_json(datos_completos):
    resultado = q10.clientes_por_sucursal("S006")
    assert json.loads(json.dumps(resultado)) == resultado


@pytest.mark.parametrize("id_sucursal", ["S001", "S006"])
def test_cli_da_lo_mismo_que_la_funcion(datos_completos, id_sucursal):
    resultado = correr_cli("q10", id_sucursal)
    assert resultado.returncode == 0, resultado.stderr
    assert json.loads(resultado.stdout) == q10.clientes_por_sucursal(id_sucursal)


def test_cli_sin_sucursal_sale_con_2():
    assert correr_cli("q10").returncode == 2


def test_cli_con_sucursal_inexistente_informa_el_error(datos_completos):
    resultado = correr_cli("q10", "S999")
    assert resultado.returncode == 1
    assert resultado.stderr.startswith("Error [SUCURSAL_INEXISTENTE]")
