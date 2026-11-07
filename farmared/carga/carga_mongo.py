import re
from collections import defaultdict

from pymongo import IndexModel

from farmared import conexiones

COLECCIONES = {"clientes": "id_cliente", "sucursales": "id_sucursal", "farmaceuticos": "id_farmaceutico",
               "proveedores": "id_proveedor", "productos": "id_producto", "recetas": "id_receta",
               "ventas": "id_venta"}
INDICES = {
    "clientes": [([("dni", 1)], {"unique": True})],
    "farmaceuticos": [([("matricula", 1)], {"unique": True})],
    "proveedores": [([("cuit", 1)], {"unique": True})],
    "ventas": [([("id_cliente", 1), ("fecha", 1)], {}), ([("id_farmaceutico", 1), ("fecha", 1)], {}),
               ([("fecha", 1)], {})],
    "recetas": [([("id_cliente", 1), ("fecha_emision", 1)], {}),
                ([("tipo", 1), ("estado", 1), ("proxima_dispensa", 1)], {})],
}


def _sufijo(id_):
    return int(re.search(r"(\d+)$", id_).group(1))


def documentos(filas):
    docs = {col: [{"_id": f[pk], **{k: v for k, v in f.items() if k != pk}} for f in filas[col]]
            for col, pk in COLECCIONES.items()}
    detalle = defaultdict(list)
    for d in sorted(filas["detalle_ventas"], key=lambda d: d["id_detalle"]):
        detalle[d["id_venta"]].append({k: d[k] for k in ("id_detalle", "id_producto", "cantidad", "precio_unit")})
    for v in docs["ventas"]:
        v["items"] = detalle[v["_id"]]
        v["stock_descontado"] = v["estado"] == "Completada"
    docs["contadores"] = [
        {"_id": "clientes", "ultimo": max(_sufijo(c["_id"]) for c in docs["clientes"])},
        {"_id": "ventas", "ultimo": max(_sufijo(v["_id"]) for v in docs["ventas"])},
        {"_id": "detalle_ventas", "ultimo": max(_sufijo(d["id_detalle"]) for d in filas["detalle_ventas"])},
    ]
    return docs


def cargar_mongo(filas):
    db = conexiones.get_db()
    conteos = {}
    for col, lista in documentos(filas).items():
        db.drop_collection(col)
        modelos = [IndexModel(k, **o) for k, o in INDICES.get(col, [])]
        if modelos:
            db[col].create_indexes(modelos)
        db[col].insert_many(lista)
        conteos[col] = len(lista)
    return conteos
