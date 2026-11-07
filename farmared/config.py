import os


def mongo_uri():
    return os.environ.get("MONGO_URI", "mongodb://mongo:27017/?replicaSet=rs0")


def mongo_db():
    return os.environ.get("MONGO_DB", "farmared")


def redis_url():
    return os.environ.get("REDIS_URL", "redis://redis:6379")


def redis_db():
    return int(os.environ.get("REDIS_DB", "0"))
