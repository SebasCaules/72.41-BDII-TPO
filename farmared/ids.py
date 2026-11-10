from pymongo import ReturnDocument

from farmared import conexiones
from farmared.errores import FarmaRedError


def siguiente_id(nombre, prefijo, session=None):
    """Avanza un contador y arma el id siguiente.

    Parámetros:
        nombre: _id del documento de contadores ('clientes', 'ventas' o 'detalle_ventas').
        prefijo: letra del id ('C', 'V' o 'D').
        session: sesión de MongoDB, para que el avance quede dentro de una transacción.
    Retorna:
        El id con al menos tres dígitos, por ejemplo 'C023'.
    Motor: MongoDB (find_one_and_update sobre contadores).
    Errores: FarmaRedError con BASE_SIN_CARGA si el contador no existe; no lo crea.
    """
    doc = conexiones.get_db().contadores.find_one_and_update(
        {"_id": nombre}, {"$inc": {"ultimo": 1}}, return_document=ReturnDocument.AFTER, session=session)
    if doc is None:
        raise FarmaRedError("BASE_SIN_CARGA", f"falta el contador {nombre}: hay que correr python -m farmared carga")
    return f"{prefijo}{doc['ultimo']:03d}"
