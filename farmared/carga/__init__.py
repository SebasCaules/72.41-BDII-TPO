from farmared.carga import carga_mongo, carga_redis, lector, validacion
from farmared.errores import ValidacionError


def validar(solo_provistos=False):
    """Valida los CSV sin escribir en ningún motor.

    Parámetros:
        solo_provistos: si es True, no lee los datos adicionales.
    Retorna:
        Lista de errores legibles; vacía si los datos son válidos.
    Motor: ninguno (solo lee los CSV).
    Errores: ValidacionError si un valor no se puede convertir a su tipo.
    """
    return validacion.errores(lector.leer_todo(solo_provistos))


def cargar(solo_provistos=False):
    """Valida los CSV y reemplaza con ellos los datos de MongoDB y Redis.

    Parámetros:
        solo_provistos: si es True, no lee los datos adicionales.
    Retorna:
        Diccionario con los conteos: {'mongo': {coleccion: n}, 'redis': {'lotes': n}}.
    Motor: MongoDB (colecciones e índices) y Redis (lotes y stock).
    Errores: ValidacionError con todos los errores si los datos no son válidos.
    """
    errores = validar(solo_provistos)
    if errores:
        raise ValidacionError("DATO_INVALIDO", "\n".join(errores))
    filas = lector.leer_todo(solo_provistos)
    docs, lotes = carga_mongo.documentos(filas), carga_redis.preparar(filas["stock_lotes"])
    return {"mongo": carga_mongo.cargar_mongo(docs), "redis": carga_redis.cargar_redis(lotes)}
