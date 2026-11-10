import datetime
import json
import os
import pathlib
import subprocess
import sys

import conftest
import pytest
import redis
from bson import ObjectId
from pymongo import ASCENDING

import snapshots
from farmared import claves, config, conexiones, errores, fechas, formato, ids

RAIZ = pathlib.Path(__file__).resolve().parent.parent
BASE_DE_TRABAJO = "farmared"
COLECCION_PRUEBA = "prueba_base"
CONTADOR_PRUEBA = "prueba_base"
CONTADOR_AUSENTE = "prueba_base_ausente"
ID_LOTE_PRUEBA = "PRUEBA_BASE"

ENTORNO_DE_TRABAJO = {"MONGO_DB": BASE_DE_TRABAJO, "REDIS_DB": "0"}


def correr_con_entorno_de_trabajo(*argumentos, **extra):
    entorno = {**os.environ, **ENTORNO_DE_TRABAJO, **extra}
    return subprocess.run([sys.executable, *argumentos], env=entorno, cwd=RAIZ, capture_output=True, text=True,
                          timeout=60)


def estado_base_de_trabajo():
    base = conexiones.get_client()[BASE_DE_TRABAJO]
    return {nombre: base[nombre].count_documents({}) for nombre in base.list_collection_names()}


def redis_db(numero):
    return redis.Redis.from_url(config.redis_url(), db=numero, decode_responses=True)


@pytest.fixture
def coleccion(db):
    db.drop_collection(COLECCION_PRUEBA)
    yield db[COLECCION_PRUEBA]
    db.drop_collection(COLECCION_PRUEBA)


@pytest.fixture
def contador(db):
    existia = "contadores" in db.list_collection_names()
    borrar = {"_id": {"$in": [CONTADOR_PRUEBA, CONTADOR_AUSENTE]}}
    db.contadores.delete_many(borrar)

    def preparar(ultimo):
        db.contadores.replace_one({"_id": CONTADOR_PRUEBA}, {"ultimo": ultimo}, upsert=True)
        return CONTADOR_PRUEBA

    yield preparar
    db.contadores.delete_many(borrar)
    if not existia:
        db.drop_collection("contadores")


@pytest.fixture
def claves_prueba(r):
    lote = claves.lote(ID_LOTE_PRUEBA)
    stock = claves.stock("S_PRUEBA", "P_PRUEBA")

    def limpiar():
        r.delete(lote, stock)
        r.zrem(claves.UNIDADES, ID_LOTE_PRUEBA)
        r.srem(claves.LOTES, ID_LOTE_PRUEBA)

    limpiar()
    yield lote, stock
    limpiar()


def test_hoy_devuelve_la_fecha_fijada_por_conftest(hoy_fijo):
    assert hoy_fijo == datetime.date(2026, 11, 3)
    assert fechas.hoy() == hoy_fijo


def test_hoy_queda_fijada_sin_pedir_la_fixture():
    assert fechas.hoy() == datetime.date(2026, 11, 3)


def test_hoy_sin_monkeypatch_sigue_la_zona_del_sistema(monkeypatch):
    monkeypatch.undo()
    assert type(fechas.hoy()) is datetime.date
    guion = "from farmared import fechas; print(fechas.hoy())"
    # estas zonas distan 25 horas: la fecha local nunca coincide, a ninguna hora
    este, oeste = (correr_con_entorno_de_trabajo("-c", guion, TZ=zona).stdout.strip()
                   for zona in ("Pacific/Kiritimati", "Pacific/Pago_Pago"))
    assert este > oeste


def test_a_datetime_da_medianoche_sin_zona():
    resultado = fechas.a_datetime(datetime.date(2026, 2, 28))
    assert resultado == datetime.datetime(2026, 2, 28, 0, 0, 0)
    assert type(resultado) is datetime.datetime
    assert resultado.tzinfo is None


def test_a_datetime_vuelve_igual_desde_mongo(coleccion):
    guardada = fechas.a_datetime(datetime.date(2026, 12, 31))
    coleccion.insert_one({"_id": "f", "fecha": guardada})
    leida = coleccion.find_one({"_id": "f"})["fecha"]
    assert leida == guardada
    assert leida.tzinfo is None


