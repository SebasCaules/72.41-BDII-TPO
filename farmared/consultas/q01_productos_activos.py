def productos_activos_con_proveedor():
    """Productos activos con todos los datos de su proveedor.

    Parámetros: ninguno.
    Retorna:
        Lista de productos con id_producto, sus columnas y el proveedor anidado, ordenada por id_producto.
    Motor: MongoDB (aggregate sobre productos con $lookup de proveedores).
    """
    raise NotImplementedError
