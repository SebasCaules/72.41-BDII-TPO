def clientes_por_sucursal(id_sucursal):
    """Clientes con al menos una venta registrada por un farmacéutico de la sucursal.

    Parámetros:
        id_sucursal: id de la sucursal, p. ej. "S001".
    Retorna:
        Lista con id_cliente, nombre, apellido, dni, activo y cantidad_ventas, ordenada por id_cliente.
    Motor: MongoDB (aggregate sobre farmaceuticos con $lookup de ventas y clientes).
    Errores: NoEncontrado si la sucursal no existe.
    """
    raise NotImplementedError
