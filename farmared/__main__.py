import argparse
import importlib
import json
import re
import sys
from pathlib import Path

from pymongo.errors import ConnectionFailure, OperationFailure, PyMongoError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from farmared.errores import FarmaRedError, ValidacionError

RESULTADOS = Path(__file__).resolve().parents[1] / "docs" / "resultados"
CONSULTAS = {
    "q01": ("q01_productos_activos", "productos_activos_con_proveedor"),
    "q02": ("q02_ventas_pendientes", "ventas_pendientes"),
    "q03": ("q03_historial_cliente", "historial_cliente"),
    "q04": ("q04_clientes_varias_recetas", "clientes_con_varias_recetas"),
    "q05": ("q05_ventas_por_farmaceutico", "ventas_recientes_por_farmaceutico"),
    "q06": ("q06_dispensas_atrasadas", "dispensas_atrasadas"),
    "q07": ("q07_top_productos", "top_productos_vendidos"),
    "q08": ("q08_lotes_stock_bajo", "lotes_stock_bajo"),
    "q09": ("q09_ventas_libres_menores", "ventas_libres_menores"),
    "q10": ("q10_clientes_por_sucursal", "clientes_por_sucursal"),
    "q11": ("q11_ingresos_mes_actual", "ingresos_mes_actual"),
    "q12": ("q12_clientes_sin_ventas", "clientes_sin_ventas"),
    "q14": ("q14_registrar_venta", "registrar_venta"),
    "q15": ("q15_descontar_stock", "descontar_stock_venta"),
}
CONTACTO = ("email", "telefono", "ciudad", "provincia", "obra_social", "nro_afiliado")
COMANDOS = {
    "carga": "valida los CSV y reemplaza con ellos los datos de MongoDB y Redis",
    "q01": "productos activos con los datos de su proveedor",
    "q02": "ventas pendientes con el farmacéutico, la sucursal y el total",
    "q03": "recetas y ventas de un cliente en orden cronológico",
    "q04": "clientes con más de una receta",
    "q05": "farmacéuticos activos con su cantidad de ventas recientes",
    "q06": "recetas de tratamiento prolongado con la próxima dispensa vencida",
    "q07": "productos más vendidos en unidades",
    "q08": "lotes con menos unidades que un umbral",
    "q09": "ventas de venta libre con total menor a un monto",
    "q10": "clientes atendidos en una sucursal",
    "q11": "ingresos del mes actual por farmacéutico",
    "q12": "clientes sin ventas en el último año",
    "q13": "alta, modificación y baja lógica de clientes",
    "q14": "registra una venta y descuenta el stock",
    "q15": "descuenta el stock de una venta registrada",
    "demo": "recarga los datos y escribe los resultados de ejemplo en docs/resultados/",
}
# Valor mínimo de cada parámetro numérico. El del límite es el que ya valida q07; cero días es la ventana de hoy.
MINIMOS = {"dias": (0, "los días deben"), "limite": (1, "el límite debe"), "umbral": (1, "el umbral debe"),
           "monto": (1, "el monto debe")}
ITEM = re.compile(r"(?P<id_producto>[^:]+):(?P<cantidad>[0-9]+)")


def _item(texto):
    partes = ITEM.fullmatch(texto)
    if partes is None:
        raise argparse.ArgumentTypeError(
            f"se espera PRODUCTO:CANTIDAD con la cantidad en dígitos, por ejemplo PRD001:2, y llegó {texto!r}")
    return {"id_producto": partes["id_producto"], "cantidad": int(partes["cantidad"])}


def _comando(sub, nombre, ayuda):
    return sub.add_parser(nombre, help=ayuda, description=ayuda, allow_abbrev=False)


