def dispensas_atrasadas():
    """Recetas de tratamiento prolongado vigentes con la próxima dispensa anterior a hoy.

    Parámetros: ninguno.
    Retorna:
        Lista de recetas con id_receta, sus columnas y el cliente anidado, por proxima_dispensa e id_receta.
    Motor: MongoDB (aggregate sobre recetas con $lookup de clientes).
    """
    raise NotImplementedError
