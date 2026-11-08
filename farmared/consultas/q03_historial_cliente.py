from farmared import conexiones, formato
from farmared.errores import NoEncontrado


def pipeline(id_cliente):
    return [
        {"$match": {"id_cliente": id_cliente}},
        {"$project": {"_id": 0, "registro": {"$literal": "venta"}, "orden": {"$literal": 1}, "id": "$_id",
                      "fecha": 1, "tipo": 1, "estado": 1, "total": 1, "id_receta": 1, "id_farmaceutico": 1,
                      "items": 1}},
        {"$unionWith": {"coll": "recetas", "pipeline": [
            {"$match": {"id_cliente": id_cliente}},
            {"$project": {"_id": 0, "registro": {"$literal": "receta"}, "orden": {"$literal": 0}, "id": "$_id",
                          "fecha": "$fecha_emision", "tipo": 1, "estado": 1, "medico": 1,
                          "dispensas_autorizadas": 1, "dispensas_realizadas": 1, "proxima_dispensa": 1}}]}},
        {"$sort": {"fecha": 1, "orden": 1, "id": 1}},
        {"$unset": "orden"}]


def historial_cliente(id_cliente):
    """Ventas y recetas de un cliente en orden cronológico.

    Parámetros:
        id_cliente: id del cliente, p. ej. "C001".
    Retorna:
        Lista de registros ('venta' o 'receta') ordenada por fecha.
    Motor: MongoDB (aggregate sobre ventas con $unionWith de recetas).
    Errores: NoEncontrado si el cliente no existe.
    """
    db = conexiones.get_db()
    if db.clientes.find_one({"_id": id_cliente}, {"_id": 1}) is None:
        raise NoEncontrado("CLIENTE_INEXISTENTE", f"no existe el cliente {id_cliente}")
    return formato.a_json(list(db.ventas.aggregate(pipeline(id_cliente))))
