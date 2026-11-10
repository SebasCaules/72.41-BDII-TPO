import pathlib
import subprocess
import sys

import pytest

from farmared import claves
from farmared.consultas import q08_lotes_stock_bajo as q08
from farmared.errores import FarmaRedError

RAIZ = pathlib.Path(__file__).resolve().parent.parent
LOTE = "L011"   # 48 unidades con los datos provistos: queda bajo el umbral


def sin_hash(db, r):
    r.delete(claves.lote(LOTE))


def sin_nro_lote(db, r):
    r.hdel(claves.lote(LOTE), "nro_lote")


def sin_id_producto(db, r):
    r.hdel(claves.lote(LOTE), "id_producto")


def unidades_que_no_son_un_numero(db, r):
    r.hset(claves.lote(LOTE), "unidades", "abc")


def producto_inexistente(db, r):
    r.hset(claves.lote(LOTE), "id_producto", "PRD999")


def sucursal_inexistente(db, r):
    r.hset(claves.lote(LOTE), "id_sucursal", "S999")


def proveedor_inexistente(db, r):
    db.productos.update_one({"_id": r.hget(claves.lote(LOTE), "id_producto")}, {"$set": {"id_proveedor": "PRV999"}})


@pytest.mark.parametrize("desacuerdo", [sin_hash, sin_nro_lote, sin_id_producto, unidades_que_no_son_un_numero,
                                        producto_inexistente, sucursal_inexistente, proveedor_inexistente])
def test_si_redis_y_mongo_no_coinciden_informa_el_lote(datos_provistos, db, r, desacuerdo):
    desacuerdo(db, r)
    with pytest.raises(FarmaRedError) as error:
        q08.lotes_stock_bajo()
    assert error.value.codigo == "DATOS_INCONSISTENTES"
    assert LOTE in error.value.mensaje


def test_la_cli_informa_el_desacuerdo_con_su_codigo(datos_provistos, db, r):
    producto_inexistente(db, r)
    salida = subprocess.run([sys.executable, "-m", "farmared", "q08"], cwd=RAIZ, capture_output=True, text=True,
                            timeout=60)
    assert (salida.returncode, salida.stdout) == (1, "")
    assert salida.stderr.startswith("Error [DATOS_INCONSISTENTES]: "), salida.stderr
    assert "Traceback" not in salida.stderr


def test_un_lote_sobre_el_umbral_no_se_revisa(datos_provistos, db, r):
    # L001 tiene 120 unidades: aunque apunte a un producto que no existe, q08 no lo lee.
    r.hset(claves.lote("L001"), "id_producto", "PRD999")
    assert "L001" not in [l["id_lote"] for l in q08.lotes_stock_bajo()]
