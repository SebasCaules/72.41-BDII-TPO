import importlib
import os
import pathlib
import socket
import subprocess
import sys
import time

import pytest
import redis
from pymongo.errors import AutoReconnect, NetworkTimeout, OperationFailure, ServerSelectionTimeoutError

import farmared.__main__ as terminal
from farmared import conexiones

RAIZ = pathlib.Path(__file__).resolve().parent.parent
# Un motor que no responde se informa en unos 3 s; el margen cubre el arranque de Python y el cierre del cliente.
ESPERA_MAXIMA_S = 10
PUERTO_CERRADO = "127.0.0.1:1"
MARCA = "MARCA_TERMINAL"
VENTA = ["--cliente", "C003", "--farmaceutico", "F006", "--medio-pago", "Efectivo"]


def correr_cli(*argumentos, **entorno):
    inicio = time.monotonic()
    salida = subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                            text=True, timeout=60, env={**os.environ, **entorno})
    return salida, time.monotonic() - inicio


def reemplazar(monkeypatch, comando, funcion):
    modulo, nombre = terminal.CONSULTAS[comando]
    monkeypatch.setattr(importlib.import_module(f"farmared.consultas.{modulo}"), nombre, funcion)


def lanza(error):
    def funcion(*args, **kwargs):
        raise error
    return funcion


@pytest.fixture
def puerto_mudo():
    """Puerto que acepta la conexión y nunca contesta, como un motor congelado."""
    with socket.create_server(("127.0.0.1", 0), backlog=16) as servidor:
        yield f"127.0.0.1:{servidor.getsockname()[1]}"


@pytest.fixture
def sin_ejecutar(monkeypatch):
    """Registra los argumentos que llegan a ejecutar, sin tocar los motores."""
    recibidos = []
    monkeypatch.setattr(terminal, "ejecutar", lambda a: recibidos.append(a) or [])
    return recibidos


# Motor que no responde, con los clientes reales

@pytest.mark.parametrize("motor, comando, entorno", [
    ("MongoDB", "q01", lambda puerto: {"MONGO_URI": f"mongodb://{PUERTO_CERRADO}/?replicaSet=rs0"}),
    ("MongoDB", "q01", lambda puerto: {"MONGO_URI": f"mongodb://{puerto}/?replicaSet=rs0"}),
    ("Redis", "q08", lambda puerto: {"REDIS_URL": f"redis://{PUERTO_CERRADO}"}),
    ("Redis", "q08", lambda puerto: {"REDIS_URL": f"redis://{puerto}"}),
], ids=["mongodb_detenido", "mongodb_congelado", "redis_detenido", "redis_congelado"])
def test_motor_que_no_responde_da_error_de_conexion_sin_traza(puerto_mudo, motor, comando, entorno):
    salida, demora = correr_cli(comando, **entorno(puerto_mudo))
    assert salida.returncode == 1
    assert salida.stdout == ""
    assert salida.stderr == f"Error [CONEXION]: {motor} no responde\n"
    assert demora < ESPERA_MAXIMA_S


@pytest.mark.parametrize("comando", ["carga", "demo"])
def test_comando_que_recarga_no_toca_mongodb_si_redis_no_responde(db, comando):
    db.contadores.insert_one({"_id": MARCA, "ultimo": 0})
    try:
        salida, _ = correr_cli(comando, REDIS_URL=f"redis://{PUERTO_CERRADO}")
        assert salida.returncode == 1
        assert salida.stderr == "Error [CONEXION]: Redis no responde\n"
        assert db.contadores.count_documents({"_id": MARCA}) == 1
    finally:
        db.contadores.delete_one({"_id": MARCA})


def test_validar_la_carga_no_necesita_los_motores():
    salida, _ = correr_cli("carga", "--validar", MONGO_URI=f"mongodb://{PUERTO_CERRADO}/?replicaSet=rs0",
                           REDIS_URL=f"redis://{PUERTO_CERRADO}")
    assert (salida.returncode, salida.stdout, salida.stderr) == (0, "[]\n", "")


