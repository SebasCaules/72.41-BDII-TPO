"""q15 llamada sola, sin la transacción de q14: fallos alrededor de la marca, reintentos y llamadas simultáneas."""
import subprocess
import sys
import threading

import pytest
import redis
from pymongo.collection import Collection
from pymongo.errors import AutoReconnect, OperationFailure

import snapshots
from farmared import claves, stock
from farmared.consultas import q15_descontar_stock as q15
from farmared.errores import NoEncontrado, ValidacionError
from test_q15 import RAIZ, correr_cli, insertar_venta, unidades

TRES_DE_L004 = [{"id_lote": "L004", "id_producto": "PRD002", "unidades": 3}]
UNA_DE_L004 = [{"id_lote": "L004", "id_producto": "PRD002", "unidades": 1}]

# Proceso aparte que corre q15 y muere sin aviso justo antes de marcar la venta, con el script ya ejecutado.
MUERE_ANTES_DE_MARCAR = """
import datetime, os, sys
from pymongo.collection import Collection
from farmared import fechas
from farmared.consultas import q15_descontar_stock as q15

fechas.hoy = lambda: datetime.date.fromisoformat(sys.argv[2])
marcar = Collection.update_one


def morir(self, *args, **kwargs):
    if self.name == "ventas":
        os._exit(9)
    return marcar(self, *args, **kwargs)


Collection.update_one = morir
q15.descontar_stock_venta(sys.argv[1])
"""


def snapshot():
    return snapshots.mongo_snap(), snapshots.redis_snap()


def venta(db, id_venta):
    doc = db.ventas.find_one({"_id": id_venta})
    return doc["stock_descontado"], doc.get("consumos")


def registro(r, id_venta):
    return r.hgetall(claves.descuento(id_venta))


# Los tres fallos alrededor de la marca

def test_si_el_proceso_muere_antes_de_marcar_el_reintento_no_descuenta_otra_vez(datos_provistos, db, r, hoy_fijo):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD002", 3)])
    hijo = subprocess.run([sys.executable, "-c", MUERE_ANTES_DE_MARCAR, id_venta, hoy_fijo.isoformat()],
                          cwd=RAIZ, capture_output=True, text=True, timeout=60)
    assert hijo.returncode == 9, hijo.stderr
    assert unidades(r, "L004") == 87
    assert venta(db, id_venta) == (False, None)
    salida = correr_cli("q15", id_venta)
    assert salida.returncode == 0, salida.stderr
    assert unidades(r, "L004") == 87
    assert venta(db, id_venta) == (True, TRES_DE_L004)
    # el reintento recibió los consumos del registro que dejó el script del proceso muerto
    assert registro(r, id_venta)["usos"] == "2"


def test_si_fallan_la_marca_y_la_reposicion_el_reintento_no_descuenta_otra_vez(datos_provistos, db, r, monkeypatch):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD002", 3)])

    def marca_que_falla(self, *args, **kwargs):
        raise OperationFailure("fallo simulado al marcar la venta")

    def reposicion_que_falla(*args):
        raise redis.ConnectionError("fallo simulado al reponer")

    with monkeypatch.context() as m:
        m.setattr(Collection, "update_one", marca_que_falla)
        m.setattr(stock, "reponer", reposicion_que_falla)
        m.setattr(stock, "reponer_venta", reposicion_que_falla, raising=False)
        with pytest.raises(redis.ConnectionError):
            q15.descontar_stock_venta(id_venta)
    assert unidades(r, "L004") == 87
    assert venta(db, id_venta) == (False, None)
    assert q15.descontar_stock_venta(id_venta)["consumos"] == TRES_DE_L004
    assert unidades(r, "L004") == 87
    assert venta(db, id_venta) == (True, TRES_DE_L004)


def test_si_la_marca_se_aplica_y_se_pierde_la_respuesta_no_repone(datos_provistos, db, r, monkeypatch):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD002", 3)])
    marcar = Collection.update_one

    def aplica_y_pierde_la_respuesta(self, *args, **kwargs):
        resultado = marcar(self, *args, **kwargs)
        if self.name == "ventas":
            raise AutoReconnect("se perdió la respuesta de la marca")
        return resultado

    monkeypatch.setattr(Collection, "update_one", aplica_y_pierde_la_respuesta)
    resultado = q15.descontar_stock_venta(id_venta)
    assert resultado == {"id_venta": id_venta, "id_sucursal": "S001", "consumos": TRES_DE_L004}
    assert unidades(r, "L004") == 87
    assert venta(db, id_venta) == (True, TRES_DE_L004)


