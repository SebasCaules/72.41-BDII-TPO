from farmared import conexiones, formato


def pipeline():
    return [
        {"$match": {"estado": "Pendiente"}},
        {"$lookup": {"from": "farmaceuticos", "localField": "id_farmaceutico", "foreignField": "_id", "as": "f"}},
        {"$unwind": "$f"},
        {"$lookup": {"from": "sucursales", "localField": "f.id_sucursal", "foreignField": "_id", "as": "s"}},
        {"$unwind": "$s"},
        {"$sort": {"fecha": 1, "_id": 1}},
        {"$project": {"_id": 0, "id_venta": "$_id", "fecha": 1, "id_cliente": 1, "tipo": 1, "total": 1,
                      "farmaceutico": {"id_farmaceutico": "$f._id", "nombre": "$f.nombre",
                                       "apellido": "$f.apellido", "matricula": "$f.matricula"},
                      "sucursal": {"id_sucursal": "$s._id", "nombre": "$s.nombre"}}}]


def ventas_pendientes():
    """Ventas 'Pendiente' con el farmacéutico asignado, su sucursal y el total.

    Parámetros: ninguno.
    Retorna:
        Lista con id_venta, fecha, id_cliente, tipo, total, farmaceutico y sucursal, por fecha e id_venta.
    Motor: MongoDB (aggregate sobre ventas con $lookup de farmaceuticos y sucursales).
    """
    return formato.a_json(list(conexiones.get_db().ventas.aggregate(pipeline())))
