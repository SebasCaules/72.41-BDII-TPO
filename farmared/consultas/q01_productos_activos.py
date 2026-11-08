from farmared import conexiones, formato


def pipeline():
    return [
        {"$match": {"activo": True}},
        {"$lookup": {"from": "proveedores", "localField": "id_proveedor", "foreignField": "_id", "as": "proveedor"}},
        {"$unwind": "$proveedor"},
        {"$sort": {"_id": 1}},
        {"$set": {"id_producto": "$_id", "proveedor.id_proveedor": "$proveedor._id"}},
        {"$unset": ["_id", "id_proveedor", "proveedor._id"]}]


def productos_activos_con_proveedor():
    """Productos activos con todos los datos de su proveedor.

    Parámetros: ninguno.
    Retorna:
        Lista de productos con id_producto, sus columnas y el proveedor anidado, ordenada por id_producto.
    Motor: MongoDB (aggregate sobre productos con $lookup de proveedores).
    """
    return formato.a_json(list(conexiones.get_db().productos.aggregate(pipeline())))