@pytest.mark.parametrize("vacio", ["", None])
def test_desde_iso_vacio_da_none(vacio):
    assert fechas.desde_iso(vacio) is None


def test_desde_iso_con_fecha():
    resultado = fechas.desde_iso("2028-02-29")
    assert resultado == datetime.date(2028, 2, 29)
    assert type(resultado) is datetime.date


def test_a_iso_con_none():
    assert fechas.a_iso(None) is None


@pytest.mark.parametrize("valor, esperado", [
    (datetime.date(2026, 1, 5), "2026-01-05"),
    (datetime.date(2026, 12, 31), "2026-12-31"),
    (datetime.datetime(2026, 11, 3), "2026-11-03"),
    (datetime.datetime(2027, 1, 1, 23, 59, 59), "2027-01-01"),
])
def test_a_iso_con_date_y_datetime(valor, esperado):
    assert fechas.a_iso(valor) == esperado


@pytest.mark.parametrize("fecha, esperado", [
    (datetime.date(2026, 11, 3), 20261103),
    (datetime.date(2026, 12, 31), 20261231),
    (datetime.date(2027, 1, 1), 20270101),
    (datetime.date(2026, 2, 28), 20260228),
    (datetime.date(2028, 2, 29), 20280229),
    (datetime.date(2026, 3, 1), 20260301),
])
def test_a_entero_en_bordes_de_mes_y_de_anio(fecha, esperado):
    assert fechas.a_entero(fecha) == esperado
    assert type(fechas.a_entero(fecha)) is int


@pytest.mark.parametrize("anterior, siguiente", [
    (datetime.date(2026, 12, 31), datetime.date(2027, 1, 1)),
    (datetime.date(2026, 2, 28), datetime.date(2026, 3, 1)),
    (datetime.date(2028, 2, 28), datetime.date(2028, 2, 29)),
    (datetime.date(2028, 2, 29), datetime.date(2028, 3, 1)),
    (datetime.date(2026, 1, 31), datetime.date(2026, 2, 1)),
])
def test_a_entero_conserva_el_orden_cronologico(anterior, siguiente):
    assert anterior + datetime.timedelta(days=1) == siguiente
    assert fechas.a_entero(anterior) < fechas.a_entero(siguiente)


def test_a_json_anidado_con_listas_quita_id_y_formatea_fechas():
    entrada = {
        "_id": "V001",
        "fecha": datetime.datetime(2026, 11, 3),
        "total": 1500,
        "activo": True,
        "receta": None,
        "cliente": {"_id": "C001", "alta": datetime.date(2026, 1, 5), "nombre": "Ana"},
        "items": [
            {"_id": "D001", "cantidad": 2, "lote": {"_id": "L001", "vencimiento": datetime.datetime(2027, 1, 1)}},
            {"_id": "D002", "cantidad": 1, "fechas": [datetime.date(2026, 12, 31), [datetime.date(2028, 2, 29)]]},
        ],
    }
    esperado = {
        "fecha": "2026-11-03",
        "total": 1500,
        "activo": True,
        "receta": None,
        "cliente": {"alta": "2026-01-05", "nombre": "Ana"},
        "items": [
            {"cantidad": 2, "lote": {"vencimiento": "2027-01-01"}},
            {"cantidad": 1, "fechas": ["2026-12-31", ["2028-02-29"]]},
        ],
    }
    resultado = formato.a_json(entrada)
    assert resultado == esperado
    assert json.loads(json.dumps(resultado)) == esperado


def test_a_json_con_lista_en_la_raiz():
    assert formato.a_json([{"_id": 1, "a": 2}, datetime.date(2026, 1, 1), "x", 3]) == [{"a": 2}, "2026-01-01", "x", 3]


def test_a_json_solo_quita_la_clave_id_exacta():
    entrada = {"_id": "V001", "id_cliente": "C001", "_version": 2,
               "items": [{"id_detalle": "D001", "id_producto": "PRD003"}]}
    assert formato.a_json(entrada) == {"id_cliente": "C001", "_version": 2,
                                       "items": [{"id_detalle": "D001", "id_producto": "PRD003"}]}


