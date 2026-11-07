def ventas_recientes_por_farmaceutico(dias=60):
    """Farmacéuticos activos con su cantidad de ventas recientes, sin contar las anuladas.

    Parámetros:
        dias: días hacia atrás desde hoy, inclusive, 60 por defecto.
    Retorna:
        Lista con id_farmaceutico, nombre, apellido, matricula, id_sucursal y cantidad_ventas (puede ser 0),
        de mayor a menor cantidad y por id.
    Motor: MongoDB (aggregate sobre farmaceuticos con $lookup de ventas).
    """
    raise NotImplementedError
