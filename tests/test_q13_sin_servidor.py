import pymongo
import pytest
from pymongo.errors import ServerSelectionTimeoutError

from farmared import conexiones
from farmared.consultas import q13_abm_clientes as q13

DATOS = {"nombre": "Paula", "apellido": "Sosa", "dni": "99100200", "email": "paula.sosa@gmail.com",
         "telefono": "1144556677", "ciudad": "La Plata", "provincia": "Buenos Aires", "obra_social": "OSDE",
         "nro_afiliado": "OS-990001"}
OPERACIONES = {
    "alta": lambda: q13.alta_cliente(dict(DATOS)),
    "modificar": lambda: q13.modificar_cliente("C001", {"email": "lu@gmail.com"}),
    "baja": lambda: q13.baja_cliente("C001"),
}


@pytest.fixture
def sin_servidor(monkeypatch):
    """Apunta q13 a un MongoDB que no existe y cuenta cuántas transacciones intenta."""
    cliente = pymongo.MongoClient("mongodb://127.0.0.1:9/", serverSelectionTimeoutMS=300, connect=False)
    intentos = []
    abrir = cliente.start_session

    def contar(*argumentos, **opciones):
        intentos.append(1)
        return abrir(*argumentos, **opciones)

    monkeypatch.setattr(cliente, "start_session", contar)
    monkeypatch.setattr(conexiones, "get_client", lambda: cliente)
    monkeypatch.setattr(conexiones, "get_db", lambda: cliente["farmared_test"])
    yield intentos
    cliente.close()


@pytest.mark.parametrize("operacion", OPERACIONES)
def test_sin_servidor_no_se_reintenta(sin_servidor, operacion):
    # Dentro de una transacción, pymongo marca el error de selección de servidor como transitorio; reintentarlo
    # solo multiplicaría la espera.
    with pytest.raises(ServerSelectionTimeoutError) as capturado:
        OPERACIONES[operacion]()
    assert capturado.value.has_error_label("TransientTransactionError")
    assert len(sin_servidor) == 1
