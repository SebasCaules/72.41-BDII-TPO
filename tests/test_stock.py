import datetime
import threading

import pytest
import redis

import snapshots
from farmared import claves, fechas, stock
from farmared.errores import StockInsuficiente, ValidacionError

HILOS = 20
UNIDADES_DEL_LOTE = 10


def unidades(r, id_lote):
    return int(r.hget(claves.lote(id_lote), "unidades"))


def indice(r, id_lote):
    return r.zscore(claves.UNIDADES, id_lote)


def item(id_producto, cantidad):
    return {"id_producto": id_producto, "cantidad": cantidad}


def fijar_unidades(r, id_lote, n):
    r.hset(claves.lote(id_lote), "unidades", n)
    r.zadd(claves.UNIDADES, {id_lote: n})


def test_fefo_consume_primero_el_lote_que_vence_antes(datos_provistos, r):
    consumos = stock.descontar_fefo("S001", [item("PRD003", 42)])
    assert consumos == [{"id_lote": "L005", "id_producto": "PRD003", "unidades": 40},
                        {"id_lote": "L015", "id_producto": "PRD003", "unidades": 2}]
    assert (unidades(r, "L005"), unidades(r, "L015")) == (0, 98)
    assert (indice(r, "L005"), indice(r, "L015")) == (0, 98)


def test_reponer_devuelve_las_unidades_y_restaura_el_snapshot(datos_provistos, r):
    antes = snapshots.redis_snap()
    consumos = stock.descontar_fefo("S001", [item("PRD003", 42)])
    assert snapshots.redis_snap() != antes
    stock.reponer(consumos)
    assert (unidades(r, "L005"), unidades(r, "L015")) == (40, 100)
    assert (indice(r, "L005"), indice(r, "L015")) == (40, 100)
    assert snapshots.redis_snap() == antes


def test_reponer_sin_consumos_no_cambia_nada(datos_provistos):
    antes = snapshots.redis_snap()
    stock.reponer([])
    assert snapshots.redis_snap() == antes


def test_lote_vencido_no_se_dispensa(datos_provistos, r):
    antes = snapshots.redis_snap()
    with pytest.raises(StockInsuficiente) as e:
        stock.descontar_fefo("S002", [item("PRD010", 1)])
    assert (e.value.codigo, e.value.id_producto, e.value.requerido, e.value.disponible) == (
        "STOCK_INSUFICIENTE", "PRD010", 1, 0)
    assert unidades(r, "L012") == 30
    assert snapshots.redis_snap() == antes


def test_el_lote_que_vence_hoy_se_dispensa(datos_provistos, monkeypatch, r):
    # la carga valida fechas con la de referencia; "hoy" se mueve recién después
    monkeypatch.setattr(fechas, "hoy", lambda: datetime.date(2026, 10, 31))
    consumos = stock.descontar_fefo("S002", [item("PRD010", 1)])
    assert consumos == [{"id_lote": "L012", "id_producto": "PRD010", "unidades": 1}]
    assert unidades(r, "L012") == 29


@pytest.mark.parametrize("hoy,lotes", [
    (datetime.date(2026, 11, 30), [("L005", 5)]),
    (datetime.date(2026, 12, 1), [("L015", 5)]),
])
def test_borde_de_vencimiento_del_primer_lote(datos_provistos, monkeypatch, hoy, lotes):
    monkeypatch.setattr(fechas, "hoy", lambda: hoy)
    consumos = stock.descontar_fefo("S001", [item("PRD003", 5)])
    assert [(c["id_lote"], c["unidades"]) for c in consumos] == lotes


def test_lote_agotado_se_saltea(datos_provistos, r):
    fijar_unidades(r, "L005", 0)
    consumos = stock.descontar_fefo("S001", [item("PRD003", 5)])
    assert consumos == [{"id_lote": "L015", "id_producto": "PRD003", "unidades": 5}]
    assert (unidades(r, "L005"), unidades(r, "L015")) == (0, 95)


def test_todo_o_nada_si_un_item_no_alcanza(datos_provistos, r):
    antes = snapshots.redis_snap()
    with pytest.raises(StockInsuficiente) as e:
        stock.descontar_fefo("S001", [item("PRD001", 5), item("PRD003", 141)])
    assert (e.value.id_producto, e.value.requerido, e.value.disponible) == ("PRD003", 141, 140)
    assert unidades(r, "L001") == 120
    assert snapshots.redis_snap() == antes


def test_todo_o_nada_si_falla_el_primer_item(datos_provistos):
    antes = snapshots.redis_snap()
    with pytest.raises(StockInsuficiente) as e:
        stock.descontar_fefo("S001", [item("PRD003", 141), item("PRD001", 5)])
    assert (e.value.id_producto, e.value.requerido, e.value.disponible) == ("PRD003", 141, 140)
    assert snapshots.redis_snap() == antes


