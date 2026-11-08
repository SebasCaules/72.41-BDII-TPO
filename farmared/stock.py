from pathlib import Path

from farmared import claves, conexiones, fechas
from farmared.errores import StockInsuficiente, ValidacionError

_LUA = (Path(__file__).parent / "lua" / "descontar_fefo.lua").read_text(encoding="utf-8")
_script = None


def _fefo():
    global _script
    if _script is None:
        _script = conexiones.get_redis().register_script(_LUA)
    return _script


def descontar_fefo(id_sucursal, items):
    pedido = {}
    for it in items:
        cantidad = it["cantidad"]
        if type(cantidad) is not int or not 0 < cantidad < 2**31:
            raise ValidacionError("CANTIDAD_INVALIDA", f"cantidad inválida para {it['id_producto']}")
        pedido[it["id_producto"]] = pedido.get(it["id_producto"], 0) + cantidad
    productos = list(pedido)
    r = conexiones.get_redis()
    res = _fefo()(keys=[claves.stock(id_sucursal, p) for p in productos],
                  args=[fechas.a_entero(fechas.hoy())] + [pedido[p] for p in productos],
                  client=r)
    if res[0] == "FALTA":
        p = productos[int(res[1]) - 1]
        raise StockInsuficiente(p, pedido[p], int(res[2]))
    pares = list(zip(res[1::2], res[2::2]))
    # el Lua no devuelve el producto de cada lote; el campo no cambia nunca, se puede leer después
    pipe = r.pipeline(transaction=False)
    for id_lote, _ in pares:
        pipe.hget(claves.lote(id_lote), "id_producto")
    try:
        productos_de_lote = pipe.execute()
    except Exception:
        # el script ya descontó y todavía no se devolvió nada: compensa quien descontó
        reponer([{"id_lote": l, "unidades": int(n)} for l, n in pares])
        raise
    return [{"id_lote": l, "id_producto": p, "unidades": int(n)}
            for (l, n), p in zip(pares, productos_de_lote)]


def reponer(consumos):
    pipe = conexiones.get_redis().pipeline(transaction=True)
    for c in consumos:
        pipe.hincrby(claves.lote(c["id_lote"]), "unidades", c["unidades"])
        pipe.zincrby(claves.UNIDADES, c["unidades"], c["id_lote"])
    pipe.execute()
