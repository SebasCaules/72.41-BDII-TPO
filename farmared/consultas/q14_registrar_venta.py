import datetime
import random
import time

from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

from farmared import conexiones, fechas, formato, ids, stock
from farmared.consultas.q15_descontar_stock import descontar_stock_venta
from farmared.dominio import CONDICIONES_CON_RECETA, MEDIOS_DE_PAGO, validar_id
from farmared.errores import NoEncontrado, ValidacionError

INTENTOS = 5


def _validar(db, s, id_cliente, id_farmaceutico, items, medio_pago, id_receta):
    if not items:
        raise ValidacionError("ITEMS_VACIOS", "la venta no tiene ítems")
    for it in items:
        if type(it.get("cantidad")) is not int or not 0 < it["cantidad"] < 2**31:
            raise ValidacionError("CANTIDAD_INVALIDA", f"cantidad inválida para {it.get('id_producto')}")
        validar_id("id_producto", it.get("id_producto"))
    validar_id("id_cliente", id_cliente)
    validar_id("id_farmaceutico", id_farmaceutico)
    if id_receta is not None:
        validar_id("id_receta", id_receta)
    cliente = db.clientes.find_one({"_id": id_cliente}, session=s)
    if cliente is None:
        raise NoEncontrado("CLIENTE_INEXISTENTE", f"no existe el cliente {id_cliente}")
    if not cliente["activo"]:
        raise ValidacionError("CLIENTE_INACTIVO", f"el cliente {id_cliente} está dado de baja")
    farmaceutico = db.farmaceuticos.find_one({"_id": id_farmaceutico}, session=s)
    if farmaceutico is None:
        raise NoEncontrado("FARMACEUTICO_INEXISTENTE", f"no existe el farmacéutico {id_farmaceutico}")
    if not farmaceutico["activo"]:
        raise ValidacionError("FARMACEUTICO_INACTIVO", f"el farmacéutico {id_farmaceutico} está inactivo")
    sucursal = db.sucursales.find_one({"_id": farmaceutico["id_sucursal"]}, session=s)
    if sucursal is None:
        raise NoEncontrado("SUCURSAL_INEXISTENTE", f"no existe la sucursal {farmaceutico['id_sucursal']}")
    if sucursal["tipo"] != "Farmacia":
        raise ValidacionError("SUCURSAL_NO_FARMACIA", f"{sucursal['nombre']} no vende al público")
    if not sucursal["activo"]:
        raise ValidacionError("SUCURSAL_INACTIVA", f"{sucursal['nombre']} está inactiva")
    pedidos = sorted({it["id_producto"] for it in items})
    productos = {p["_id"]: p for p in db.productos.find({"_id": {"$in": pedidos}}, session=s)}
    for id_producto in pedidos:
        if id_producto not in productos:
            raise NoEncontrado("PRODUCTO_INEXISTENTE", f"no existe el producto {id_producto}")
        if not productos[id_producto]["activo"]:
            raise ValidacionError("PRODUCTO_INACTIVO", f"el producto {id_producto} está discontinuado")
    if medio_pago not in MEDIOS_DE_PAGO:
        raise ValidacionError("MEDIO_PAGO_INVALIDO", f"medio de pago inválido: {medio_pago}")
    if medio_pago == "Obra social" and cliente["obra_social"] == "Sin cobertura":
        raise ValidacionError("OBRA_SOCIAL_SIN_COBERTURA", f"el cliente {id_cliente} no tiene cobertura")
    receta = None
    if id_receta is not None:
        receta = db.recetas.find_one({"_id": id_receta}, session=s)
        if receta is None:
            raise NoEncontrado("RECETA_INEXISTENTE", f"no existe la receta {id_receta}")
        if receta["id_cliente"] != id_cliente:
            raise ValidacionError("RECETA_OTRO_CLIENTE", f"la receta {id_receta} es de otro cliente")
        if receta["estado"] != "Vigente":
            raise ValidacionError("RECETA_NO_VIGENTE", f"la receta {id_receta} está {receta['estado']}")
        if receta["dispensas_realizadas"] >= receta["dispensas_autorizadas"]:
            raise ValidacionError("RECETA_SIN_DISPENSAS", f"la receta {id_receta} no tiene dispensas")
        if not any(productos[p]["condicion_venta"] in CONDICIONES_CON_RECETA for p in pedidos):
            raise ValidacionError("RECETA_INNECESARIA", f"ningún producto requiere la receta {id_receta}")
    elif any(productos[p]["condicion_venta"] in CONDICIONES_CON_RECETA for p in pedidos):
        raise ValidacionError("RECETA_REQUERIDA", "hay productos bajo receta y no se indicó receta")
    return productos, receta