def test_base_sin_cargar_da_un_error_de_negocio():
    base = "farmared_sin_carga_test"
    try:
        salida, _ = correr_cli("q13", "alta", "--nombre", "Valeria", "--apellido", "Quiroga", "--dni", "99300400",
                               "--email", "valeria.quiroga@gmail.com", "--telefono", "1162004400",
                               "--ciudad", "La Plata", "--provincia", "Buenos Aires", "--obra-social", "IOMA",
                               "--nro-afiliado", "IO-993004", MONGO_DB=base)
        assert salida.returncode == 1
        assert salida.stderr == ("Error [BASE_SIN_CARGA]: falta el contador clientes: "
                                 "hay que correr python -m farmared carga\n")
    finally:
        conexiones.get_client().drop_database(base)


def test_los_clientes_esperan_unos_segundos():
    assert conexiones.get_client().options.server_selection_timeout == conexiones.ESPERA_S == 3
    opciones = conexiones.get_redis().connection_pool.connection_kwargs
    assert (opciones["socket_connect_timeout"], opciones["socket_timeout"]) == (3, 3)


def test_comprobar_con_los_motores_arriba():
    assert conexiones.comprobar() is None


# Fallo de un motor simulado en el cliente

@pytest.mark.parametrize("comando, error, esperado", [
    ("q01", ServerSelectionTimeoutError("mongo:27017: [Errno -2] Name or service not known, Timeout: 3.0s"),
     "Error [CONEXION]: MongoDB no responde"),
    ("q01", AutoReconnect("mongo:27017: connection closed"), "Error [CONEXION]: MongoDB no responde"),
    ("q01", NetworkTimeout("mongo:27017: timed out"), "Error [CONEXION]: MongoDB no responde"),
    ("q08", redis.exceptions.ConnectionError("Error -2 connecting to redis:6379. Name or service not known."),
     "Error [CONEXION]: Redis no responde"),
    ("q08", redis.exceptions.TimeoutError("Timeout reading from socket"), "Error [CONEXION]: Redis no responde"),
    ("q01", OperationFailure("Expected a positive number in: $limit: 0", 15958,
                             {"ok": 0, "errmsg": "Expected a positive number in: $limit: 0", "code": 15958}),
     "Error [MOTOR]: MongoDB devolvió un error: Expected a positive number in: $limit: 0"),
    ("q08", redis.exceptions.ResponseError("ERR Error running script"),
     "Error [MOTOR]: Redis devolvió un error: ERR Error running script"),
], ids=["seleccion", "conexion_cortada", "respuesta_vencida", "redis_conexion", "redis_respuesta",
        "mongodb_otro", "redis_otro"])
def test_fallo_de_un_motor_se_informa_con_codigo(monkeypatch, capsys, comando, error, esperado):
    reemplazar(monkeypatch, comando, lanza(error))
    assert terminal.main([comando]) == 1
    salida = capsys.readouterr()
    assert (salida.out, salida.err) == ("", esperado + "\n")


def test_conflicto_de_escritura_persistente_se_informa_con_codigo(monkeypatch, capsys):
    conflicto = OperationFailure(
        "Write conflict during plan execution and yielding is disabled.", 112,
        {"ok": 0, "errmsg": "Write conflict during plan execution and yielding is disabled.", "code": 112,
         "codeName": "WriteConflict", "errorLabels": ["TransientTransactionError"]})
    reemplazar(monkeypatch, "q14", lanza(conflicto))
    assert terminal.main(["q14", *VENTA, "--item", "PRD004:1"]) == 1
    assert capsys.readouterr().err == ("Error [CONFLICTO]: otra escritura simultánea en MongoDB canceló la "
                                       "operación; se puede reintentar\n")


def test_la_terminal_no_tiene_una_salida_para_comandos_sin_implementar(monkeypatch):
    reemplazar(monkeypatch, "q01", lanza(NotImplementedError()))
    with pytest.raises(NotImplementedError):
        terminal.main(["q01"])


# Parámetros numéricos

