from farmared import claves, conexiones


def redis_snap():
    r = conexiones.get_redis()
    estado = {}
    for patron in (*claves.PATRONES, claves.UNIDADES):
        for k in r.scan_iter(match=patron):
            t = r.type(k)
            estado[k] = (r.hgetall(k) if t == "hash" else r.zrange(k, 0, -1, withscores=True) if t == "zset"
                         else r.get(k))
    return estado


def mongo_snap():
    db = conexiones.get_db()
    estado = {}
    for nombre in sorted(db.list_collection_names(filter={"type": "collection"})):
        if nombre.startswith("system."):
            continue
        estado[nombre] = list(db[nombre].find(sort=[("_id", 1)]))
        estado[nombre + "#indices"] = sorted((i["name"], i.get("unique", False))
                                             for i in db[nombre].list_indexes())
    return estado
