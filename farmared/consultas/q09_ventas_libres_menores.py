from farmared import conexiones, formato


def pipeline(monto):
    return [{"$match": {"tipo": "Venta libre", "total": {"$lt": monto}, "estado": {"$ne": "Anulada"}}},
            {"$sort": {"fecha": 1, "_id": 1}},
            {"$project": {"_id": 0, "id_venta": "$_id", "fecha": 1, "id_cliente": 1, "id_farmaceutico": 1,
                          "total": 1, "estado": 1, "medio_pago": 1}}]


def ventas_libres_menores(monto=5000):
    """Ventas 'Venta libre' con total menor al monto, sin contar las anuladas.

    Parámetros:
        monto: total máximo en pesos, 5000 por defecto (exclusivo).
    Retorna:
        Lista con id_venta, fecha, id_cliente, id_farmaceutico, total, estado y medio_pago,
        ordenada por fecha e id_venta.
    Motor: MongoDB (aggregate sobre ventas).
    """
    return formato.a_json(list(conexiones.get_db().ventas.aggregate(pipeline(monto))))
