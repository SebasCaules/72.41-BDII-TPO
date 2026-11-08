import json
import pathlib
import subprocess
import sys
import threading

import pymongo
import pytest
from pymongo.client_session import ClientSession
from pymongo.errors import OperationFailure, PyMongoError

import snapshots
from farmared import config
from farmared.consultas import q13_abm_clientes as q13
from farmared.errores import FarmaRedError, NoEncontrado, ValidacionError

RAIZ = pathlib.Path(__file__).resolve().parent.parent
DATOS = {"nombre": "Paula", "apellido": "Sosa", "dni": "99100200", "email": "paula.sosa@gmail.com",
         "telefono": "1144556677", "ciudad": "La Plata", "provincia": "Buenos Aires", "obra_social": "OSDE",
         "nro_afiliado": "OS-990001"}
# DNI de C012, cliente inactivo de datos/adicionales/clientes.csv
DNI_C012 = "20456789"


def correr_cli(*argumentos):
    return subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                          text=True, timeout=60)


def estado():
    return snapshots.mongo_snap(), snapshots.redis_snap()


def contador_clientes(db):
    return db.contadores.find_one({"_id": "clientes"})["ultimo"]


def rechaza(codigo, funcion, *argumentos):
    """Comprueba el código del rechazo y que Mongo y Redis queden exactamente como estaban."""
    antes = estado()
    with pytest.raises(FarmaRedError) as capturado:
        funcion(*argumentos)
    assert capturado.value.codigo == codigo
    assert estado() == antes
    return capturado.value


# Alta

def test_alta_valida_con_los_provistos_crea_c009(datos_provistos, db):
    total = db.clientes.count_documents({})
    cliente = q13.alta_cliente(dict(DATOS))
    esperado = {"id_cliente": "C009", "nombre": "Paula", "apellido": "Sosa", "dni": "99100200",
                "email": "paula.sosa@gmail.com", "telefono": "1144556677", "ciudad": "La Plata",
                "provincia": "Buenos Aires", "obra_social": "OSDE", "nro_afiliado": "OS-990001", "activo": True}
    assert cliente == esperado
    assert list(cliente) == list(esperado)
    guardado = db.clientes.find_one({"_id": "C009"})
    assert {"id_cliente": guardado.pop("_id"), **guardado} == esperado
    assert db.clientes.count_documents({}) == total + 1
    assert contador_clientes(db) == 9
    json.dumps(cliente)


def test_altas_sucesivas_numeran_sin_huecos_aunque_haya_rechazos(datos_provistos, db):
    assert q13.alta_cliente(dict(DATOS))["id_cliente"] == "C009"
    rechaza("DNI_DUPLICADO", q13.alta_cliente, dict(DATOS))
    rechaza("DATO_INVALIDO", q13.alta_cliente, {**DATOS, "dni": "99100201", "email": ""})
    assert q13.alta_cliente({**DATOS, "dni": "99100201"})["id_cliente"] == "C010"
    assert contador_clientes(db) == 10


def test_alta_sin_cobertura_deja_nro_afiliado_nulo_aunque_venga_informado(datos_provistos, db):
    cliente = q13.alta_cliente({**DATOS, "obra_social": "Sin cobertura"})
    assert cliente["nro_afiliado"] is None
    assert db.clientes.find_one({"_id": cliente["id_cliente"]})["nro_afiliado"] is None
    sin_numero = {k: v for k, v in DATOS.items() if k != "nro_afiliado"}
    cliente = q13.alta_cliente({**sin_numero, "dni": "99100201", "obra_social": "Sin cobertura"})
    assert cliente["nro_afiliado"] is None


def test_alta_quita_espacios_de_los_extremos(datos_provistos):
    cliente = q13.alta_cliente({**DATOS, "nombre": "  Paula ", "dni": " 99100200 "})
    assert (cliente["nombre"], cliente["dni"]) == ("Paula", "99100200")


@pytest.mark.parametrize("dni", ["31245678", "25678901", " 31245678 "],
                         ids=["activo", "inactivo", "con-espacios"])
def test_alta_con_dni_repetido_se_rechaza_sin_escribir(datos_provistos, dni):
    # 31245678 es C001 (activo) y 25678901 es C008 (inactivo)
    rechaza("DNI_DUPLICADO", q13.alta_cliente, {**DATOS, "dni": dni})


