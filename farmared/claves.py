UNIDADES = "lotes:unidades"
LOTES = "lotes"
PATRONES = ("lote:*", "stock:*")


def lote(id_lote):
    return f"lote:{id_lote}"


def stock(id_sucursal, id_producto):
    return f"stock:{id_sucursal}:{id_producto}"
