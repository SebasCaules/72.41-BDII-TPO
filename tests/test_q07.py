import datetime
import json
import pathlib
import subprocess
import sys

import pytest

from farmared import conexiones
from farmared.consultas import q07_top_productos as q07
from farmared.errores import ValidacionError

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def correr_cli(*argumentos):
    return subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                          text=True, timeout=60)


def resumen(resultado):
    return [(p["id_producto"], p["unidades"]) for p in resultado]


def insertar_venta(db, id_venta, estado, items):
    db.ventas.insert_one({
        "_id": id_venta, "id_cliente": "C001", "id_farmaceutico": "F001", "id_receta": None,
        "fecha": datetime.datetime(2026, 11, 2), "tipo": "Venta libre", "medio_pago": "Efectivo",
        "total": sum(cantidad * 1000 for _, cantidad in items), "estado": estado,
        "items": [{"id_detalle": f"D9{i:02d}", "id_producto": p, "cantidad": c, "precio_unit": 1000}
                  for i, (p, c) in enumerate(items)],
        "stock_descontado": estado == "Completada"})


def test_valores_de_control_con_datos_provistos(datos_provistos):
    assert resumen(q07.top_productos_vendidos()) == [
        ("PRD005", 6), ("PRD011", 5), ("PRD001", 4), ("PRD004", 3), ("PRD009", 2)]


def test_cada_elemento_trae_id_nombre_y_unidades(datos_provistos):
    assert q07.top_productos_vendidos()[0] == {"id_producto": "PRD005", "nombre": "Metformina 850mg x60",
                                               "unidades": 6}


def test_empate_en_el_quinto_puesto_entra_el_de_menor_id(datos_provistos, db):
    insertar_venta(db, "V900", "Completada", [("PRD010", 1)])
    resultado = resumen(q07.top_productos_vendidos())
    assert resultado[4] == ("PRD009", 2)
    assert ("PRD010", 2) not in resultado
    assert len(resultado) == 5


def test_empate_con_un_id_menor_desplaza_al_quinto(datos_provistos, db):
    insertar_venta(db, "V900", "Completada", [("PRD008", 1)])
    assert resumen(q07.top_productos_vendidos()) == [
        ("PRD005", 6), ("PRD011", 5), ("PRD001", 4), ("PRD004", 3), ("PRD008", 2)]


def test_solo_cuentan_las_ventas_completadas(datos_provistos, db):
    insertar_venta(db, "V900", "Pendiente", [("PRD013", 50)])
    insertar_venta(db, "V901", "Anulada", [("PRD006", 40)])
    assert resumen(q07.top_productos_vendidos()) == [
        ("PRD005", 6), ("PRD011", 5), ("PRD001", 4), ("PRD004", 3), ("PRD009", 2)]


def test_suma_las_unidades_de_varios_items_y_ventas(datos_provistos, db):
    insertar_venta(db, "V900", "Completada", [("PRD006", 3), ("PRD007", 1)])
    insertar_venta(db, "V901", "Completada", [("PRD006", 4)])
    assert resumen(q07.top_productos_vendidos(2)) == [("PRD006", 8), ("PRD005", 6)]


def test_datos_completos_dejan_afuera_por_id_a_los_empatados(datos_completos):
    assert resumen(q07.top_productos_vendidos()) == [
        ("PRD005", 6), ("PRD011", 6), ("PRD001", 4), ("PRD004", 3), ("PRD009", 3)]


def test_limite_es_un_argumento_real(datos_completos):
    assert resumen(q07.top_productos_vendidos(3)) == [("PRD005", 6), ("PRD011", 6), ("PRD001", 4)]
    assert resumen(q07.top_productos_vendidos(7))[4:] == [("PRD009", 3), ("PRD016", 3), ("PRD017", 3)]


def test_limite_mayor_que_los_productos_vendidos_los_devuelve_todos(datos_provistos):
    assert len(q07.top_productos_vendidos(100)) == 11


@pytest.mark.parametrize("limite", [0, -1])
def test_limite_menor_que_uno_se_rechaza_antes_de_consultar(monkeypatch, limite):
    def sin_base():
        raise AssertionError("no debe consultar MongoDB")

    monkeypatch.setattr(conexiones, "get_db", sin_base)
    with pytest.raises(ValidacionError) as capturado:
        q07.top_productos_vendidos(limite)
    assert capturado.value.codigo == "DATO_INVALIDO"


def test_resultado_serializable_en_json(datos_completos):
    resultado = q07.top_productos_vendidos()
    assert json.loads(json.dumps(resultado)) == resultado


@pytest.mark.parametrize("argumentos,limite", [([], 5), (["--limite", "3"], 3)])
def test_cli_da_lo_mismo_que_la_funcion(datos_completos, argumentos, limite):
    resultado = correr_cli("q07", *argumentos)
    assert resultado.returncode == 0, resultado.stderr
    assert json.loads(resultado.stdout) == q07.top_productos_vendidos(limite)


def test_cli_con_limite_mal_formado_sale_con_2():
    assert correr_cli("q07", "--limite", "tres").returncode == 2


def test_cli_con_limite_cero_informa_el_error():
    resultado = correr_cli("q07", "--limite", "0")
    assert resultado.returncode == 1
    assert resultado.stderr.startswith("Error [DATO_INVALIDO]")
