from datetime import timedelta

from farmared import conexiones, fechas, formato


def pipeline(desde, hasta):
    return [
        {"$match": {"activo": True}},
        {"$lookup": {"from": "ventas", "localField": "_id", "foreignField": "id_farmaceutico", "as": "v",
                     "pipeline": [{"$match": {"fecha": {"$gte": desde, "$lt": hasta}, "estado": {"$ne": "Anulada"}}},
                                  {"$project": {"_id": 1}}]}},
        {"$project": {"_id": 0, "id_farmaceutico": "$_id", "nombre": 1, "apellido": 1, "matricula": 1,
                      "id_sucursal": 1, "cantidad_ventas": {"$size": "$v"}}},
        {"$sort": {"cantidad_ventas": -1, "id_farmaceutico": 1}}]


def ventas_recientes_por_farmaceutico(dias=60):
    """Farmacéuticos activos con su cantidad de ventas recientes, sin contar las anuladas.

    Parámetros:
        dias: días hacia atrás desde hoy, inclusive, 60 por defecto.
    Retorna:
        Lista con id_farmaceutico, nombre, apellido, matricula, id_sucursal y cantidad_ventas (puede ser 0),
        de mayor a menor cantidad y por id.
    Motor: MongoDB (aggregate sobre farmaceuticos con $lookup de ventas).
    """
    hoy = fechas.a_datetime(fechas.hoy())
    # Hasta la medianoche de mañana, sin incluirla: cuenta todo el día de hoy aunque una venta tenga hora.
    desde, hasta = hoy - timedelta(days=dias), hoy + timedelta(days=1)
    return formato.a_json(list(conexiones.get_db().farmaceuticos.aggregate(pipeline(desde, hasta))))
