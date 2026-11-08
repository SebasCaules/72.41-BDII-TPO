import sys

from farmared import carga, claves, conexiones, fechas, formato, ids
from farmared.consultas import q13_abm_clientes, q14_registrar_venta, q15_descontar_stock
from farmared.demo import escribir, ordenar
from farmared.errores import FarmaRedError

ALTA = {"nombre": "Valeria", "apellido": "Quiroga", "dni": "99300400", "email": "valeria.quiroga@gmail.com",
        "telefono": "1162004400", "ciudad": "La Plata", "provincia": "Buenos Aires", "obra_social": "IOMA",
        "nro_afiliado": "IO-993004"}
CAMBIOS = {"email": "vquiroga@hotmail.com", "telefono": "1162004499", "obra_social": "OSDE",
           "nro_afiliado": "OS-993004"}
VENTAS = (
    ("venta con receta de tratamiento prolongado (última dispensa)",
     {"id_cliente": "C003", "id_farmaceutico": "F006", "items": [{"id_producto": "PRD004", "cantidad": 1}],
      "medio_pago": "Obra social", "id_receta": "RC002"}),
    ("venta con receta de tratamiento prolongado (dispensa intermedia)",
     {"id_cliente": "C006", "id_farmaceutico": "F001", "items": [{"id_producto": "PRD003", "cantidad": 1}],
      "medio_pago": "Obra social", "id_receta": "RC004"}),
    ("rechazo por cliente inactivo",
     {"id_cliente": "C008", "id_farmaceutico": "F001", "items": [{"id_producto": "PRD001", "cantidad": 1}],
      "medio_pago": "Efectivo", "id_receta": None}),
    ("rechazo por stock: el único lote del producto en la sucursal está vencido",
     {"id_cliente": "C007", "id_farmaceutico": "F003", "items": [{"id_producto": "PRD010", "cantidad": 1}],
      "medio_pago": "Débito", "id_receta": "RC006"}),
)
VENTA = ("id_venta", "id_cliente", "id_farmaceutico", "id_receta", "fecha", "tipo", "medio_pago", "total", "estado",
         "items", "stock_descontado", "consumos")
CLIENTE = ("id_cliente", "nombre", "apellido", "obra_social", "activo")
RECETA = ("id_receta", "id_cliente", "tipo", "estado", "dispensas_autorizadas", "dispensas_realizadas",
          "proxima_dispensa")


def _documento(coleccion, id_, orden, campos=None):
    doc = conexiones.get_db()[coleccion].find_one({"_id": id_}, campos)
    if doc is None:
        return None
    return ordenar(formato.a_json({orden[0]: doc["_id"], **doc}), orden)


def _contadores():
    return {c["_id"]: c["ultimo"] for c in conexiones.get_db().contadores.find(sort=[("_id", 1)])}


def _lotes(id_sucursal, productos):
    r = conexiones.get_redis()
    lotes = []
    for id_producto in sorted(set(productos)):
        for id_lote in r.zrange(claves.stock(id_sucursal, id_producto), 0, -1):
            lote = r.hgetall(claves.lote(id_lote))
            lotes.append({"id_lote": id_lote, "id_producto": id_producto, "unidades": int(lote["unidades"]),
                          "vencimiento": lote["vencimiento"]})
    return lotes


def _sucursal(id_farmaceutico):
    return conexiones.get_db().farmaceuticos.find_one({"_id": id_farmaceutico})["id_sucursal"]


def _escenario(nombre, estado, operacion):
    antes = estado()
    try:
        salida = {"resultado": operacion()}
    except FarmaRedError as e:
        salida = {"error": {"codigo": e.codigo, "mensaje": e.mensaje}}
    return {"escenario": nombre, "antes": antes, "despues": estado(), **salida}