def test_a_json_sobre_documento_real_pasa_por_dumps(coleccion):
    coleccion.insert_one({"fecha": fechas.a_datetime(datetime.date(2026, 11, 3)),
                          "items": [{"_id": ObjectId(), "cantidad": 1}]})
    documento = coleccion.find_one()
    with pytest.raises(TypeError):
        json.dumps(documento)
    assert json.dumps(formato.a_json(documento), sort_keys=True) == \
        '{"fecha": "2026-11-03", "items": [{"cantidad": 1}]}'


def test_claves_con_los_nombres_del_modelo():
    assert claves.lote("L005") == "lote:L005"
    assert claves.stock("S001", "PRD003") == "stock:S001:PRD003"
    assert claves.UNIDADES == "lotes:unidades"
    assert claves.LOTES == "lotes"
    assert claves.PATRONES == ("lote:*", "stock:*")


def test_jerarquia_de_errores():
    assert issubclass(errores.FarmaRedError, Exception)
    assert issubclass(errores.ValidacionError, errores.FarmaRedError)
    assert issubclass(errores.NoEncontrado, errores.ValidacionError)
    assert issubclass(errores.StockInsuficiente, errores.FarmaRedError)
    assert not issubclass(errores.StockInsuficiente, errores.ValidacionError)


@pytest.mark.parametrize("clase", [errores.FarmaRedError, errores.ValidacionError, errores.NoEncontrado])
def test_error_trae_codigo_y_mensaje(clase):
    error = clase("DATO_INVALIDO", "dni vacío")
    assert error.codigo == "DATO_INVALIDO"
    assert error.mensaje == "dni vacío"
    assert str(error) == "dni vacío"


def test_no_encontrado_se_captura_como_validacion():
    with pytest.raises(errores.ValidacionError) as capturado:
        raise errores.NoEncontrado("CLIENTE_INEXISTENTE", "no existe C999")
    assert capturado.value.codigo == "CLIENTE_INEXISTENTE"


def test_stock_insuficiente_trae_codigo_y_datos():
    error = errores.StockInsuficiente("PRD003", 10, 4)
    assert isinstance(error, errores.FarmaRedError)
    assert error.codigo == "STOCK_INSUFICIENTE"
    assert (error.id_producto, error.requerido, error.disponible) == ("PRD003", 10, 4)
    assert all(dato in error.mensaje for dato in ("PRD003", "10", "4"))


def test_siguiente_id_da_consecutivos(contador):
    nombre = contador(16)
    assert ids.siguiente_id(nombre, "V") == "V017"
    assert ids.siguiente_id(nombre, "V") == "V018"


def test_siguiente_id_persiste_el_contador(contador, db):
    nombre = contador(8)
    ids.siguiente_id(nombre, "C")
    assert db.contadores.find_one({"_id": nombre}) == {"_id": nombre, "ultimo": 9}


@pytest.mark.parametrize("ultimo, prefijo, esperado", [
    (0, "C", "C001"),
    (8, "C", "C009"),
    (16, "V", "V017"),
    (22, "D", "D023"),
    (998, "C", "C999"),
    (999, "C", "C1000"),
    (1233, "V", "V1234"),
])
def test_siguiente_id_tiene_al_menos_tres_digitos(contador, ultimo, prefijo, esperado):
    assert ids.siguiente_id(contador(ultimo), prefijo) == esperado


def test_siguiente_id_en_transaccion_abortada_no_avanza(contador, db):
    nombre = contador(5)
    with conexiones.get_client().start_session() as sesion:
        sesion.start_transaction()
        assert ids.siguiente_id(nombre, "C", session=sesion) == "C006"
        assert ids.siguiente_id(nombre, "C", session=sesion) == "C007"
        assert db.contadores.find_one({"_id": nombre})["ultimo"] == 5
        sesion.abort_transaction()
    assert db.contadores.find_one({"_id": nombre})["ultimo"] == 5
    assert ids.siguiente_id(nombre, "C") == "C006"


def test_siguiente_id_en_transaccion_confirmada_avanza(contador, db):
    nombre = contador(5)
    with conexiones.get_client().start_session() as sesion:
        sesion.start_transaction()
        assert ids.siguiente_id(nombre, "C", session=sesion) == "C006"
        sesion.commit_transaction()
    assert db.contadores.find_one({"_id": nombre})["ultimo"] == 6


