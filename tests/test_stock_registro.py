import json
import pathlib

import pytest
import redis

import snapshots
from farmared import carga, claves, fechas, stock
from farmared.consultas import q14_registrar_venta as q14
from farmared.errores import StockInsuficiente

LUA = pathlib.Path(__file__).resolve().parent.parent / "farmared" / "lua" / "descontar_fefo.lua"
PEDIDO = [{"id_producto": "PRD003", "cantidad": 42}]
CONSUMOS = [{"id_lote": "L005", "id_producto": "PRD003", "unidades": 40},
            {"id_lote": "L015", "id_producto": "PRD003", "unidades": 2}]


def unidades(r, id_lote):
    return int(r.hget(claves.lote(id_lote), "unidades"))


def registros(r):
    return sorted(r.scan_iter(match="descuento:*"))


# El registro por venta

def test_el_descuento_con_venta_deja_su_registro_en_el_mismo_paso(datos_provistos, r):
    assert stock.descontar_fefo("S001", PEDIDO, id_venta="V900") == CONSUMOS
    assert r.type(claves.descuento("V900")) == "hash"
    registro = r.hgetall(claves.descuento("V900"))
    assert json.loads(registro["consumos"]) == [["L005", 40], ["L015", 2]]
    assert registro["usos"] == "1"
    assert (unidades(r, "L005"), unidades(r, "L015")) == (0, 98)


def test_la_misma_venta_no_descuenta_dos_veces(datos_provistos, r):
    stock.descontar_fefo("S001", PEDIDO, id_venta="V900")
    antes = {k: v for k, v in snapshots.redis_snap().items() if k != claves.descuento("V900")}
    assert stock.descontar_fefo("S001", PEDIDO, id_venta="V900") == CONSUMOS
    despues = snapshots.redis_snap()
    assert despues.pop(claves.descuento("V900"))["usos"] == "2"
    assert despues == antes
    assert (unidades(r, "L005"), unidades(r, "L015")) == (0, 98)


def test_sin_venta_no_se_registra_nada(datos_provistos, r):
    stock.descontar_fefo("S001", PEDIDO)
    assert registros(r) == []


def test_un_rechazo_por_stock_no_deja_registro(datos_provistos):
    antes = snapshots.redis_snap()
    with pytest.raises(StockInsuficiente):
        stock.descontar_fefo("S001", [{"id_producto": "PRD003", "cantidad": 141}], id_venta="V900")
    assert snapshots.redis_snap() == antes


def test_el_estado_de_redis_de_los_tests_incluye_el_registro(datos_provistos):
    antes = snapshots.redis_snap()
    stock.descontar_fefo("S001", PEDIDO, id_venta="V900")
    assert claves.descuento("V900") in snapshots.redis_snap()
    assert claves.descuento("V900") not in antes


def test_la_carga_borra_los_registros(datos_provistos, r):
    stock.descontar_fefo("S001", PEDIDO, id_venta="V900")
    carga.cargar(solo_provistos=True)
    assert registros(r) == []
    assert unidades(r, "L005") == 40


def test_el_camino_de_q14_no_deja_registro(datos_provistos, r):
    q14.registrar_venta("C005", "F001", [{"id_producto": "PRD002", "cantidad": 1}], "Efectivo")
    assert registros(r) == []


# La reposición por venta

def test_reponer_la_venta_devuelve_las_unidades_y_borra_el_registro(datos_provistos, r):
    antes = snapshots.redis_snap()
    stock.descontar_fefo("S001", PEDIDO, id_venta="V900")
    assert stock.reponer_venta("V900") is True
    assert snapshots.redis_snap() == antes
    assert (unidades(r, "L005"), unidades(r, "L015")) == (40, 100)
    assert r.zscore(claves.UNIDADES, "L005") == 40


def test_reponer_la_venta_dos_veces_repone_una_sola(datos_provistos):
    antes = snapshots.redis_snap()
    stock.descontar_fefo("S001", PEDIDO, id_venta="V900")
    stock.reponer_venta("V900")
    assert stock.reponer_venta("V900") is False
    assert snapshots.redis_snap() == antes


def test_reponer_una_venta_sin_registro_no_cambia_nada(datos_provistos):
    antes = snapshots.redis_snap()
    assert stock.reponer_venta("V900") is False
    assert snapshots.redis_snap() == antes


def test_no_repone_si_otra_llamada_recibio_los_consumos(datos_provistos, r):
    stock.descontar_fefo("S001", PEDIDO, id_venta="V900")
    stock.descontar_fefo("S001", PEDIDO, id_venta="V900")
    antes = snapshots.redis_snap()
    assert stock.reponer_venta("V900") is False
    assert snapshots.redis_snap() == antes
    assert unidades(r, "L005") == 0


def test_falla_despues_del_script_repone_por_el_registro(datos_provistos, monkeypatch):
    antes = snapshots.redis_snap()
    original = redis.client.Pipeline.execute

    def ejecutar(self, *args, **kwargs):
        if not self.transaction:
            raise redis.ConnectionError("conexión perdida al leer los lotes")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(redis.client.Pipeline, "execute", ejecutar)
    with pytest.raises(redis.ConnectionError):
        stock.descontar_fefo("S001", PEDIDO, id_venta="V900")
    monkeypatch.setattr(redis.client.Pipeline, "execute", original)
    assert snapshots.redis_snap() == antes


# El script valida sus argumentos antes de escribir

def script(r):
    return r.register_script(LUA.read_text(encoding="utf-8"))


def hoy():
    return fechas.a_entero(fechas.hoy())


@pytest.mark.parametrize("cantidad", ["-5", "0", "6.5", "nan", "inf", "1e3", " 5", "0x10", "", "2147483648"])
def test_el_script_rechaza_una_cantidad_invalida_sin_escribir(datos_provistos, r, cantidad):
    antes = snapshots.redis_snap()
    with pytest.raises(redis.ResponseError) as e:
        script(r)(keys=["stock:S001:PRD001", "stock:S001:PRD003"], args=[hoy(), 1, cantidad], client=r)
    assert "ARGUMENTOS_INVALIDOS" in str(e.value)
    assert snapshots.redis_snap() == antes


@pytest.mark.parametrize("claves_lua,argumentos", [
    (["stock:S001:PRD003", "stock:S001:PRD003"], [20261103, 30, 30]),
    (["stock:S001:PRD003", "stock:S001:PRD001"], [20261103, 30]),
    (["stock:S001:PRD003"], [20261103, 30, 1]),
    (["stock:S001:PRD003"], [20261103]),
    (["stock:S001:PRD003"], []),
    (["stock:S001:PRD003"], ["2026-11-03", 30]),
    (["stock:S001:PRD003", "otra:V900"], [20261103, 30]),
], ids=["clave-repetida", "falta-una-cantidad", "sobra-una-cantidad", "sin-cantidades", "sin-fecha",
        "fecha-con-guiones", "registro-con-otro-prefijo"])
def test_el_script_rechaza_argumentos_mal_formados_sin_escribir(datos_provistos, r, claves_lua, argumentos):
    antes = snapshots.redis_snap()
    with pytest.raises(redis.ResponseError) as e:
        script(r)(keys=claves_lua, args=argumentos, client=r)
    assert "ARGUMENTOS_INVALIDOS" in str(e.value)
    assert snapshots.redis_snap() == antes