@pytest.mark.parametrize("argumentos, mensaje", [
    (["q05", "--dias", "0"], "los días deben ser al menos 1: 0"),
    (["q05", "--dias", "-5"], "los días deben ser al menos 1: -5"),
    (["q07", "--limite", "0"], "el límite debe ser al menos 1: 0"),
    (["q07", "--limite", "-1"], "el límite debe ser al menos 1: -1"),
    (["q08", "--umbral", "0"], "el umbral debe ser al menos 1: 0"),
    (["q08", "--umbral", "-5"], "el umbral debe ser al menos 1: -5"),
    (["q09", "--monto", "0"], "el monto debe ser al menos 1: 0"),
    (["q09", "--monto", "-1"], "el monto debe ser al menos 1: -1"),
])
def test_parametro_numerico_menor_que_uno_se_rechaza_igual_en_las_cuatro(monkeypatch, capsys, argumentos, mensaje):
    reemplazar(monkeypatch, argumentos[0], lanza(AssertionError("la consulta no debía correr")))
    assert terminal.main(argumentos) == 1
    salida = capsys.readouterr()
    assert (salida.out, salida.err) == ("", f"Error [DATO_INVALIDO]: {mensaje}\n")


@pytest.mark.parametrize("argumentos, parametro", [
    (["q05", "--dias", "1"], {"dias": 1}),
    (["q07", "--limite", "1"], {"limite": 1}),
    (["q08", "--umbral", "1"], {"umbral": 1}),
    (["q09", "--monto", "1"], {"monto": 1}),
])
def test_parametro_numerico_igual_a_uno_llega_a_la_consulta(monkeypatch, capsys, argumentos, parametro):
    recibidos = []
    reemplazar(monkeypatch, argumentos[0], lambda **kwargs: recibidos.append(kwargs) or [])
    assert terminal.main(argumentos) == 0
    assert recibidos == [parametro]
    assert capsys.readouterr().out == "[]\n"


# Ítems de q14

@pytest.mark.parametrize("texto, esperado", [
    ("PRD001:2", {"id_producto": "PRD001", "cantidad": 2}),
    ("PRD001:10", {"id_producto": "PRD001", "cantidad": 10}),
    ("PRD001:0", {"id_producto": "PRD001", "cantidad": 0}),
])
def test_item_bien_formado(sin_ejecutar, texto, esperado):
    terminal.main(["q14", *VENTA, "--item", texto])
    assert sin_ejecutar[0].item == [esperado]


@pytest.mark.parametrize("texto", [
    "PRD001:1_0", "PRD001:+2", "PRD001:-1", "PRD001: 2", "PRD001:2 ", "PRD001:١", "PRD001:2.0",
    "PRD001:2:3", "PRD001:", "PRD001", ":2", "",
])
def test_item_mal_formado_es_un_error_de_uso(sin_ejecutar, capsys, texto):
    with pytest.raises(SystemExit) as salida:
        terminal.main(["q14", *VENTA, "--item", texto])
    assert salida.value.code == 2
    assert sin_ejecutar == []
    error = capsys.readouterr().err
    assert "argument --item: se espera PRODUCTO:CANTIDAD" in error
    assert repr(texto) in error


# Ayuda y opciones

def test_ayuda_describe_cada_comando_en_orden(monkeypatch, capsys):
    monkeypatch.setenv("COLUMNS", "200")   # sin cortes de línea en la descripción
    with pytest.raises(SystemExit):
        terminal.main(["--help"])
    ayuda = capsys.readouterr().out
    lineas = [linea.split(maxsplit=1) for linea in ayuda.splitlines() if linea.startswith("    ")]
    assert [nombre for nombre, _ in lineas] == list(terminal.COMANDOS)
    assert list(terminal.COMANDOS) == ["carga", *(f"q{n:02d}" for n in range(1, 16)), "demo"]
    assert all(texto == terminal.COMANDOS[nombre] for nombre, texto in lineas)


def test_ayuda_de_q14_explica_el_formato_del_item(capsys):
    with pytest.raises(SystemExit):
        terminal.main(["q14", "--help"])
    assert "--item PRODUCTO:CANTIDAD" in capsys.readouterr().out


@pytest.mark.parametrize("argumentos", [
    ["carga", "--solo-provisto"],
    ["carga", "--valid"],
    ["q07", "--lim", "3"],
    ["q14", "--client", "C003", "--farmaceutico", "F006", "--item", "PRD004:1", "--medio-pago", "Efectivo"],
    ["q13", "modificar", "C001", "--emai", "ana@gmail.com"],
])
def test_opcion_abreviada_no_se_acepta(sin_ejecutar, argumentos):
    with pytest.raises(SystemExit) as salida:
        terminal.main(argumentos)
    assert salida.value.code == 2
    assert sin_ejecutar == []