def _parser():
    p = argparse.ArgumentParser(prog="python -m farmared", allow_abbrev=False,
                                description="Carga de datos, consultas y servicios de FarmaRed sobre MongoDB y Redis.",
                                epilog="El resultado sale en JSON por stdout. Un error sale por stderr como "
                                       "Error [CODIGO]: mensaje, con código de salida 1; un argumento faltante o "
                                       "mal formado, con el uso del comando y código de salida 2.")
    sub = p.add_subparsers(dest="comando", required=True, metavar="comando")
    c = {nombre: _comando(sub, nombre, ayuda) for nombre, ayuda in COMANDOS.items()}
    c["carga"].add_argument("--solo-provistos", action="store_true", help="no lee datos/adicionales/")
    c["carga"].add_argument("--validar", action="store_true", help="solo valida los CSV, sin escribir")
    c["q03"].add_argument("id_cliente", help="por ejemplo C001")
    c["q05"].add_argument("--dias", type=int, default=60, help="días hacia atrás desde hoy, 60 por defecto")
    c["q07"].add_argument("--limite", type=int, default=5, help="cantidad de productos, 5 por defecto")
    c["q08"].add_argument("--umbral", type=int, default=50,
                          help="lotes con menos unidades que este valor, 50 por defecto")
    c["q09"].add_argument("--monto", type=int, default=5000,
                          help="ventas con total menor a este monto en pesos, 5000 por defecto")
    c["q10"].add_argument("id_sucursal", help="por ejemplo S001")
    q13 = c["q13"].add_subparsers(dest="accion", required=True, metavar="acción")
    alta = _comando(q13, "alta", "da de alta un cliente activo con DNI único")
    for campo in ("nombre", "apellido", "dni") + CONTACTO:
        alta.add_argument("--" + campo.replace("_", "-"), required=campo != "nro_afiliado")
    modificar = _comando(q13, "modificar", "modifica los datos de contacto y la obra social de un cliente activo")
    modificar.add_argument("id_cliente")
    for campo in CONTACTO:
        modificar.add_argument("--" + campo.replace("_", "-"))
    _comando(q13, "baja", "baja lógica de un cliente activo").add_argument("id_cliente")
    c["q14"].add_argument("--cliente", required=True)
    c["q14"].add_argument("--farmaceutico", required=True)
    c["q14"].add_argument("--item", type=_item, action="append", required=True, metavar="PRODUCTO:CANTIDAD",
                          help="producto y cantidad, por ejemplo PRD001:2; se repite para vender varios productos")
    c["q14"].add_argument("--medio-pago", required=True)
    c["q14"].add_argument("--receta", help="solo si algún producto es bajo receta")
    c["q15"].add_argument("id_venta")
    return p


def _validar_minimos(a):
    for campo, (minimo, sujeto) in MINIMOS.items():
        valor = getattr(a, campo, None)
        if valor is not None and valor < minimo:
            raise ValidacionError("DATO_INVALIDO", f"{sujeto} ser al menos {minimo}: {valor}")


def ejecutar(a):
    _validar_minimos(a)
    if a.comando == "carga":
        from farmared import carga
        if not a.validar:
            return carga.cargar(a.solo_provistos)
        errores = carga.validar(a.solo_provistos)
        if errores:
            raise ValidacionError("DATO_INVALIDO", "\n".join(errores))
        return []
    if a.comando == "demo":
        from farmared import demo
        return demo.ejecutar(RESULTADOS)
    if a.comando == "q13":
        from farmared.consultas import q13_abm_clientes as q13
        campos = {c: getattr(a, c) for c in ("nombre", "apellido", "dni") + CONTACTO
                  if getattr(a, c, None) is not None}
        if a.accion == "alta":
            return q13.alta_cliente(campos)
        if a.accion == "modificar":
            return q13.modificar_cliente(a.id_cliente, campos)
        return q13.baja_cliente(a.id_cliente)
    modulo, funcion = CONSULTAS[a.comando]
    f = getattr(importlib.import_module(f"farmared.consultas.{modulo}"), funcion)
    if a.comando == "q14":
        return f(a.cliente, a.farmaceutico, a.item, a.medio_pago, a.receta)
    return f(**{k: v for k, v in vars(a).items() if k != "comando"})


def _error_de_motor(e):
    motor = "MongoDB" if isinstance(e, PyMongoError) else "Redis"
    if isinstance(e, (ConnectionFailure, RedisConnectionError, RedisTimeoutError)):
        return "CONEXION", f"{motor} no responde"
    # dentro de una transacción, MongoDB marca así un choque con otra escritura; los servicios ya reintentaron
    if isinstance(e, PyMongoError) and e.has_error_label("TransientTransactionError"):
        return "CONFLICTO", "otra escritura simultánea en MongoDB canceló la operación; se puede reintentar"
    detalle = e.details.get("errmsg", str(e)) if isinstance(e, OperationFailure) and e.details else str(e)
    return "MOTOR", f"{motor} devolvió un error: {detalle}"


def main(argv=None):
    a = _parser().parse_args(argv)
    try:
        resultado = ejecutar(a)
    except FarmaRedError as e:
        print(f"Error [{e.codigo}]: {e.mensaje}", file=sys.stderr)
        return 1
    except (PyMongoError, RedisError) as e:
        codigo, mensaje = _error_de_motor(e)
        print(f"Error [{codigo}]: {mensaje}", file=sys.stderr)
        return 1
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
