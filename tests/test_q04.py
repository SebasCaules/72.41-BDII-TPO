import json
import pathlib
import subprocess
import sys

from farmared.consultas import q04_clientes_varias_recetas as q04

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def correr_cli(*argumentos):
    return subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                          text=True, timeout=60)


def test_clientes_con_varias_recetas_de_los_provistos(datos_provistos):
    assert q04.clientes_con_varias_recetas() == [
        {"id_cliente": "C001", "nombre": "Lucía", "apellido": "Fernández", "cantidad_recetas": 2},
        {"id_cliente": "C002", "nombre": "Martín", "apellido": "Gómez", "cantidad_recetas": 2},
        {"id_cliente": "C006", "nombre": "Ricardo", "apellido": "Paz", "cantidad_recetas": 2},
    ]


def test_clientes_con_varias_recetas_con_datos_completos(datos_completos, db):
    resultado = q04.clientes_con_varias_recetas()
    assert [(c["id_cliente"], c["cantidad_recetas"]) for c in resultado] == [
        ("C014", 3), ("C001", 2), ("C002", 2), ("C006", 2)]
    assert resultado[0] == {"id_cliente": "C014", "nombre": "Norma", "apellido": "Castillo", "cantidad_recetas": 3}
    for cliente in resultado:
        assert db.recetas.count_documents({"id_cliente": cliente["id_cliente"]}) == cliente["cantidad_recetas"]


def test_resultado_serializable_sin_conversiones(datos_completos):
    resultado = q04.clientes_con_varias_recetas()
    assert json.loads(json.dumps(resultado)) == resultado


def test_linea_de_comandos_igual_a_la_funcion(datos_completos):
    salida = correr_cli("q04")
    assert salida.returncode == 0, salida.stderr
    assert json.loads(salida.stdout) == q04.clientes_con_varias_recetas()


def test_linea_de_comandos_rechaza_argumentos_de_mas():
    salida = correr_cli("q04", "2")
    assert salida.returncode == 2
    assert salida.stdout == ""
