"""q14 interrumpida después del script (Ctrl+C), antes y después del commit, y con MongoDB sin responder."""
import pytest
import redis
from pymongo.client_session import ClientSession
from pymongo.collection import Collection
from pymongo.errors import ServerSelectionTimeoutError

import snapshots
from farmared import claves
from farmared.consultas import q14_registrar_venta as q14


def snapshot():
    return snapshots.mongo_snap(), snapshots.redis_snap()


def venta_rc002():
    return q14.registrar_venta("C003", "F006", [{"id_producto": "PRD004", "cantidad": 1}], "Obra social", "RC002")


def interrumpir_antes_de_enviar_el_commit(monkeypatch):
    def interrumpir(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(ClientSession, "commit_transaction", interrumpir)


def interrumpir_con_el_commit_aplicado(monkeypatch):
    confirmar = ClientSession.commit_transaction

    def interrumpir(self):
        confirmar(self)
        raise KeyboardInterrupt

    monkeypatch.setattr(ClientSession, "commit_transaction", interrumpir)


def interrumpir_la_marca(monkeypatch):
    marcar = Collection.update_one

    def interrumpir(self, *args, **kwargs):
        if self.name == "ventas":
            raise KeyboardInterrupt
        return marcar(self, *args, **kwargs)

    monkeypatch.setattr(Collection, "update_one", interrumpir)


def interrumpir_la_lectura_de_los_lotes(monkeypatch):
    ejecutar = redis.client.Pipeline.execute

    def interrumpir(self, *args, **kwargs):
        if not self.transaction:
            raise KeyboardInterrupt
        return ejecutar(self, *args, **kwargs)

    monkeypatch.setattr(redis.client.Pipeline, "execute", interrumpir)


@pytest.mark.parametrize("interrumpir", [interrumpir_antes_de_enviar_el_commit, interrumpir_la_marca,
                                         interrumpir_la_lectura_de_los_lotes],
                         ids=["antes-de-enviar-el-commit", "marca", "lectura-de-los-lotes"])
def test_ctrl_c_despues_del_script_y_antes_del_commit_deja_todo_como_estaba(datos_provistos, monkeypatch,
                                                                            interrumpir):
    antes = snapshot()
    with monkeypatch.context() as m:
        interrumpir(m)
        with pytest.raises(KeyboardInterrupt):
            venta_rc002()
    assert snapshot() == antes


def test_ctrl_c_con_el_commit_aplicado_conserva_la_venta_con_su_descuento(datos_provistos, db, r, monkeypatch):
    with monkeypatch.context() as m:
        interrumpir_con_el_commit_aplicado(m)
        with pytest.raises(KeyboardInterrupt):
            venta_rc002()
    venta = db.ventas.find_one({"_id": "V017"})
    assert (venta["stock_descontado"], venta["consumos"]) == (
        True, [{"id_lote": "L007", "id_producto": "PRD004", "unidades": 1}])
    assert r.hget(claves.lote("L007"), "unidades") == "21"
    assert r.zscore(claves.UNIDADES, "L007") == 21
    assert db.recetas.find_one({"_id": "RC002"})["dispensas_realizadas"] == 3


def test_no_reintenta_si_mongodb_no_responde(datos_provistos, monkeypatch):
    llamadas = []

    def sin_servidor(*args):
        llamadas.append(1)
        # dentro de una transacción, el driver marca la falta de servidor como transitoria
        raise ServerSelectionTimeoutError("sin servidor disponible", {"errorLabels": ["TransientTransactionError"]})

    monkeypatch.setattr(q14, "_validar", sin_servidor)
    monkeypatch.setattr(q14.time, "sleep", lambda segundos: None)
    antes = snapshot()
    with pytest.raises(ServerSelectionTimeoutError):
        venta_rc002()
    assert llamadas == [1]
    assert snapshot() == antes
