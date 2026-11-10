import copy
import datetime
import shutil

import pytest

from farmared import carga
from farmared.carga import lector
from farmared.carga.validacion import errores


@pytest.fixture
def filas():
    return copy.deepcopy(lector.leer_todo(True))


def receta(filas, id_):
    return next(f for f in filas["recetas"] if f["id_receta"] == id_)


@pytest.mark.parametrize("proxima", ["2020-01-01", "2026-07-14"])
def test_proxima_dispensa_anterior_a_la_emision(filas, proxima):
    rc002 = receta(filas, "RC002")
    assert rc002["fecha_emision"] == datetime.datetime(2026, 7, 15)
    rc002["proxima_dispensa"] = datetime.datetime.strptime(proxima, "%Y-%m-%d")
    assert errores(filas) == [
        f"recetas.csv RC002: [receta-coherente] proxima_dispensa {proxima} anterior a la emisión 2026-07-15"]


@pytest.mark.parametrize("proxima", ["2026-07-15", "2026-07-16"])
def test_proxima_dispensa_desde_la_emision_es_valida(filas, proxima):
    receta(filas, "RC002")["proxima_dispensa"] = datetime.datetime.strptime(proxima, "%Y-%m-%d")
    assert errores(filas) == []


def test_proxima_dispensa_anterior_a_la_emision_leida_del_csv(tmp_path, monkeypatch):
    shutil.copytree(lector.DATOS / "provistos", tmp_path / "provistos")
    ruta = tmp_path / "provistos" / "recetas.csv"
    texto = ruta.read_text(encoding="utf-8")
    assert texto.count("2026-07-15,Tratamiento prolongado,3,2,2026-09-15,") == 1
    ruta.write_text(texto.replace("2026-07-15,Tratamiento prolongado,3,2,2026-09-15,",
                                  "2026-07-15,Tratamiento prolongado,3,2,2020-01-01,"), encoding="utf-8")
    monkeypatch.setattr(lector, "DATOS", tmp_path)
    assert carga.validar(True) == [
        "recetas.csv RC002: [receta-coherente] proxima_dispensa 2020-01-01 anterior a la emisión 2026-07-15"]
