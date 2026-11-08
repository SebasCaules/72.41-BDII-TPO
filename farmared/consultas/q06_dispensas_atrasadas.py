from farmared import conexiones, fechas, formato


def pipeline(hoy_dt):
    return [
        {"$match": {"tipo": "Tratamiento prolongado", "estado": "Vigente", "proxima_dispensa": {"$lt": hoy_dt}}},
        {"$lookup": {"from": "clientes", "localField": "id_cliente", "foreignField": "_id", "as": "cliente"}},
        {"$unwind": "$cliente"},
        {"$sort": {"proxima_dispensa": 1, "_id": 1}},
        {"$set": {"id_receta": "$_id", "cliente.id_cliente": "$cliente._id"}},
        {"$unset": ["_id", "cliente._id"]}]


def dispensas_atrasadas():
    """Recetas de tratamiento prolongado vigentes con la próxima dispensa anterior a hoy.

    Parámetros: ninguno.
    Retorna:
        Lista de recetas con id_receta, sus columnas y el cliente anidado, por proxima_dispensa e id_receta.
    Motor: MongoDB (aggregate sobre recetas con $lookup de clientes).
    """
    hoy_dt = fechas.a_datetime(fechas.hoy())
    return formato.a_json(list(conexiones.get_db().recetas.aggregate(pipeline(hoy_dt))))
