from farmared import conexiones, formato


def pipeline():
    return [
        {"$group": {"_id": "$id_cliente", "cantidad_recetas": {"$sum": 1}}},
        {"$match": {"cantidad_recetas": {"$gt": 1}}},
        {"$lookup": {"from": "clientes", "localField": "_id", "foreignField": "_id", "as": "c"}},
        {"$unwind": "$c"},
        {"$sort": {"cantidad_recetas": -1, "_id": 1}},
        {"$project": {"_id": 0, "id_cliente": "$_id", "nombre": "$c.nombre", "apellido": "$c.apellido",
                      "cantidad_recetas": 1}}]


def clientes_con_varias_recetas():
    """Clientes con más de una receta registrada, con la cantidad.

    Parámetros: ninguno.
    Retorna:
        Lista con id_cliente, nombre, apellido y cantidad_recetas, de mayor a menor cantidad y por id.
    Motor: MongoDB (aggregate sobre recetas con $group y $lookup de clientes).
    """
    return formato.a_json(list(conexiones.get_db().recetas.aggregate(pipeline())))
