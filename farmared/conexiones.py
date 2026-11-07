import pymongo
import redis

from farmared import config

_cliente = None
_redis = None


def get_client():
    global _cliente
    if _cliente is None:
        _cliente = pymongo.MongoClient(config.mongo_uri())
    return _cliente


def get_db():
    return get_client()[config.mongo_db()]


def get_redis():
    global _redis
    if _redis is None:
        _redis = redis.Redis.from_url(config.redis_url(), db=config.redis_db(), decode_responses=True)
    return _redis


def cerrar():
    global _cliente, _redis
    if _cliente is not None:
        _cliente.close()
    if _redis is not None:
        _redis.close()
    _cliente = _redis = None