def test_siguiente_id_sin_contador_lanza_y_no_lo_crea(contador, db):
    with pytest.raises(errores.FarmaRedError, match=CONTADOR_AUSENTE) as capturado:
        ids.siguiente_id(CONTADOR_AUSENTE, "C")
    assert capturado.value.codigo == "BASE_SIN_CARGA"
    assert db.contadores.count_documents({"_id": CONTADOR_AUSENTE}) == 0


def test_escritura_en_mongo_no_toca_la_base_de_trabajo(coleccion, db):
    antes = estado_base_de_trabajo()
    coleccion.insert_one({"_id": "escritura"})
    assert config.mongo_db() == "farmared_test"
    assert db.name == "farmared_test"
    assert conexiones.get_client()["farmared_test"][COLECCION_PRUEBA].count_documents({"_id": "escritura"}) == 1
    assert estado_base_de_trabajo() == antes


def test_escritura_en_redis_va_a_la_db_1(r, claves_prueba):
    lote, _ = claves_prueba
    base_de_trabajo = redis_db(0)
    antes = (base_de_trabajo.dbsize(), base_de_trabajo.hgetall(lote))
    assert config.redis_db() == 1
    assert int(r.client_info()["db"]) == 1
    r.hset(lote, "unidades", 1)
    assert redis_db(1).hget(lote, "unidades") == "1"
    assert (base_de_trabajo.dbsize(), base_de_trabajo.hgetall(lote)) == antes


# conftest ya sobrescribió os.environ en este proceso: solo un proceso nuevo arranca con el entorno de trabajo.
def test_conftest_fuerza_las_bases_de_prueba_con_el_entorno_de_trabajo(coleccion):
    guion = (
        "import os\n"
        "assert os.environ['MONGO_DB'] == 'farmared' and os.environ['REDIS_DB'] == '0'\n"
        "import conftest\n"
        "from farmared import config, conexiones\n"
        f"conexiones.get_db()['{COLECCION_PRUEBA}'].insert_one({{'_id': 'subproceso'}})\n"
        "print(config.mongo_db(), conexiones.get_db().name)\n"
        "print(config.redis_db(), conexiones.get_redis().client_info()['db'])\n"
    )
    antes = estado_base_de_trabajo()
    resultado = correr_con_entorno_de_trabajo("-c", guion, PYTHONPATH=f"{RAIZ}{os.pathsep}{RAIZ / 'tests'}")
    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.split() == ["farmared_test", "farmared_test", "1", "1"]
    assert coleccion.count_documents({"_id": "subproceso"}) == 1
    assert estado_base_de_trabajo() == antes


@pytest.mark.parametrize("base", ["farmared", "produccion", "farmared_test_copia", "farmaredtest"])
def test_inicio_de_sesion_aborta_si_la_base_no_termina_en_test(monkeypatch, base):
    monkeypatch.setenv("MONGO_DB", base)
    with pytest.raises(pytest.exit.Exception) as capturado:
        conftest.pytest_sessionstart(None)
    assert capturado.value.returncode == 2


def test_inicio_de_sesion_sigue_con_base_de_prueba():
    assert conftest.pytest_sessionstart(None) is None


def test_corrida_real_de_pytest_se_corta_con_base_de_trabajo(tmp_path):
    (tmp_path / "forzar_base.py").write_text(
        "import os\n"
        "import pytest\n"
        "@pytest.hookimpl(tryfirst=True)\n"
        "def pytest_sessionstart(session):\n"
        "    os.environ['MONGO_DB'] = 'farmared'\n"
    )
    antes = estado_base_de_trabajo()
    resultado = correr_con_entorno_de_trabajo(
        "-m", "pytest", "-q", "--collect-only", "-p", "forzar_base", "-p", "no:cacheprovider", "tests/test_base.py",
        PYTHONPATH=str(tmp_path))
    assert resultado.returncode == 2, resultado.stdout + resultado.stderr
    assert "_test" in resultado.stdout + resultado.stderr
    assert estado_base_de_trabajo() == antes


