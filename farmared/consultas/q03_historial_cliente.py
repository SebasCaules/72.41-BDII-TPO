def historial_cliente(id_cliente):
    """Ventas y recetas de un cliente en orden cronológico.

    Parámetros:
        id_cliente: id del cliente, p. ej. "C001".
    Retorna:
        Lista de registros ('venta' o 'receta') ordenada por fecha.
    Motor: MongoDB (aggregate sobre ventas con $unionWith de recetas).
    Errores: NoEncontrado si el cliente no existe.
    """
    raise NotImplementedError
