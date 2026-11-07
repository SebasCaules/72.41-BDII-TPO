def clientes_sin_ventas():
    """Clientes activos e inactivos sin ventas registradas en el último año.

    Parámetros: ninguno.
    Retorna:
        Lista con id_cliente, nombre, apellido, activo y ultima_venta (o None), ordenada por id_cliente.
    Motor: MongoDB (aggregate sobre clientes con $lookup de ventas).
    """
    raise NotImplementedError
