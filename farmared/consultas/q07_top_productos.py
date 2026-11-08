from farmared import conexiones, formato
from farmared.errores import ValidacionError


def pipeline(limite):
    return [{"$match": {"estado": "Completada"}},
            {"$unwind": "$items"},
            {"$group": {"_id": "$items.id_producto", "unidades": {"$sum": "$items.cantidad"}}},
            {"$sort": {"unidades": -1, "_id": 1}},
            {"$limit": limite},
            {"$lookup": {"from": "productos", "localField": "_id", "foreignField": "_id", "as": "p"}},
            {"$unwind": "$p"},
            {"$sort": {"unidades": -1, "_id": 1}},
            {"$project": {"_id": 0, "id_producto": "$_id", "nombre": "$p.nombre", "unidades": 1}}]


def top_productos_vendidos(limite=5):
    """Productos más vendidos en unidades, solo de ventas 'Completada'.

    Parámetros:
        limite: cantidad de productos, 5 por defecto.
    Retorna:
        Lista con id_producto, nombre y unidades, de mayor a menor cantidad de unidades y por id.
    Motor: MongoDB (aggregate sobre ventas con $unwind de items y $lookup de productos).
    Errores: ValidacionError si limite es menor que 1.
    """
    if limite < 1:
        raise ValidacionError("DATO_INVALIDO", f"el límite debe ser al menos 1: {limite}")
    return formato.a_json(list(conexiones.get_db().ventas.aggregate(pipeline(limite))))