def test_redis_snap_igual_sin_cambios(r, claves_prueba):
    lote, stock = claves_prueba
    r.hset(lote, mapping={"unidades": 5, "vencimiento": "2027-01-01"})
    r.zadd(stock, {ID_LOTE_PRUEBA: 20270101})
    assert snapshots.redis_snap() == snapshots.redis_snap()


def test_redis_snap_refleja_el_contenido(r, claves_prueba):
    lote, stock = claves_prueba
    r.hset(lote, "unidades", 5)
    r.zadd(stock, {ID_LOTE_PRUEBA: 20270101})
    r.zadd(claves.UNIDADES, {ID_LOTE_PRUEBA: 5})
    r.sadd(claves.LOTES, ID_LOTE_PRUEBA)
    estado = snapshots.redis_snap()
    assert estado[lote] == {"unidades": "5"}
    assert estado[stock] == [(ID_LOTE_PRUEBA, 20270101.0)]
    assert (ID_LOTE_PRUEBA, 5.0) in estado[claves.UNIDADES]
    assert ID_LOTE_PRUEBA in estado[claves.LOTES]


@pytest.mark.parametrize("cambio", [
    lambda r, lote, stock: r.hset(lote, "unidades", 4),
    lambda r, lote, stock: r.zadd(stock, {ID_LOTE_PRUEBA: 20270102}),
    lambda r, lote, stock: r.zadd(claves.UNIDADES, {ID_LOTE_PRUEBA: 4}),
    lambda r, lote, stock: r.srem(claves.LOTES, ID_LOTE_PRUEBA),
    lambda r, lote, stock: r.delete(lote),
], ids=["hash", "zset_stock", "zset_unidades", "set", "clave_borrada"])
def test_redis_snap_detecta_un_cambio(r, claves_prueba, cambio):
    lote, stock = claves_prueba
    r.hset(lote, "unidades", 5)
    r.zadd(stock, {ID_LOTE_PRUEBA: 20270101})
    r.zadd(claves.UNIDADES, {ID_LOTE_PRUEBA: 5})
    r.sadd(claves.LOTES, ID_LOTE_PRUEBA)
    antes = snapshots.redis_snap()
    cambio(r, lote, stock)
    assert snapshots.redis_snap() != antes


def test_mongo_snap_igual_sin_cambios(coleccion):
    coleccion.insert_one({"_id": "a", "n": 1})
    assert snapshots.mongo_snap() == snapshots.mongo_snap()


def test_mongo_snap_detecta_cambio_de_documento(coleccion):
    coleccion.insert_one({"_id": "a", "n": 1})
    antes = snapshots.mongo_snap()
    coleccion.update_one({"_id": "a"}, {"$set": {"n": 2}})
    assert snapshots.mongo_snap() != antes
    coleccion.update_one({"_id": "a"}, {"$set": {"n": 1}})
    assert snapshots.mongo_snap() == antes


def test_mongo_snap_detecta_documento_nuevo(coleccion):
    coleccion.insert_one({"_id": "a"})
    antes = snapshots.mongo_snap()
    coleccion.insert_one({"_id": "b"})
    assert snapshots.mongo_snap() != antes


def test_mongo_snap_ignora_vistas_y_colecciones_de_sistema(coleccion, db):
    vista = COLECCION_PRUEBA + "_vista"
    db.drop_collection(vista)
    coleccion.insert_one({"_id": "a"})
    habia_vistas = db["system.views"].count_documents({}) > 0
    antes = snapshots.mongo_snap()
    db.create_collection(vista, viewOn=COLECCION_PRUEBA, pipeline=[])
    try:
        assert snapshots.mongo_snap() == antes
    finally:
        db.drop_collection(vista)
        if not habia_vistas:
            db.drop_collection("system.views")


def test_mongo_snap_detecta_cambio_de_indice(coleccion):
    coleccion.insert_one({"_id": "a", "n": 1})
    antes = snapshots.mongo_snap()
    coleccion.create_index([("n", ASCENDING)], name="n_1", unique=True)
    despues = snapshots.mongo_snap()
    assert despues != antes
    assert ("n_1", True) in despues[COLECCION_PRUEBA + "#indices"]
    coleccion.drop_index("n_1")
    assert snapshots.mongo_snap() == antes
