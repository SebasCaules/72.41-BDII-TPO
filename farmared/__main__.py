import argparse
import importlib
import json
import sys
from pathlib import Path

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


def _item(texto):
    producto, _, cantidad = texto.partition(":")
    return {"id_producto": producto, "cantidad": int(cantidad)}


def _parser():
    p = argparse.ArgumentParser(prog="python -m farmared")
    sub = p.add_subparsers(dest="comando", required=True)
    c = sub.add_parser("carga")
    c.add_argument("--solo-provistos", action="store_true")
    c.add_argument("--validar", action="store_true")
    for q in ("q01", "q02", "q04", "q06", "q11", "q12"):
        sub.add_parser(q)
    sub.add_parser("q03").add_argument("id_cliente")
    sub.add_parser("q05").add_argument("--dias", type=int, default=60)
    sub.add_parser("q07").add_argument("--limite", type=int, default=5)
    sub.add_parser("q08").add_argument("--umbral", type=int, default=50)
    sub.add_parser("q09").add_argument("--monto", type=int, default=5000)
    sub.add_parser("q10").add_argument("id_sucursal")
    q13 = sub.add_parser("q13").add_subparsers(dest="accion", required=True)
    alta = q13.add_parser("alta")
    for campo in ("nombre", "apellido", "dni") + CONTACTO:
        alta.add_argument("--" + campo.replace("_", "-"), required=campo != "nro_afiliado")
    modificar = q13.add_parser("modificar")
    modificar.add_argument("id_cliente")
    for campo in CONTACTO:
        modificar.add_argument("--" + campo.replace("_", "-"))
    q13.add_parser("baja").add_argument("id_cliente")
    q14 = sub.add_parser("q14")
    q14.add_argument("--cliente", required=True)
    q14.add_argument("--farmaceutico", required=True)
    q14.add_argument("--item", type=_item, action="append", required=True)
    q14.add_argument("--medio-pago", required=True)
    q14.add_argument("--receta")
    sub.add_parser("q15").add_argument("id_venta")
    sub.add_parser("demo")
    return p


def ejecutar(a):
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


def main(argv=None):
    a = _parser().parse_args(argv)
    try:
        resultado = ejecutar(a)
    except FarmaRedError as e:
        print(f"Error [{e.codigo}]: {e.mensaje}", file=sys.stderr)
        return 1
    except NotImplementedError:
        print(f"Error: {a.comando} todavía no está implementado", file=sys.stderr)
        return 2
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
