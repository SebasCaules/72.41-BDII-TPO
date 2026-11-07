def registrar_venta(id_cliente, id_farmaceutico, items, medio_pago, id_receta=None):
    """Registra una venta 'Completada' con sus ítems y descuenta el stock.

    Parámetros:
        id_cliente, id_farmaceutico: ids existentes y activos.
        items: lista de {id_producto, cantidad}.
        medio_pago: uno de los medios de pago válidos.
        id_receta: receta del cliente; obligatoria si hay productos bajo receta.
    Retorna:
        Diccionario con la venta, la receta actualizada (o None) y los consumos.
    Motor: MongoDB (transacción) y Redis (stock).
    Errores: NoEncontrado, ValidacionError, StockInsuficiente.
    """
    raise NotImplementedError
