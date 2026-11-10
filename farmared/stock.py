from pathlib import Path

from farmared import claves, conexiones, fechas
from farmared.errores import StockInsuficiente, ValidacionError

_LUA = {nombre: (Path(__file__).parent / "lua" / f"{nombre}.lua").read_text(encoding="utf-8")
        for nombre in ("descontar_fefo", "reponer_venta")}
_scripts = {}


def _script(nombre):
    if nombre not in _scripts:
        _scripts[nombre] = conexiones.get_redis().register_script(_LUA[nombre])
    return _scripts[nombre]


def descontar_fefo(id_sucursal, items, id_venta=None):
    """Descuenta las unidades pedidas de los lotes vigentes de la sucursal, por vencimiento y todo o nada.

    Parámetros:
        id_sucursal: sucursal cuyos lotes se consumen.
        items: lista de {id_producto, cantidad}; los del mismo producto se suman.
        id_venta: venta a la que corresponde el descuento. Si se indica, el script deja el registro
            descuento:{id_venta} en el mismo paso en que descuenta, y una nueva llamada con la misma venta
            no descuenta otra vez: devuelve los consumos registrados.
    Retorna:
        Lista de consumos {id_lote, id_producto, unidades}, en el orden en que se tomaron.
    Motor: Redis (script Lua).
    Errores: ValidacionError (CANTIDAD_INVALIDA), StockInsuficiente.
    """
    pedido = {}
    for it in items:
        cantidad = it["cantidad"]
        if type(cantidad) is not int or not 0 < cantidad < 2**31:
            raise ValidacionError("CANTIDAD_INVALIDA", f"cantidad inválida para {it['id_producto']}")
        pedido[it["id_producto"]] = pedido.get(it["id_producto"], 0) + cantidad
    productos = list(pedido)
    claves_lua = [claves.stock(id_sucursal, p) for p in productos]
    if id_venta is not None:
        claves_lua.append(claves.descuento(id_venta))
    r = conexiones.get_redis()
    res = _script("descontar_fefo")(keys=claves_lua,
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
    except BaseException:
        # el script ya descontó y todavía no se devolvió nada: compensa quien descontó
        if id_venta is None:
            reponer([{"id_lote": l, "unidades": int(n)} for l, n in pares])
        else:
            reponer_venta(id_venta)
        raise
    return [{"id_lote": l, "id_producto": p, "unidades": int(n)}
            for (l, n), p in zip(pares, productos_de_lote)]


def reponer(consumos):
    pipe = conexiones.get_redis().pipeline(transaction=True)
    for c in consumos:
        pipe.hincrby(claves.lote(c["id_lote"]), "unidades", c["unidades"])
        pipe.zincrby(claves.UNIDADES, c["unidades"], c["id_lote"])
    pipe.execute()


def reponer_venta(id_venta):
    """Deshace el descuento registrado de una venta y borra su registro, en un solo paso atómico.

    No hace nada si la venta no tiene registro, o si sus consumos los recibió más de una llamada:
    cualquiera de ellas puede marcar la venta todavía. Repetirla no repone dos veces.

    Parámetros:
        id_venta: venta cuyo descuento se deshace.
    Retorna:
        True si repuso; False si no había nada que reponer.
    Motor: Redis (script Lua).
    Errores: los de conexión de Redis.
    """
    r = conexiones.get_redis()
    return _script("reponer_venta")(keys=[claves.descuento(id_venta)], client=r) == 1