def _q13():
    def estado():
        db = conexiones.get_db()
        clientes = [formato.a_json({"id_cliente": c["_id"], **c})
                    for c in db.clientes.find({"dni": ALTA["dni"]}, sort=[("_id", 1)])]
        return {"clientes_con_dni": clientes, "contadores": {"clientes": _contadores()["clientes"]}}

    alta = _escenario("alta", estado, lambda: q13_abm_clientes.alta_cliente(ALTA))
    id_cliente = alta["resultado"]["id_cliente"]
    repetido = {**ALTA, "nombre": "Valentina", "email": "valentina.quiroga@gmail.com"}
    parametros = {"alta": ALTA,
                  "modificación de contacto y cobertura": {"id_cliente": id_cliente, "cambios": CAMBIOS},
                  "baja lógica": {"id_cliente": id_cliente},
                  "rechazo por DNI repetido, el del cliente recién dado de baja": repetido}
    escenarios = [
        alta,
        _escenario("modificación de contacto y cobertura", estado,
                   lambda: q13_abm_clientes.modificar_cliente(id_cliente, CAMBIOS)),
        _escenario("baja lógica", estado, lambda: q13_abm_clientes.baja_cliente(id_cliente)),
        _escenario("rechazo por DNI repetido, el del cliente recién dado de baja", estado,
                   lambda: q13_abm_clientes.alta_cliente(repetido)),
    ]
    return parametros, escenarios


def _q14():
    parametros, escenarios = {}, []
    for nombre, venta in VENTAS:
        id_previsto = f"V{_contadores()['ventas'] + 1:03d}"
        sucursal = _sucursal(venta["id_farmaceutico"])

        def estado(venta=venta, id_previsto=id_previsto, sucursal=sucursal):
            receta = venta["id_receta"] and _documento("recetas", venta["id_receta"], RECETA)
            return {"cliente": _documento("clientes", venta["id_cliente"], CLIENTE, list(CLIENTE[1:])),
                    "receta": receta,
                    "lotes": _lotes(sucursal, [it["id_producto"] for it in venta["items"]]),
                    "contadores": {k: v for k, v in _contadores().items() if k != "clientes"},
                    "venta_nueva": _documento("ventas", id_previsto, VENTA)}

        parametros[nombre] = venta
        escenarios.append(_escenario(nombre, estado,
                                     lambda venta=venta: q14_registrar_venta.registrar_venta(**venta)))
    return parametros, escenarios


def _q15():
    db = conexiones.get_db()
    producto = db.productos.find_one({"_id": "PRD002"})
    id_venta = ids.siguiente_id("ventas", "V")
    item = {"id_detalle": ids.siguiente_id("detalle_ventas", "D"), "id_producto": "PRD002", "cantidad": 1,
            "precio_unit": producto["precio_unit"]}
    insertada = {"_id": id_venta, "id_cliente": "C005", "id_farmaceutico": "F001", "id_receta": None,
                 "fecha": fechas.a_datetime(fechas.hoy()), "tipo": "Venta libre", "medio_pago": "Efectivo",
                 "total": item["precio_unit"], "estado": "Completada", "items": [item], "stock_descontado": False}
    db.ventas.insert_one(insertada)

    def estado_de(id_):
        def estado():
            venta = db.ventas.find_one({"_id": id_})
            productos = [it["id_producto"] for it in venta["items"]]
            return {"venta": _documento("ventas", id_, ("id_venta", "estado", "stock_descontado", "consumos"),
                                        ["estado", "stock_descontado", "consumos"]),
                    "lotes": _lotes(_sucursal(venta["id_farmaceutico"]), productos)}
        return estado

    nombres = ("venta importada sin descuento", "rechazo por descuento repetido sobre la misma venta",
               "rechazo por venta pendiente")
    parametros = {nombres[0]: {"id_venta": id_venta,
                               "venta_insertada": ordenar(formato.a_json({"id_venta": id_venta, **insertada}), VENTA)},
                  nombres[1]: {"id_venta": id_venta},
                  nombres[2]: {"id_venta": "V012"}}
    escenarios = [_escenario(nombre, estado_de(p["id_venta"]),
                             lambda p=p: q15_descontar_stock.descontar_stock_venta(p["id_venta"]))
                  for nombre, p in parametros.items()]
    return parametros, escenarios


def ejecutar(destino):
    """Recarga los datos completos y escribe los escenarios de los servicios, con el estado antes y después.

    Parámetros:
        destino: carpeta donde se escriben q13.json, q14.json y q15.json.
    Retorna:
        Lista con las rutas escritas.
    Motor: MongoDB y Redis.
    Errores: ValidacionError si los datos a cargar no son válidos.
    """
    carga.cargar()
    escritas = []
    for nombre, servicio in (("q13", _q13), ("q14", _q14), ("q15", _q15)):
        try:
            parametros, escenarios = servicio()
        except NotImplementedError:
            print(f"{nombre}: sin implementar", file=sys.stderr)
            continue
        escritas.append(escribir(destino, nombre, parametros, escenarios))
    return escritas
