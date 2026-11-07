def clientes_con_varias_recetas():
    """Clientes con más de una receta registrada, con la cantidad.

    Parámetros: ninguno.
    Retorna:
        Lista con id_cliente, nombre, apellido y cantidad_recetas, de mayor a menor cantidad y por id.
    Motor: MongoDB (aggregate sobre recetas con $group y $lookup de clientes).
    """
    raise NotImplementedError
