def top_productos_vendidos(limite=5):
    """Productos más vendidos en unidades, solo de ventas 'Completada'.

    Parámetros:
        limite: cantidad de productos, 5 por defecto.
    Retorna:
        Lista con id_producto, nombre y unidades, de mayor a menor cantidad de unidades y por id.
    Motor: MongoDB (aggregate sobre ventas con $unwind de items y $lookup de productos).
    Errores: ValidacionError si limite es menor que 1.
    """
    raise NotImplementedError
