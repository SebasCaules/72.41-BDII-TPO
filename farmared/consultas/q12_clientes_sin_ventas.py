from datetime import timedelta

from farmared import conexiones, fechas, formato


def pipeline(desde):
    return [{"$lookup": {"from": "ventas", "localField": "_id", "foreignField": "id_cliente", "as": "ultima",
                         "pipeline": [{"$sort": {"fecha": -1, "_id": -1}}, {"$limit": 1},
                             {"$project": {"_id": 0, "id_venta": "$_id", "fecha": 1, "estado": 1, "total": 1}}]}},
            {"$set": {"ultima_venta": {"$first": "$ultima"}}},
            {"$match": {"ultima_venta.fecha": {"$not": {"$gte": desde}}}},
            {"$sort": {"_id": 1}},
            {"$project": {"_id": 0, "id_cliente": "$_id", "nombre": 1, "apellido": 1, "activo": 1,
                          "ultima_venta": {"$ifNull": ["$ultima_venta", None]}}}]


def clientes_sin_ventas():
    """Clientes activos e inactivos sin ventas registradas en el último año.

    Parámetros: ninguno.
    Retorna:
        Lista con id_cliente, nombre, apellido, activo y ultima_venta (o None), ordenada por id_cliente.
    Motor: MongoDB (aggregate sobre clientes con $lookup de ventas).
    """
    desde = fechas.a_datetime(fechas.hoy()) - timedelta(days=365)
    return formato.a_json(list(conexiones.get_db().clientes.aggregate(pipeline(desde))))