def _dispensar(db, s, receta, hoy):
    hechas = receta["dispensas_realizadas"] + 1
    sigue = receta["tipo"] == "Tratamiento prolongado" and hechas < receta["dispensas_autorizadas"]
    cambios = {"dispensas_realizadas": hechas,
               "estado": "Vigente" if sigue else "Completada",
               "proxima_dispensa": fechas.a_datetime(hoy + datetime.timedelta(days=30)) if sigue else None}
    res = db.recetas.update_one(
        {"_id": receta["_id"], "estado": "Vigente", "dispensas_realizadas": receta["dispensas_realizadas"]},
        {"$set": cambios}, session=s)
    if res.matched_count != 1:
        raise ValidacionError("RECETA_MODIFICADA", f"la receta {receta['_id']} cambió durante la venta")
    return {"id_receta": receta["_id"], **cambios}


def _venta_confirmada(db, id_venta):
    return db.ventas.find_one({"_id": id_venta, "stock_descontado": True}) is not None


def _registrar(id_cliente, id_farmaceutico, items, medio_pago, id_receta):
    db = conexiones.get_db()
    hoy = fechas.hoy()
    consumos = None
    id_venta = None
    with conexiones.get_client().start_session() as s:
        try:
            with s.start_transaction():
                productos, receta = _validar(db, s, id_cliente, id_farmaceutico, items, medio_pago, id_receta)
                id_venta = ids.siguiente_id("ventas", "V", session=s)
                detalle = [{"id_detalle": ids.siguiente_id("detalle_ventas", "D", session=s),
                            "id_producto": it["id_producto"], "cantidad": it["cantidad"],
                            "precio_unit": productos[it["id_producto"]]["precio_unit"]} for it in items]
                venta = {"_id": id_venta, "id_cliente": id_cliente, "id_farmaceutico": id_farmaceutico,
                         "id_receta": id_receta, "fecha": fechas.a_datetime(hoy),
                         "tipo": "Con receta" if id_receta else "Venta libre", "medio_pago": medio_pago,
                         "total": sum(d["cantidad"] * d["precio_unit"] for d in detalle),
                         "estado": "Completada", "items": detalle, "stock_descontado": False}
                db.ventas.insert_one(venta, session=s)
                receta_final = _dispensar(db, s, receta, hoy) if receta is not None else None
                consumos = descontar_stock_venta(id_venta, session=s)["consumos"]
        except BaseException as e:
            if consumos is None:
                raise
            # el Lua ya descontó y solo faltaba el commit. Si el commit dio un resultado desconocido o lo cortó una
            # interrupción (Ctrl+C), pudo aplicarse igual: se relee la venta y solo se repone si no quedó. Si la
            # relectura falla, se propaga sin reponer
            desconocido = isinstance(e, PyMongoError) and e.has_error_label("UnknownTransactionCommitResult")
            incierto = desconocido or not isinstance(e, Exception)
            if not (incierto and _venta_confirmada(db, id_venta)):
                stock.reponer(consumos)
                raise
            # la venta quedó con su descuento: un resultado desconocido termina en éxito, la interrupción se respeta
            if not desconocido:
                raise
    venta.update(stock_descontado=True, consumos=consumos)
    return formato.a_json({"venta": {"id_venta": id_venta, **venta}, "receta": receta_final,
                           "consumos": consumos})


def registrar_venta(id_cliente, id_farmaceutico, items, medio_pago, id_receta=None):
    """Registra una venta 'Completada' con sus ítems y descuenta el stock.

    Parámetros:
        id_cliente, id_farmaceutico: ids existentes y activos.
        items: lista de {id_producto, cantidad}.
        medio_pago: uno de los medios de pago válidos.
        id_receta: receta del cliente; obligatoria si hay productos bajo receta.
    Retorna:
        Diccionario con la venta, la receta actualizada (o None) y los consumos.
    Motor: MongoDB (transacción) y Redis (stock).
    Errores: NoEncontrado, ValidacionError (DATO_INVALIDO si un id no es texto), StockInsuficiente.
    """
    for intento in range(INTENTOS):
        try:
            return _registrar(id_cliente, id_farmaceutico, items, medio_pago, id_receta)
        except PyMongoError as e:
            # dos ventas a la vez chocan en contadores; la transacción ya se abortó y el stock se repuso.
            # Si MongoDB no responde, reintentar solo multiplica la espera
            if (isinstance(e, ServerSelectionTimeoutError) or not e.has_error_label("TransientTransactionError")
                    or intento == INTENTOS - 1):
                raise
            time.sleep(random.uniform(0.015, 0.15) * (intento + 1))
