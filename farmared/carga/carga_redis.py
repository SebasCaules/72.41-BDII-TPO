import datetime

from farmared import claves, conexiones, fechas


def cargar_redis(lotes):
    r = conexiones.get_redis()
    for patron in claves.PATRONES:
        tanda = []
        for k in r.scan_iter(match=patron, count=500):
            tanda.append(k)
            if len(tanda) == 500:
                r.unlink(*tanda)
                tanda = []
        if tanda:
            r.unlink(*tanda)
    r.unlink(claves.UNIDADES, claves.LOTES)
    p = r.pipeline(transaction=True)
    for l in lotes:
        venc = datetime.date.fromisoformat(l["vencimiento"])
        p.hset(claves.lote(l["id_lote"]), mapping={
            "id_producto": l["id_producto"], "id_sucursal": l["id_sucursal"],
            "nro_lote": l["nro_lote"], "unidades": l["unidades"], "vencimiento": l["vencimiento"]})
        p.zadd(claves.stock(l["id_sucursal"], l["id_producto"]), {l["id_lote"]: fechas.a_entero(venc)})
        p.zadd(claves.UNIDADES, {l["id_lote"]: l["unidades"]})
        p.sadd(claves.LOTES, l["id_lote"])
    p.execute()
    return {"lotes": len(lotes)}
