from farmared import conexiones, stock
from farmared.errores import NoEncontrado, ValidacionError


def descontar_stock_venta(id_venta, session=None):
    """Descuenta el stock de una venta registrada, por FEFO y sin lotes vencidos.

    Parámetros:
        id_venta: id de la venta, p. ej. "V017".
        session: sesión de MongoDB cuando la llamada es parte de una transacción.
    Retorna:
        Diccionario con id_venta, id_sucursal y los consumos por lote.
    Motor: Redis (script Lua sobre los lotes) y MongoDB (marca de la venta).
    Errores: NoEncontrado, ValidacionError, StockInsuficiente.
    """
    db = conexiones.get_db()
    venta = db.ventas.find_one({"_id": id_venta}, session=session)
    if venta is None:
        raise NoEncontrado("VENTA_INEXISTENTE", f"no existe la venta {id_venta}")
    if venta["estado"] != "Completada":
        raise ValidacionError("VENTA_NO_COMPLETADA", f"la venta {id_venta} está {venta['estado']}")
    if venta.get("stock_descontado"):
        raise ValidacionError("STOCK_YA_DESCONTADO", f"la venta {id_venta} ya descontó stock")
    farmaceutico = db.farmaceuticos.find_one({"_id": venta["id_farmaceutico"]}, session=session)
    id_sucursal = farmaceutico["id_sucursal"]
    consumos = stock.descontar_fefo(id_sucursal, venta["items"])
    try:
        res = db.ventas.update_one({"_id": id_venta, "stock_descontado": False},
                                   {"$set": {"stock_descontado": True, "consumos": consumos}},
                                   session=session)
        if res.matched_count != 1:
            raise ValidacionError("STOCK_YA_DESCONTADO", f"la venta {id_venta} ya descontó stock")
    except Exception:
        stock.reponer(consumos)
        raise
    return {"id_venta": id_venta, "id_sucursal": id_sucursal, "consumos": consumos}