def test_si_no_puede_releer_la_venta_no_repone_y_el_reintento_completa(datos_provistos, db, r, monkeypatch):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD002", 3)])
    leer = Collection.find_one

    def marca_sin_respuesta(self, *args, **kwargs):
        raise AutoReconnect("sin respuesta al marcar la venta")

    def relectura_que_falla(self, filtro=None, *args, **kwargs):
        if self.name == "ventas" and filtro.get("stock_descontado") is True:
            raise AutoReconnect("sin respuesta al releer la venta")
        return leer(self, filtro, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(Collection, "update_one", marca_sin_respuesta)
        m.setattr(Collection, "find_one", relectura_que_falla)
        with pytest.raises(AutoReconnect) as e:
            q15.descontar_stock_venta(id_venta)
    assert str(e.value) == "sin respuesta al releer la venta"
    assert unidades(r, "L004") == 87
    assert venta(db, id_venta) == (False, None)
    assert registro(r, id_venta)["usos"] == "1"
    assert q15.descontar_stock_venta(id_venta)["consumos"] == TRES_DE_L004
    assert unidades(r, "L004") == 87
    assert venta(db, id_venta) == (True, TRES_DE_L004)


def interrumpir_la_marca(monkeypatch, aplicarla):
    marcar = Collection.update_one

    def interrumpir(self, *args, **kwargs):
        if self.name != "ventas":
            return marcar(self, *args, **kwargs)
        if aplicarla:
            marcar(self, *args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(Collection, "update_one", interrumpir)


def test_ctrl_c_antes_de_aplicar_la_marca_repone_y_se_propaga(datos_provistos, db, monkeypatch):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD002", 3)])
    antes = snapshot()
    with monkeypatch.context() as m:
        interrumpir_la_marca(m, aplicarla=False)
        with pytest.raises(KeyboardInterrupt):
            q15.descontar_stock_venta(id_venta)
    assert snapshot() == antes


def test_ctrl_c_con_la_marca_aplicada_no_repone_y_se_propaga(datos_provistos, db, r, monkeypatch):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD002", 3)])
    with monkeypatch.context() as m:
        interrumpir_la_marca(m, aplicarla=True)
        with pytest.raises(KeyboardInterrupt):
            q15.descontar_stock_venta(id_venta)
    assert unidades(r, "L004") == 87
    assert venta(db, id_venta) == (True, TRES_DE_L004)


# Llamadas simultáneas sobre la misma venta

def test_otra_llamada_entre_el_script_y_la_marca_no_descuenta_otra_vez(datos_provistos, db, r, monkeypatch):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD002", 1)])
    marcar = Collection.update_one
    otra = {}

    def adelantarse(self, *args, **kwargs):
        if self.name == "ventas" and not otra:
            otra["en_curso"] = True
            otra["resultado"] = q15.descontar_stock_venta(id_venta)
            otra["L004"] = unidades(r, "L004")
        return marcar(self, *args, **kwargs)

    monkeypatch.setattr(Collection, "update_one", adelantarse)
    with pytest.raises(ValidacionError) as e:
        q15.descontar_stock_venta(id_venta)
    assert e.value.codigo == "STOCK_YA_DESCONTADO"
    assert otra["resultado"]["consumos"] == UNA_DE_L004
    assert otra["L004"] == 89
    assert unidades(r, "L004") == 89
    assert venta(db, id_venta) == (True, UNA_DE_L004)


def test_una_llamada_que_leyo_la_venta_antes_de_la_marca_no_descuenta_despues(datos_provistos, db, r, monkeypatch):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD002", 1)])
    descontar = stock.descontar_fefo
    otra, tras_cada_script = {}, []

    def otra_completa_antes(*args, **kwargs):
        # la venta ya se leyó sin marcar; antes del script, otra llamada descuenta, marca y termina
        if not otra:
            otra["en_curso"] = True
            otra["resultado"] = q15.descontar_stock_venta(id_venta)
        consumos = descontar(*args, **kwargs)
        tras_cada_script.append(unidades(r, "L004"))
        return consumos

    monkeypatch.setattr(stock, "descontar_fefo", otra_completa_antes)
    with pytest.raises(ValidacionError) as e:
        q15.descontar_stock_venta(id_venta)
    assert e.value.codigo == "STOCK_YA_DESCONTADO"
    assert otra["resultado"]["consumos"] == UNA_DE_L004
    assert tras_cada_script == [89, 89]
    assert unidades(r, "L004") == 89
    assert venta(db, id_venta) == (True, UNA_DE_L004)


def test_la_que_falla_no_repone_si_otra_ya_recibio_los_consumos(datos_provistos, db, r, monkeypatch):
    id_venta = insertar_venta(db, "C005", "F001", [("PRD002", 1)])
    marcar = Collection.update_one
    otra_lista_para_marcar, primera_termino = threading.Event(), threading.Event()
    resultado_otra = []

    def otra_llamada():
        try:
            resultado_otra.append(q15.descontar_stock_venta(id_venta))
        except Exception as e:
            resultado_otra.append(e)

    otra = threading.Thread(target=otra_llamada)

    def marca(self, *args, **kwargs):
        if threading.current_thread() is otra:
            otra_lista_para_marcar.set()
            assert primera_termino.wait(30)
            return marcar(self, *args, **kwargs)
        # la otra llamada lee la venta y recibe los consumos del registro antes de que esta marca falle
        otra.start()
        assert otra_lista_para_marcar.wait(30)
        raise OperationFailure("fallo simulado al marcar la venta")

    monkeypatch.setattr(Collection, "update_one", marca)
    with pytest.raises(OperationFailure):
        q15.descontar_stock_venta(id_venta)
    assert unidades(r, "L004") == 89
    primera_termino.set()
    otra.join(30)
    assert resultado_otra == [{"id_venta": id_venta, "id_sucursal": "S001", "consumos": UNA_DE_L004}]
    assert unidades(r, "L004") == 89
    assert venta(db, id_venta) == (True, UNA_DE_L004)


# El farmacéutico y la sucursal de la venta

def farmaceutico_sin_sucursal(db):
    db.farmaceuticos.update_one({"_id": "F001"}, {"$set": {"id_sucursal": "S999"}})


@pytest.mark.parametrize("id_farmaceutico,preparar,clase,codigo", [
    ("F999", None, NoEncontrado, "FARMACEUTICO_INEXISTENTE"),
    ("F001", farmaceutico_sin_sucursal, NoEncontrado, "SUCURSAL_INEXISTENTE"),
    ("F007", None, ValidacionError, "SUCURSAL_NO_FARMACIA"),
], ids=["farmaceutico-inexistente", "sucursal-inexistente", "drogueria"])
def test_rechaza_una_venta_sin_farmacia_valida(datos_provistos, db, id_farmaceutico, preparar, clase, codigo):
    id_venta = insertar_venta(db, "C005", id_farmaceutico, [("PRD001", 1)])
    if preparar is not None:
        preparar(db)
    antes = snapshot()
    with pytest.raises(clase) as e:
        q15.descontar_stock_venta(id_venta)
    assert type(e.value) is clase
    assert e.value.codigo == codigo
    assert snapshot() == antes


def test_cli_farmaceutico_inexistente(datos_provistos, db):
    id_venta = insertar_venta(db, "C005", "F999", [("PRD001", 1)])
    antes = snapshot()
    salida = correr_cli("q15", id_venta)
    assert salida.returncode == 1
    assert salida.stdout == ""
    assert salida.stderr == "Error [FARMACEUTICO_INEXISTENTE]: no existe el farmacéutico F999\n"
    assert snapshot() == antes


def test_una_venta_de_un_farmaceutico_hoy_inactivo_se_descuenta(datos_provistos, db, r):
    # la venta pudo hacerse cuando estaba activo; la sucursal sigue siendo una farmacia
    id_venta = insertar_venta(db, "C005", "F004", [("PRD001", 1)])
    resultado = q15.descontar_stock_venta(id_venta)
    assert resultado["id_sucursal"] == "S002"
    assert resultado["consumos"] == [{"id_lote": "L002", "id_producto": "PRD001", "unidades": 1}]
    assert unidades(r, "L002") == 34
