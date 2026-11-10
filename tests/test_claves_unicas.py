import copy
import shutil

import pytest

from farmared import carga
from farmared.carga import lector
from farmared.carga.validacion import errores


@pytest.fixture(scope="module")
def originales():
    return lector.leer_todo(True)


@pytest.fixture
def filas(originales):
    return copy.deepcopy(originales)


def fila(filas, archivo, clave, id_):
    return next(f for f in filas[archivo] if f[clave] == id_)


@pytest.mark.parametrize("cuit", ["30712345671", "30-71234567-1", "3071234567-1"])
def test_cuit_repetido_con_o_sin_guiones(filas, cuit):
    filas["proveedores"].append({**fila(filas, "proveedores", "id_proveedor", "PRV005"), "id_proveedor": "PRV006",
                                 "cuit": cuit})
    assert errores(filas) == [f"proveedores.csv PRV006: [clave-unica] cuit {cuit} repetido"]


def test_cuit_distinto_sin_guiones_es_valido(filas):
    filas["proveedores"].append({**fila(filas, "proveedores", "id_proveedor", "PRV005"), "id_proveedor": "PRV006",
                                 "cuit": "30712345672"})
    assert errores(filas) == []


def test_lote_repetido_en_la_misma_sucursal_y_producto(filas):
    filas["stock_lotes"].append({**fila(filas, "stock_lotes", "id_lote", "L001"), "id_lote": "L019", "unidades": 10})
    assert errores(filas) == ["stock_lotes.csv L019: [clave-unica] id_sucursal S001, id_producto PRD001, "
                              "nro_lote L-2501A repetidos"]


@pytest.mark.parametrize("cambio", [{"id_sucursal": "S004"}, {"id_producto": "PRD002"}, {"nro_lote": "L-2501B"}])
def test_lote_con_el_mismo_numero_en_otra_sucursal_u_otro_producto_es_valido(filas, cambio):
    filas["stock_lotes"].append({**fila(filas, "stock_lotes", "id_lote", "L001"), "id_lote": "L019", **cambio})
    assert errores(filas) == []


def test_el_mismo_lote_ya_esta_en_varias_sucursales_de_los_provistos(originales):
    lotes = [f for f in originales["stock_lotes"] if f["nro_lote"] == "L-2501A" and f["id_producto"] == "PRD001"]
    assert len({f["id_sucursal"] for f in lotes}) == len(lotes) > 1
    assert errores(originales) == []


def test_lote_repetido_entre_provistos_y_adicionales_leido_del_csv(tmp_path, monkeypatch):
    shutil.copytree(lector.DATOS / "provistos", tmp_path / "provistos")
    (tmp_path / "adicionales").mkdir()
    encabezado = (tmp_path / "provistos" / "stock_lotes.csv").read_text(encoding="utf-8").splitlines()[0]
    (tmp_path / "adicionales" / "stock_lotes.csv").write_text(
        f"{encabezado}\nL900,PRD001,S001,L-2501A,10,2027-08-31\n", encoding="utf-8")
    monkeypatch.setattr(lector, "DATOS", tmp_path)
    assert carga.validar() == ["stock_lotes.csv L900: [clave-unica] id_sucursal S001, id_producto PRD001, "
                               "nro_lote L-2501A repetidos"]