def test_justo_todo_el_stock_vigente_alcanza(datos_provistos, r):
    consumos = stock.descontar_fefo("S001", [item("PRD003", 140)])
    assert [(c["id_lote"], c["unidades"]) for c in consumos] == [("L005", 40), ("L015", 100)]
    assert (unidades(r, "L005"), unidades(r, "L015")) == (0, 0)


def test_items_del_mismo_producto_se_agrupan(datos_provistos, r):
    consumos = stock.descontar_fefo("S001", [item("PRD003", 30), item("PRD001", 1), item("PRD003", 12)])
    assert consumos == [{"id_lote": "L005", "id_producto": "PRD003", "unidades": 40},
                        {"id_lote": "L015", "id_producto": "PRD003", "unidades": 2},
                        {"id_lote": "L001", "id_producto": "PRD001", "unidades": 1}]
    assert (unidades(r, "L005"), unidades(r, "L015"), unidades(r, "L001")) == (0, 98, 119)


def test_el_agrupado_cuenta_el_total_para_rechazar(datos_provistos):
    # cada ítem por separado alcanza (100 y 40 de 140), juntos no
    antes = snapshots.redis_snap()
    with pytest.raises(StockInsuficiente) as e:
        stock.descontar_fefo("S001", [item("PRD003", 100), item("PRD003", 41)])
    assert (e.value.id_producto, e.value.requerido, e.value.disponible) == ("PRD003", 141, 140)
    assert snapshots.redis_snap() == antes


def test_solo_consume_lotes_de_la_sucursal_pedida(datos_provistos, r):
    consumos = stock.descontar_fefo("S002", [item("PRD001", 3)])
    assert consumos == [{"id_lote": "L002", "id_producto": "PRD001", "unidades": 3}]
    assert (unidades(r, "L001"), unidades(r, "L002"), unidades(r, "L016")) == (120, 32, 4000)


def test_producto_sin_lotes_en_la_sucursal(datos_provistos):
    antes = snapshots.redis_snap()
    with pytest.raises(StockInsuficiente) as e:
        stock.descontar_fefo("S003", [item("PRD002", 1)])
    assert (e.value.id_producto, e.value.requerido, e.value.disponible) == ("PRD002", 1, 0)
    assert snapshots.redis_snap() == antes


@pytest.mark.parametrize("cantidad", [0, -1, True, 1.0, "2", None, 2**31])
def test_cantidad_invalida_no_toca_redis(datos_provistos, cantidad):
    antes = snapshots.redis_snap()
    with pytest.raises(ValidacionError) as e:
        stock.descontar_fefo("S001", [item("PRD001", 1), item("PRD003", cantidad)])
    assert e.value.codigo == "CANTIDAD_INVALIDA"
    assert snapshots.redis_snap() == antes


def test_veinte_hilos_sobre_un_lote_de_diez(datos_provistos, r):
    fijar_unidades(r, "L001", UNIDADES_DEL_LOTE)
    barrera = threading.Barrier(HILOS)
    exitos, rechazos, otros = [], [], []

    def comprar():
        barrera.wait()
        try:
            exitos.append(stock.descontar_fefo("S001", [item("PRD001", 1)]))
        except StockInsuficiente as e:
            rechazos.append(e)
        except Exception as e:
            otros.append(e)

    hilos = [threading.Thread(target=comprar) for _ in range(HILOS)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert otros == []
    assert (len(exitos), len(rechazos)) == (10, 10)
    assert all(c == [{"id_lote": "L001", "id_producto": "PRD001", "unidades": 1}] for c in exitos)
    assert all((e.requerido, e.disponible) == (1, 0) for e in rechazos)
    assert unidades(r, "L001") == 0
    assert indice(r, "L001") == 0


def test_el_conteo_por_unidades_sigue_al_lote(datos_provistos, r):
    stock.descontar_fefo("S001", [item("PRD003", 42), item("PRD001", 7)])
    for id_lote in ("L001", "L005", "L015"):
        assert indice(r, id_lote) == unidades(r, id_lote)


def test_falla_despues_del_script_repone_las_unidades(datos_provistos, monkeypatch):
    antes = snapshots.redis_snap()
    original = redis.client.Pipeline.execute

    def ejecutar(self, *args, **kwargs):
        if not self.transaction:
            raise redis.ConnectionError("conexión perdida al leer los lotes")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(redis.client.Pipeline, "execute", ejecutar)
    with pytest.raises(redis.ConnectionError):
        stock.descontar_fefo("S001", [item("PRD003", 42)])
    monkeypatch.setattr(redis.client.Pipeline, "execute", original)
    assert snapshots.redis_snap() == antes
