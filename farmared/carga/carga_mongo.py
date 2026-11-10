import re
from collections import Counter, defaultdict

import bson
from bson.errors import InvalidDocument
from pymongo import IndexModel

from farmared import conexiones
from farmared.consultas import q11_ingresos_mes_actual
from farmared.errores import ValidacionError

MAXIMO_BSON = 16 * 1024 * 1024   # el mayor documento que acepta MongoDB

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
    # Sin filas, el contador queda en 0 y el primer id nuevo es el 001.
    docs["contadores"] = [
        {"_id": "clientes", "ultimo": max((_sufijo(c["_id"]) for c in docs["clientes"]), default=0)},
        {"_id": "ventas", "ultimo": max((_sufijo(v["_id"]) for v in docs["ventas"]), default=0)},
        {"_id": "detalle_ventas",
         "ultimo": max((_sufijo(d["id_detalle"]) for d in filas["detalle_ventas"]), default=0)},
    ]
    return _comprobar(docs)


def _comprobar(docs):
    """Falla antes de borrar nada si algún documento no entraría en su colección."""
    for col, lista in docs.items():
        for campos in [("_id",)] + [tuple(c for c, _ in k) for k, o in INDICES.get(col, []) if o.get("unique")]:
            repetidos = [v for v, n in Counter(tuple(d.get(c) for c in campos) for d in lista).items() if n > 1]
            if repetidos:
                raise ValidacionError("DATO_INVALIDO", f"{col}: {', '.join(campos)} repetido {repetidos[0]}")
        for d in lista:
            try:
                largo = len(bson.encode(d))
            except (OverflowError, InvalidDocument) as e:
                raise ValidacionError("DATO_INVALIDO", f"{col} {d.get('_id')}: {e}") from e
            if largo > MAXIMO_BSON:
                raise ValidacionError("DATO_INVALIDO",
                                      f"{col} {d.get('_id')}: documento de {largo} bytes, más que el máximo de 16 MiB")
    return docs


def cargar_mongo(docs):
    db = conexiones.get_db()
    conteos = {}
    for col, lista in docs.items():
        db.drop_collection(col)
        modelos = [IndexModel(k, **o) for k, o in INDICES.get(col, [])]
        if modelos:
            db[col].create_indexes(modelos)
        if lista:   # insert_many no acepta una lista vacía
            db[col].insert_many(lista)
        conteos[col] = len(lista)
    q11_ingresos_mes_actual.crear_vista()
    return conteos
