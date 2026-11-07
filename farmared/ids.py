from pymongo import ReturnDocument

from farmared import conexiones


def siguiente_id(nombre, prefijo, session=None):
    doc = conexiones.get_db().contadores.find_one_and_update(
        {"_id": nombre}, {"$inc": {"ultimo": 1}}, return_document=ReturnDocument.AFTER, session=session)
    if doc is None:
        raise RuntimeError(f"falta el contador {nombre}: correr la carga")
    return f"{prefijo}{doc['ultimo']:03d}"