@pytest.mark.parametrize("dni", ["31245678", "25678901"], ids=["activo", "inactivo"])
def test_el_chequeo_previo_frena_el_dni_repetido_sin_el_indice(datos_provistos, db, dni):
    # Sin el índice único, el rechazo solo puede venir del chequeo previo, que mira activos e inactivos.
    db.clientes.drop_index("dni_1")
    rechaza("DNI_DUPLICADO", q13.alta_cliente, {**DATOS, "dni": dni})


SIN_NRO = {k: v for k, v in DATOS.items() if k != "nro_afiliado"}


@pytest.mark.parametrize("datos", [
    {k: v for k, v in DATOS.items() if k != "email"},
    {**DATOS, "telefono": ""},
    {**DATOS, "ciudad": "   "},
    {**DATOS, "apellido": None},
    {**DATOS, "dni": 99100200},
    {**DATOS, "activo": False},
    {**DATOS, "id_cliente": "C900"},
    SIN_NRO,
    {**DATOS, "nro_afiliado": ""},
    {},
    ["Paula", "Sosa"],
], ids=["falta-email", "telefono-vacio", "ciudad-en-blanco", "apellido-nulo", "dni-numerico", "campo-activo",
        "campo-id", "cobertura-sin-afiliado", "afiliado-vacio", "vacio", "no-es-diccionario"])
def test_alta_con_datos_invalidos_se_rechaza_sin_escribir(datos_provistos, datos):
    rechaza("DATO_INVALIDO", q13.alta_cliente, datos)


@pytest.mark.parametrize("obra_social", ["Medifé", "osde", ""], ids=["fuera-del-dominio", "minusculas", "vacia"])
def test_alta_con_obra_social_invalida(datos_provistos, obra_social):
    codigo = "DATO_INVALIDO" if not obra_social else "OBRA_SOCIAL_INVALIDA"
    rechaza(codigo, q13.alta_cliente, {**DATOS, "obra_social": obra_social})


@pytest.mark.parametrize("nro_afiliado", ["", "   ", None, 123], ids=["vacio", "en-blanco", "nulo", "no-es-texto"])
def test_alta_sin_cobertura_con_afiliado_invalido_se_rechaza(datos_provistos, nro_afiliado):
    # La misma regla que en la modificación: una clave informada y vacía es un dato inválido.
    rechaza("DATO_INVALIDO", q13.alta_cliente, {**DATOS, "obra_social": "Sin cobertura", "nro_afiliado": nro_afiliado})


def test_alta_frena_en_el_indice_unico_si_el_chequeo_previo_no_ve_el_dni(datos_provistos, db, monkeypatch):
    # Simula otra alta con el mismo DNI confirmada entre el chequeo y la inserción.
    monkeypatch.setattr(q13, "_dni_registrado", lambda *argumentos: False)
    error = rechaza("DNI_DUPLICADO", q13.alta_cliente, {**DATOS, "dni": "31245678"})
    assert isinstance(error, ValidacionError)
    assert contador_clientes(db) == 8


def correr_en_paralelo(funciones):
    barrera = threading.Barrier(len(funciones))
    resultados = [None] * len(funciones)

    def correr(i, funcion):
        barrera.wait()
        try:
            resultados[i] = funcion()
        except FarmaRedError as e:
            resultados[i] = e

    hilos = [threading.Thread(target=correr, args=(i, f)) for i, f in enumerate(funciones)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)
    return resultados


@pytest.mark.parametrize("vuelta", range(3))
def test_dos_altas_simultaneas_con_el_mismo_dni_crean_un_solo_cliente(datos_provistos, db, vuelta):
    resultados = correr_en_paralelo([lambda: q13.alta_cliente(dict(DATOS))] * 2)
    exitos = [r for r in resultados if isinstance(r, dict)]
    rechazos = [r for r in resultados if isinstance(r, FarmaRedError)]
    assert len(exitos) == 1 and len(rechazos) == 1, resultados
    assert exitos[0]["id_cliente"] == "C009"
    assert rechazos[0].codigo == "DNI_DUPLICADO"
    assert db.clientes.count_documents({"dni": DATOS["dni"]}) == 1
    assert contador_clientes(db) == 9


def test_altas_simultaneas_con_dni_distinto_numeran_sin_huecos(datos_provistos, db):
    altas = [lambda n=n: q13.alta_cliente({**DATOS, "dni": f"9920000{n}"}) for n in range(5)]
    resultados = correr_en_paralelo(altas)
    assert sorted(r["id_cliente"] for r in resultados) == ["C009", "C010", "C011", "C012", "C013"]
    assert contador_clientes(db) == 13


