from farmared import claves, conexiones, fechas
from farmared.errores import FarmaRedError

# campos del hash del lote con que se arma cada fila
CAMPOS = ("id_producto", "id_sucursal", "nro_lote", "unidades", "vencimiento")


def _no_coinciden(id_lote, detalle):
    return FarmaRedError("DATOS_INCONSISTENTES", f"Redis y MongoDB no coinciden en el lote {id_lote}: {detalle}")


def _revisar(id_lote, lote):
    if not lote:
        raise _no_coinciden(id_lote, f"está en {claves.UNIDADES} pero no existe {claves.lote(id_lote)}")
    faltan = [c for c in CAMPOS if c not in lote]
    if faltan:
        raise _no_coinciden(id_lote, f"a {claves.lote(id_lote)} le falta {', '.join(faltan)}")
    try:
        int(lote["unidades"])
    except ValueError:
        raise _no_coinciden(id_lote, f"las unidades de {claves.lote(id_lote)} no son un número: "
                                     f"{lote['unidades']}") from None


def lotes_stock_bajo(umbral=50):
    """Lotes con menos unidades que el umbral, con producto, sucursal y proveedor.

    Parámetros:
        umbral: unidades mínimas, 50 por defecto (exclusivo).
    Retorna:
        Lista de lotes ordenada por unidades e id_lote.
    Motor: Redis (lotes por unidades) y MongoDB (nombres).
    Errores: FarmaRedError DATOS_INCONSISTENTES si un lote no tiene su hash en Redis, al hash le falta un campo
        o sus unidades no son un número, o apunta a un producto, un proveedor o una sucursal que MongoDB no tiene.
    """
    r = conexiones.get_redis()
    ids_lote = r.zrange(claves.UNIDADES, "-inf", f"({umbral}", byscore=True)
    pipe = r.pipeline(transaction=False)
    for id_lote in ids_lote:
        pipe.hgetall(claves.lote(id_lote))
    lotes = pipe.execute()
    for id_lote, l in zip(ids_lote, lotes):
        _revisar(id_lote, l)
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
        p, s = productos.get(l["id_producto"]), sucursales.get(l["id_sucursal"])
        if p is None:
            raise _no_coinciden(id_lote, f"MongoDB no tiene el producto {l['id_producto']} o su proveedor")
        if s is None:
            raise _no_coinciden(id_lote, f"MongoDB no tiene la sucursal {l['id_sucursal']}")
        salida.append({"id_lote": id_lote, "nro_lote": l["nro_lote"], "unidades": int(l["unidades"]),
                       "vencimiento": l["vencimiento"], "vencido": l["vencimiento"] < hoy,
                       "id_producto": l["id_producto"], "producto": p["nombre"],
                       "id_sucursal": l["id_sucursal"], "sucursal": s["nombre"],
                       "id_proveedor": p["id_proveedor"], "proveedor": p["proveedor"]})
    return sorted(salida, key=lambda x: (x["unidades"], x["id_lote"]))
