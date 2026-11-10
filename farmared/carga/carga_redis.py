import datetime

from farmared import claves, conexiones, fechas
from farmared.errores import ValidacionError

CAMPOS = ("id_producto", "id_sucursal", "nro_lote", "unidades", "vencimiento")


def preparar(lotes):
    """Arma todo lo que se escribe; si algo falla, falla antes de borrar nada."""
    preparados = []
    for l in lotes:
        mapping = {k: l[k] for k in CAMPOS}
        if l["id_lote"] is None or None in mapping.values():
            raise ValidacionError("DATO_INVALIDO", f"lote {l['id_lote']}: valor vacío")
        puntaje = fechas.a_entero(datetime.date.fromisoformat(l["vencimiento"]))
        preparados.append((l["id_lote"], claves.lote(l["id_lote"]), mapping,
                           claves.stock(l["id_sucursal"], l["id_producto"]), puntaje, float(l["unidades"])))
    return preparados


def cargar_redis(preparados):
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
    r.unlink(claves.UNIDADES)
    p = r.pipeline(transaction=True)
    for id_lote, clave, mapping, stock, puntaje, unidades in preparados:
        p.hset(clave, mapping=mapping)
        p.zadd(stock, {id_lote: puntaje})
        p.zadd(claves.UNIDADES, {id_lote: unidades})
    p.execute()
    return {"lotes": len(preparados)}