def test_un_commit_fallido_no_deja_el_alta(datos_provistos, db, monkeypatch):
    # El contador y el insert van en la misma transacción: si no confirma, no queda ni el cliente ni el id usado.
    antes = estado()

    def falla(self):
        raise OperationFailure("fallo al confirmar")

    monkeypatch.setattr(ClientSession, "commit_transaction", falla)
    with pytest.raises(PyMongoError):
        q13.alta_cliente(dict(DATOS))
    monkeypatch.undo()
    assert estado() == antes
    assert contador_clientes(db) == 8
    assert q13.alta_cliente({**DATOS, "dni": "99100201"})["id_cliente"] == "C009"


# Modificación

def test_modificar_contacto_y_domicilio(datos_provistos, db):
    cambios = {"email": "lucia.fernandez@gmail.com", "telefono": "1145000000", "ciudad": "Quilmes"}
    cliente = q13.modificar_cliente("C001", cambios)
    assert cliente["id_cliente"] == "C001"
    assert {k: cliente[k] for k in cambios} == cambios
    assert (cliente["dni"], cliente["obra_social"], cliente["nro_afiliado"]) == ("31245678", "OSDE", "OS-310045")
    guardado = db.clientes.find_one({"_id": "C001"})
    assert {"id_cliente": guardado.pop("_id"), **guardado} == cliente


def test_modificar_solo_toca_las_claves_pasadas(datos_provistos, db):
    antes = db.clientes.find_one({"_id": "C002"})
    q13.modificar_cliente("C002", {"provincia": "Córdoba"})
    despues = db.clientes.find_one({"_id": "C002"})
    assert {k for k in antes if antes[k] != despues[k]} == {"provincia"}


def test_pasar_a_sin_cobertura_deja_nro_afiliado_nulo(datos_provistos, db):
    cliente = q13.modificar_cliente("C001", {"obra_social": "Sin cobertura"})
    assert (cliente["obra_social"], cliente["nro_afiliado"]) == ("Sin cobertura", None)
    assert db.clientes.find_one({"_id": "C001"})["nro_afiliado"] is None


def test_pasar_a_sin_cobertura_ignora_el_numero_informado(datos_provistos):
    cliente = q13.modificar_cliente("C001", {"obra_social": "Sin cobertura", "nro_afiliado": "OS-1"})
    assert cliente["nro_afiliado"] is None


def test_pasar_a_otra_obra_social_con_su_numero(datos_provistos):
    # C005 no tiene cobertura
    cliente = q13.modificar_cliente("C005", {"obra_social": "Galeno", "nro_afiliado": "GA-990001"})
    assert (cliente["obra_social"], cliente["nro_afiliado"]) == ("Galeno", "GA-990001")


def test_repetir_la_misma_obra_social_no_exige_numero(datos_provistos):
    cliente = q13.modificar_cliente("C001", {"obra_social": "OSDE", "email": "lu@gmail.com"})
    assert (cliente["obra_social"], cliente["nro_afiliado"]) == ("OSDE", "OS-310045")


def test_cambiar_solo_el_numero_de_afiliado(datos_provistos):
    assert q13.modificar_cliente("C001", {"nro_afiliado": "OS-999999"})["nro_afiliado"] == "OS-999999"


@pytest.mark.parametrize("cliente,cambios", [("C001", {"obra_social": "PAMI"}),
                                             ("C005", {"obra_social": "IOMA", "email": "sofi@gmail.com"})],
                         ids=["con-cobertura", "sin-cobertura"])
def test_pasar_a_otra_obra_social_sin_numero(datos_provistos, cliente, cambios):
    rechaza("AFILIADO_REQUERIDO", q13.modificar_cliente, cliente, cambios)


@pytest.mark.parametrize("campo,valor", [("dni", "99999999"), ("nombre", "Lucía María"), ("activo", False),
                                         ("_id", "C900"), ("id_cliente", "C900")])
def test_campo_no_modificable(datos_provistos, campo, valor):
    rechaza("CAMPO_NO_MODIFICABLE", q13.modificar_cliente, "C001", {"email": "lu@gmail.com", campo: valor})


def test_modificar_a_una_obra_social_fuera_del_dominio(datos_provistos):
    rechaza("OBRA_SOCIAL_INVALIDA", q13.modificar_cliente, "C001", {"obra_social": "Medifé", "nro_afiliado": "M-1"})


@pytest.mark.parametrize("cambios", [{}, {"email": ""}, {"telefono": "  "}, {"ciudad": None},
                                     {"obra_social": "Galeno", "nro_afiliado": ""}, None],
                         ids=["vacio", "email-vacio", "telefono-en-blanco", "ciudad-nula", "afiliado-vacio", "nulo"])
