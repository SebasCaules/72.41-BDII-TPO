from pymongo.errors import OperationFailure

from farmared import conexiones, stock
from farmared.dominio import validar_id
from farmared.errores import NoEncontrado, ValidacionError


def _sucursal(db, venta, session):
    farmaceutico = db.farmaceuticos.find_one({"_id": venta["id_farmaceutico"]}, session=session)
    if farmaceutico is None:
        raise NoEncontrado("FARMACEUTICO_INEXISTENTE", f"no existe el farmacéutico {venta['id_farmaceutico']}")
    sucursal = db.sucursales.find_one({"_id": farmaceutico["id_sucursal"]}, session=session)
    if sucursal is None:
        raise NoEncontrado("SUCURSAL_INEXISTENTE", f"no existe la sucursal {farmaceutico['id_sucursal']}")
    if sucursal["tipo"] != "Farmacia":
        raise ValidacionError("SUCURSAL_NO_FARMACIA", f"{sucursal['nombre']} no vende al público")
    return sucursal["_id"]


def _marcar(db, id_venta, consumos, session):
    res = db.ventas.update_one({"_id": id_venta, "stock_descontado": False},
                               {"$set": {"stock_descontado": True, "consumos": consumos}},
                               session=session)
    if res.matched_count != 1:
        raise ValidacionError("STOCK_YA_DESCONTADO", f"la venta {id_venta} ya descontó stock")


def _marcada(db, id_venta):
    return db.ventas.find_one({"_id": id_venta, "stock_descontado": True}) is not None


def descontar_stock_venta(id_venta, session=None):
    """Descuenta el stock de una venta registrada, por FEFO y sin lotes vencidos.

    Llamada sola (sin sesión), el descuento queda registrado en Redis por venta en el mismo paso en que se
    hace: si la marca de la venta no llega a confirmarse, una nueva llamada no descuenta otra vez.

    Parámetros:
        id_venta: id de la venta, p. ej. "V017".
        session: sesión de MongoDB cuando la llamada es parte de una transacción.
    Retorna:
        Diccionario con id_venta, id_sucursal y los consumos por lote.
    Motor: Redis (script Lua sobre los lotes) y MongoDB (marca de la venta).
    Errores: NoEncontrado, ValidacionError (DATO_INVALIDO si el id no es texto), StockInsuficiente. Un error de
        conexión o una interrupción durante la marca se propagan sin reponer: la venta queda pendiente (stock
        descontado, sin marcar y con su registro), salvo que la marca se aplique después. Una nueva llamada
        completa la pendiente sin descontar otra vez.
    """
    validar_id("id_venta", id_venta)
    db = conexiones.get_db()
    venta = db.ventas.find_one({"_id": id_venta}, session=session)
    if venta is None:
        raise NoEncontrado("VENTA_INEXISTENTE", f"no existe la venta {id_venta}")
    if venta["estado"] != "Completada":
        raise ValidacionError("VENTA_NO_COMPLETADA", f"la venta {id_venta} está {venta['estado']}")
    if venta.get("stock_descontado"):
        raise ValidacionError("STOCK_YA_DESCONTADO", f"la venta {id_venta} ya descontó stock")
    id_sucursal = _sucursal(db, venta, session)
    if session is not None:
        # dentro de una transacción no se registra: el id de una venta abortada se vuelve a usar
        consumos = stock.descontar_fefo(id_sucursal, venta["items"])
        try:
            _marcar(db, id_venta, consumos, session)
        except BaseException:
            stock.reponer(consumos)
            raise
    else:
        consumos = stock.descontar_fefo(id_sucursal, venta["items"], id_venta=id_venta)
        # ante la duda no se repone: una venta pendiente la completa el reintento con el registro, y una marca
        # aplicada con el stock repuesto no tiene salida. Una interrupción (Ctrl+C) o una relectura que falla se
        # propagan sin reponer
        try:
            _marcar(db, id_venta, consumos, None)
        except ValidacionError:
            # otra llamada marcó la venta. Si nadie más recibió estos consumos (usos 1), la que marcó descontó por
            # su cuenta, sin este registro: se repone
            stock.reponer_venta(id_venta)
            raise
        except OperationFailure:
            # el servidor respondió que la marca falló. Se relee igual: un error de write concern llega con la
            # marca aplicada
            if not _marcada(db, id_venta):
                stock.reponer_venta(id_venta)
                raise
        except Exception:
            # un error sin respuesta del servidor (conexión, tiempo): la marca puede seguir en vuelo y aplicarse
            # después, así que no se repone. Si ya se aplicó es un éxito; si no, la venta queda pendiente
            if not _marcada(db, id_venta):
                raise
    return {"id_venta": id_venta, "id_sucursal": id_sucursal, "consumos": consumos}
