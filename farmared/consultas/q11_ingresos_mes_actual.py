from farmared import conexiones, formato

TZ = "America/Argentina/Buenos_Aires"
PIPELINE_VISTA = [
    {"$match": {"$expr": {"$and": [
        {"$eq": ["$estado", "Completada"]},
        {"$eq": [{"$dateToString": {"format": "%Y-%m", "date": "$fecha"}},
                 {"$dateToString": {"format": "%Y-%m", "date": "$$NOW", "timezone": TZ}}]}]}}},
    {"$group": {"_id": "$id_farmaceutico", "ingresos": {"$sum": "$total"}, "cantidad_ventas": {"$sum": 1}}},
    {"$lookup": {"from": "farmaceuticos", "localField": "_id", "foreignField": "_id", "as": "f"}},
    {"$unwind": "$f"},
    {"$project": {"_id": 0, "id_farmaceutico": "$_id", "nombre": "$f.nombre", "apellido": "$f.apellido",
                  "id_sucursal": "$f.id_sucursal", "ingresos": 1, "cantidad_ventas": 1}},
]


def ingresos_mes_actual():
    """Ingresos del mes actual por farmacéutico, solo de ventas 'Completada'.

    Parámetros: ninguno.
    Retorna:
        Lista con id_farmaceutico, nombre, apellido, id_sucursal, cantidad_ventas e ingresos.
    Motor: MongoDB (vista ingresos_mes_actual).
    """
    db = conexiones.get_db()
    db.drop_collection("ingresos_mes_actual")
    db.create_collection("ingresos_mes_actual", viewOn="ventas", pipeline=PIPELINE_VISTA)
    return formato.a_json(list(db.ingresos_mes_actual.find(
        {}, sort=[("ingresos", -1), ("id_farmaceutico", 1)])))