def test_modificar_con_datos_invalidos(datos_provistos, cambios):
    rechaza("DATO_INVALIDO", q13.modificar_cliente, "C001", cambios)


def test_modificar_un_cliente_inactivo(datos_provistos):
    rechaza("CLIENTE_INACTIVO", q13.modificar_cliente, "C008", {"email": "hugo@gmail.com"})


def test_modificar_un_cliente_inexistente(datos_provistos):
    error = rechaza("CLIENTE_INEXISTENTE", q13.modificar_cliente, "C999", {"email": "x@gmail.com"})
    assert isinstance(error, NoEncontrado)


@pytest.mark.parametrize("nro_afiliado", ["", None], ids=["vacio", "nulo"])
def test_pasar_a_sin_cobertura_con_afiliado_invalido_se_rechaza(datos_provistos, nro_afiliado):
    rechaza("DATO_INVALIDO", q13.modificar_cliente, "C001", {"obra_social": "Sin cobertura",
                                                             "nro_afiliado": nro_afiliado})


def test_una_baja_que_confirma_en_el_medio_frena_la_modificacion(datos_provistos, db, monkeypatch):
    # Otro proceso da de baja al cliente entre la lectura y la escritura de la modificación: la escritura
    # va en la transacción, choca, se reintenta y la nueva lectura ya lo ve inactivo.
    otro = pymongo.MongoClient(config.mongo_uri())
    original = q13._buscar_activo
    bajas = []

    def leer_y_dar_de_baja(db_, s, id_cliente):
        cliente = original(db_, s, id_cliente)
        if not bajas:
            bajas.append(id_cliente)
            otro[config.mongo_db()].clientes.update_one({"_id": id_cliente}, {"$set": {"activo": False}})
        return cliente

    monkeypatch.setattr(q13, "_buscar_activo", leer_y_dar_de_baja)
    try:
        with pytest.raises(ValidacionError) as capturado:
            q13.modificar_cliente("C001", {"email": "carrera@gmail.com"})
    finally:
        otro.close()
    assert capturado.value.codigo == "CLIENTE_INACTIVO"
    guardado = db.clientes.find_one({"_id": "C001"})
    assert (guardado["email"], guardado["activo"]) == ("lucia.f@gmail.com", False)


# Baja

def test_baja_es_logica(datos_provistos, db):
    total = db.clientes.count_documents({})
    cliente = q13.baja_cliente("C001")
    assert cliente["id_cliente"] == "C001" and cliente["activo"] is False
    guardado = db.clientes.find_one({"_id": "C001"})
    assert guardado is not None and guardado["activo"] is False
    assert {"id_cliente": guardado.pop("_id"), **guardado} == cliente
    assert db.clientes.count_documents({}) == total


def test_baja_de_un_inactivo_no_cambia_nada(datos_provistos, db):
    antes = estado()
    cliente = q13.baja_cliente("C008")
    assert cliente["activo"] is False and cliente["id_cliente"] == "C008"
    assert estado() == antes


def test_despues_de_la_baja_no_se_modifica_y_su_dni_sigue_ocupado(datos_provistos):
    q13.baja_cliente("C001")
    rechaza("CLIENTE_INACTIVO", q13.modificar_cliente, "C001", {"email": "lu@gmail.com"})
    rechaza("DNI_DUPLICADO", q13.alta_cliente, {**DATOS, "dni": "31245678"})


def test_baja_de_un_cliente_inexistente(datos_provistos):
    error = rechaza("CLIENTE_INEXISTENTE", q13.baja_cliente, "C999")
    assert isinstance(error, NoEncontrado)


# Datos completos (casos documentados en datos/adicionales/CASOS.md)

def test_datos_completos_cliente_inactivo_no_se_modifica(datos_completos):
    rechaza("CLIENTE_INACTIVO", q13.modificar_cliente, "C012", {"email": "raul.d@gmail.com"})


def test_datos_completos_alta_con_el_dni_de_un_inactivo(datos_completos):
    datos = {"nombre": "Raúl", "apellido": "Domínguez", "dni": DNI_C012, "email": "r.dominguez@gmail.com",
             "telefono": "1157456704", "ciudad": "Buenos Aires", "provincia": "Buenos Aires", "obra_social": "IOMA",
             "nro_afiliado": "IO-338841"}
    rechaza("DNI_DUPLICADO", q13.alta_cliente, datos)


