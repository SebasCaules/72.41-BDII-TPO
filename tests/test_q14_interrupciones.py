"""q14 interrumpida después del script (Ctrl+C) y con MongoDB sin responder."""
import pytest
import redis
from pymongo.client_session import ClientSession
from pymongo.collection import Collection
from pymongo.errors import ServerSelectionTimeoutError

import snapshots
from farmared.consultas import q14_registrar_venta as q14


def snapshot():
    return snapshots.mongo_snap(), snapshots.redis_snap()


def venta_rc002():
    return q14.registrar_venta("C003", "F006", [{"id_producto": "PRD004", "cantidad": 1}], "Obra social", "RC002")


def interrumpir_el_commit(monkeypatch):
    def interrumpir(self):
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


@pytest.mark.parametrize("interrumpir", [interrumpir_el_commit, interrumpir_la_marca,
                                         interrumpir_la_lectura_de_los_lotes],
                         ids=["commit", "marca", "lectura-de-los-lotes"])
def test_ctrl_c_despues_del_script_deja_todo_como_estaba(datos_provistos, monkeypatch, interrumpir):
    antes = snapshot()
    with monkeypatch.context() as m:
        interrumpir(m)
        with pytest.raises(KeyboardInterrupt):
            venta_rc002()
    assert snapshot() == antes


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
