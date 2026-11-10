from farmared import conexiones, formato
from farmared.errores import FarmaRedError

VISTA = "ingresos_mes_actual"
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


def crear_vista():
    """Crea la vista ingresos_mes_actual sobre ventas, reemplazando la que hubiera. La llama la carga.

    Parámetros: ninguno.
    Retorna: nada.
    Motor: MongoDB (create_collection con viewOn y pipeline).
    """
    db = conexiones.get_db()
    db.drop_collection(VISTA)
    db.create_collection(VISTA, viewOn="ventas", pipeline=PIPELINE_VISTA)


def ingresos_mes_actual():
    """Ingresos del mes actual por farmacéutico, solo de ventas 'Completada'.

    La vista la crea la carga y esta función solo la lee. Su definición no cambia de un mes a otro: el servidor
    evalúa $$NOW en cada lectura y lo pasa a hora argentina, así que el resultado siempre es el del mes en curso.

    Parámetros: ninguno.
    Retorna:
        Lista con id_farmaceutico, nombre, apellido, id_sucursal, cantidad_ventas e ingresos, de mayor a menor
        ingreso y por id_farmaceutico.
    Motor: MongoDB (vista ingresos_mes_actual).
    Errores: FarmaRedError BASE_SIN_CARGA si la vista no existe porque la base no se cargó.
    """
    db = conexiones.get_db()
    if not db.list_collection_names(filter={"name": VISTA}):
        raise FarmaRedError("BASE_SIN_CARGA", f"falta la vista {VISTA}: hay que correr python -m farmared carga")
    return formato.a_json(list(db[VISTA].find({}, sort=[("ingresos", -1), ("id_farmaceutico", 1)])))
