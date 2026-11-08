from farmared import claves, conexiones, fechas


def lotes_stock_bajo(umbral=50):
    """Lotes con menos unidades que el umbral, con producto, sucursal y proveedor.

    Parámetros:
        umbral: unidades mínimas, 50 por defecto (exclusivo).
    Retorna:
        Lista de lotes ordenada por unidades e id_lote.
    Motor: Redis (lotes por unidades) y MongoDB (nombres).
    """
    r = conexiones.get_redis()
    ids_lote = r.zrange(claves.UNIDADES, "-inf", f"({umbral}", byscore=True)
    pipe = r.pipeline(transaction=False)
    for id_lote in ids_lote:
        pipe.hgetall(claves.lote(id_lote))
    lotes = pipe.execute()
    db = conexiones.get_db()
    productos = {p["_id"]: p for p in db.productos.aggregate([
        {"$match": {"_id": {"$in": sorted({l["id_producto"] for l in lotes})}}},
        {"$lookup": {"from": "proveedores", "localField": "id_proveedor", "foreignField": "_id", "as": "pv"}},
        {"$unwind": "$pv"},
        {"$project": {"nombre": 1, "id_proveedor": 1, "proveedor": "$pv.razon_social"}}])}
    sucursales = {s["_id"]: s for s in db.sucursales.find(
        {"_id": {"$in": sorted({l["id_sucursal"] for l in lotes})}}, {"nombre": 1})}
    hoy = fechas.hoy().isoformat()
    salida = []
    for id_lote, l in zip(ids_lote, lotes):
        p = productos[l["id_producto"]]
        salida.append({"id_lote": id_lote, "nro_lote": l["nro_lote"], "unidades": int(l["unidades"]),
                       "vencimiento": l["vencimiento"], "vencido": l["vencimiento"] < hoy,
                       "id_producto": l["id_producto"], "producto": p["nombre"],
                       "id_sucursal": l["id_sucursal"], "sucursal": sucursales[l["id_sucursal"]]["nombre"],
                       "id_proveedor": p["id_proveedor"], "proveedor": p["proveedor"]})
    return sorted(salida, key=lambda x: (x["unidades"], x["id_lote"]))
