UNIDADES = "lotes:unidades"
LOTES = "lotes"
PATRONES = ("lote:*", "stock:*", "descuento:*")


def lote(id_lote):
    return f"lote:{id_lote}"


def stock(id_sucursal, id_producto):
    return f"stock:{id_sucursal}:{id_producto}"


def descuento(id_venta):
    return f"descuento:{id_venta}"
