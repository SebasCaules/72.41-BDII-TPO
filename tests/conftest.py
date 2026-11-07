import datetime
import os

os.environ["MONGO_DB"] = "farmared_test"
os.environ["REDIS_DB"] = "1"

import pytest  # noqa: E402

from farmared import carga, config, conexiones, fechas  # noqa: E402

HOY = datetime.date(2026, 11, 3)


def pytest_sessionstart(session):
    if not config.mongo_db().endswith("_test"):
        pytest.exit("los tests corren solo sobre una base *_test", returncode=2)


@pytest.fixture(autouse=True)
def hoy_fijo(monkeypatch):
    monkeypatch.setattr(fechas, "hoy", lambda: HOY)
    return HOY


@pytest.fixture
def datos_provistos():
    carga.cargar(solo_provistos=True)


@pytest.fixture
def datos_completos():
    carga.cargar()


@pytest.fixture
def db():
    return conexiones.get_db()


@pytest.fixture
def r():
    return conexiones.get_redis()
