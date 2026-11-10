from farmared import conexiones, formato
from farmared.dominio import validar_id
from farmared.errores import NoEncontrado


def pipeline(id_sucursal):
    return [{"$match": {"id_sucursal": id_sucursal}},
            {"$lookup": {"from": "ventas", "localField": "_id", "foreignField": "id_farmaceutico", "as": "v",
                         "pipeline": [{"$project": {"id_cliente": 1}}]}},
            {"$unwind": "$v"},
            {"$group": {"_id": "$v.id_cliente", "cantidad_ventas": {"$sum": 1}}},
            {"$lookup": {"from": "clientes", "localField": "_id", "foreignField": "_id", "as": "c"}},
            {"$unwind": "$c"},
            {"$sort": {"_id": 1}},
            {"$project": {"_id": 0, "id_cliente": "$_id", "nombre": "$c.nombre", "apellido": "$c.apellido",
                          "dni": "$c.dni", "activo": "$c.activo", "cantidad_ventas": 1}}]


def clientes_por_sucursal(id_sucursal):
    """Clientes con al menos una venta registrada por un farmacéutico de la sucursal.

    Parámetros:
        id_sucursal: id de la sucursal, p. ej. "S001".
    Retorna:
        Lista con id_cliente, nombre, apellido, dni, activo y cantidad_ventas, ordenada por id_cliente.
    Motor: MongoDB (aggregate sobre farmaceuticos con $lookup de ventas y clientes).
    Errores: NoEncontrado si la sucursal no existe; ValidacionError con DATO_INVALIDO si el id no es texto.
    """
    validar_id("id_sucursal", id_sucursal)
    db = conexiones.get_db()
    if db.sucursales.find_one({"_id": id_sucursal}, {"_id": 1}) is None:
        raise NoEncontrado("SUCURSAL_INEXISTENTE", f"no existe la sucursal {id_sucursal}")
    return formato.a_json(list(db.farmaceuticos.aggregate(pipeline(id_sucursal))))