def test_datos_completos_el_alta_sigue_la_numeracion(datos_completos, db):
    assert contador_clientes(db) == 22
    assert q13.alta_cliente(dict(DATOS))["id_cliente"] == "C023"


# Línea de comandos

ALTA_CLI = ["q13", "alta", "--nombre", "Paula", "--apellido", "Sosa", "--dni", "99100200", "--email",
            "paula.sosa@gmail.com", "--telefono", "1144556677", "--ciudad", "La Plata", "--provincia",
            "Buenos Aires", "--obra-social", "OSDE", "--nro-afiliado", "OS-990001"]


def test_linea_de_comandos_alta(datos_completos, db):
    salida = correr_cli(*ALTA_CLI)
    assert salida.returncode == 0, salida.stderr
    cliente = json.loads(salida.stdout)
    assert cliente["id_cliente"] == "C023" and cliente["dni"] == "99100200" and cliente["activo"] is True
    assert db.clientes.find_one({"_id": "C023"})["nro_afiliado"] == "OS-990001"


def test_linea_de_comandos_alta_con_el_dni_de_un_inactivo(datos_completos):
    antes = estado()
    salida = correr_cli("q13", "alta", "--nombre", "Raúl", "--apellido", "Domínguez", "--dni", DNI_C012,
                        "--email", "r.dominguez@gmail.com", "--telefono", "1157456704", "--ciudad", "Buenos Aires",
                        "--provincia", "Buenos Aires", "--obra-social", "IOMA", "--nro-afiliado", "IO-338841")
    assert salida.returncode == 1
    assert salida.stderr.startswith("Error [DNI_DUPLICADO]:")
    assert salida.stdout == ""
    assert estado() == antes


def test_linea_de_comandos_alta_con_cobertura_sin_numero(datos_completos):
    antes = estado()
    salida = correr_cli(*ALTA_CLI[:-2])
    assert salida.returncode == 1
    assert salida.stderr.startswith("Error [DATO_INVALIDO]:")
    assert estado() == antes


@pytest.mark.parametrize("argumentos", [
    ALTA_CLI[:-4] + ["--obra-social", "Sin cobertura", "--nro-afiliado", ""],
    ["q13", "modificar", "C015", "--obra-social", "Sin cobertura", "--nro-afiliado", ""],
], ids=["alta", "modificar"])
def test_linea_de_comandos_sin_cobertura_con_afiliado_vacio(datos_completos, argumentos):
    antes = estado()
    salida = correr_cli(*argumentos)
    assert salida.returncode == 1
    assert salida.stderr.startswith("Error [DATO_INVALIDO]:")
    assert estado() == antes


def test_linea_de_comandos_modificar(datos_completos, db):
    salida = correr_cli("q13", "modificar", "C015", "--email", "javier.l@gmail.com", "--obra-social",
                        "Sin cobertura")
    assert salida.returncode == 0, salida.stderr
    cliente = json.loads(salida.stdout)
    assert (cliente["id_cliente"], cliente["email"], cliente["obra_social"], cliente["nro_afiliado"]) == (
        "C015", "javier.l@gmail.com", "Sin cobertura", None)
    assert db.clientes.find_one({"_id": "C015"})["telefono"] == "1158789007"


def test_linea_de_comandos_modificar_un_inactivo(datos_completos):
    antes = estado()
    salida = correr_cli("q13", "modificar", "C012", "--email", "raul.d@gmail.com")
    assert salida.returncode == 1
    assert salida.stderr.startswith("Error [CLIENTE_INACTIVO]:")
    assert salida.stdout == ""
    assert estado() == antes


def test_linea_de_comandos_modificar_sin_opciones(datos_completos):
    salida = correr_cli("q13", "modificar", "C015")
    assert salida.returncode == 1
    assert salida.stderr.startswith("Error [DATO_INVALIDO]:")


def test_linea_de_comandos_baja(datos_completos, db):
    salida = correr_cli("q13", "baja", "C015")
    assert salida.returncode == 0, salida.stderr
    assert json.loads(salida.stdout)["activo"] is False
    assert db.clientes.find_one({"_id": "C015"})["activo"] is False


def test_linea_de_comandos_baja_de_un_inexistente(datos_completos):
    antes = estado()
    salida = correr_cli("q13", "baja", "C999")
    assert salida.returncode == 1
    assert salida.stderr.startswith("Error [CLIENTE_INEXISTENTE]:")
    assert salida.stdout == ""
    assert estado() == antes
