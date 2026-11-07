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
    raise NotImplementedError
