def alta_cliente(datos):
    """Da de alta un cliente activo con DNI único.

    Parámetros:
        datos: campos del cliente; nro_afiliado es obligatorio salvo con 'Sin cobertura'.
    Retorna:
        El cliente creado, con id_cliente y sus campos.
    Motor: MongoDB (clientes y contador de ids).
    Errores: ValidacionError con DATO_INVALIDO, OBRA_SOCIAL_INVALIDA o DNI_DUPLICADO.
    """
    raise NotImplementedError


def modificar_cliente(id_cliente, cambios):
    """Modifica el contacto, el domicilio o la cobertura de un cliente activo.

    Parámetros:
        id_cliente, cambios: id y claves entre email, telefono, ciudad, provincia, obra_social y nro_afiliado.
    Retorna:
        El cliente modificado, con id_cliente y sus campos.
    Motor: MongoDB (clientes).
    Errores: NoEncontrado si el cliente no existe; ValidacionError con DATO_INVALIDO, CAMPO_NO_MODIFICABLE,
        OBRA_SOCIAL_INVALIDA, AFILIADO_REQUERIDO o CLIENTE_INACTIVO.
    """
    raise NotImplementedError


def baja_cliente(id_cliente):
    """Da de baja lógica a un cliente; si ya está inactivo no cambia nada.

    Parámetros:
        id_cliente: id del cliente, p. ej. "C001".
    Retorna:
        El cliente resultante, con id_cliente y sus campos.
    Motor: MongoDB (clientes).
    Errores: NoEncontrado si el cliente no existe.
    """
    raise NotImplementedError
