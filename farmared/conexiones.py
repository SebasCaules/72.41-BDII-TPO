import pymongo
import redis

from farmared import config

# Segundos que se espera a un motor antes de darlo por caído. En la misma red, un motor sano contesta en
# milisegundos; sin este límite, MongoDB espera 30 s para elegir servidor y Redis 5 s por respuesta.
ESPERA_S = 3

_cliente = None
_redis = None


def get_client():
    global _cliente
    if _cliente is None:
        _cliente = pymongo.MongoClient(config.mongo_uri(), serverSelectionTimeoutMS=ESPERA_S * 1000)
    return _cliente


def get_db():
    return get_client()[config.mongo_db()]


def get_redis():
    global _redis
    if _redis is None:
        _redis = redis.Redis.from_url(config.redis_url(), db=config.redis_db(), decode_responses=True,
                                      socket_connect_timeout=ESPERA_S, socket_timeout=ESPERA_S)
    return _redis


def comprobar():
    """Comprueba que los dos motores respondan, antes de una operación que escribe en ambos.

    Retorna:
        None.
    Motor: MongoDB (ping) y Redis (PING).
    Errores: pymongo.errors.ConnectionFailure si MongoDB no responde; redis.exceptions.ConnectionError o
        redis.exceptions.TimeoutError si Redis no responde.
    """
    get_client().admin.command("ping")
    get_redis().ping()


def cerrar():
    global _cliente, _redis
    if _cliente is not None:
        _cliente.close()
    if _redis is not None:
        _redis.close()
    _cliente = _redis = None
