import json
import sys
from pathlib import Path

from farmared import carga, fechas
from farmared.consultas import (q01_productos_activos, q02_ventas_pendientes, q03_historial_cliente,
                                q04_clientes_varias_recetas, q05_ventas_por_farmaceutico, q06_dispensas_atrasadas,
                                q07_top_productos, q08_lotes_stock_bajo, q09_ventas_libres_menores,
                                q10_clientes_por_sucursal, q11_ingresos_mes_actual, q12_clientes_sin_ventas)

CONSULTAS = (
    ("q01", q01_productos_activos, "productos_activos_con_proveedor", {}),
    ("q02", q02_ventas_pendientes, "ventas_pendientes", {}),
    ("q03", q03_historial_cliente, "historial_cliente", {"id_cliente": "C001"}),
    ("q04", q04_clientes_varias_recetas, "clientes_con_varias_recetas", {}),
    ("q05", q05_ventas_por_farmaceutico, "ventas_recientes_por_farmaceutico", {"dias": 60}),
    ("q06", q06_dispensas_atrasadas, "dispensas_atrasadas", {}),
    ("q07", q07_top_productos, "top_productos_vendidos", {"limite": 5}),
    ("q08", q08_lotes_stock_bajo, "lotes_stock_bajo", {"umbral": 50}),
    ("q09", q09_ventas_libres_menores, "ventas_libres_menores", {"monto": 5000}),
    ("q10", q10_clientes_por_sucursal, "clientes_por_sucursal", {"id_sucursal": "S001"}),
    ("q11", q11_ingresos_mes_actual, "ingresos_mes_actual", {}),
    ("q12", q12_clientes_sin_ventas, "clientes_sin_ventas", {}),
)

# Orden de las claves al escribir, el mismo con que se documenta cada consulta. Solo cambia la presentación.
PRODUCTO = ("id_producto", "nombre", "principio_activo", "categoria", "presentacion", "condicion_venta",
            "precio_unit", "activo", "proveedor")
PROVEEDOR = ("id_proveedor", "razon_social", "cuit", "tipo", "ciudad", "provincia", "telefono", "activo")
RECETA = ("id_receta", "id_cliente", "medico", "matricula_medico", "fecha_emision", "tipo", "dispensas_autorizadas",
          "dispensas_realizadas", "proxima_dispensa", "estado", "cliente")
CLIENTE = ("id_cliente", "nombre", "apellido", "dni", "email", "telefono", "ciudad", "provincia", "obra_social",
           "nro_afiliado", "activo")
ORDEN = {
    "q01": (PRODUCTO, {"proveedor": PROVEEDOR}),
    "q02": (("id_venta", "fecha", "id_cliente", "tipo", "total", "farmaceutico", "sucursal"), {}),
    "q03": (("registro", "id", "fecha", "tipo", "estado", "total", "id_receta", "id_farmaceutico", "items", "medico",
             "dispensas_autorizadas", "dispensas_realizadas", "proxima_dispensa"), {}),
    "q04": (("id_cliente", "nombre", "apellido", "cantidad_recetas"), {}),
    "q05": (("id_farmaceutico", "nombre", "apellido", "matricula", "id_sucursal", "cantidad_ventas"), {}),
    "q06": (RECETA, {"cliente": CLIENTE}),
    "q07": (("id_producto", "nombre", "unidades"), {}),
    "q08": (("id_lote", "nro_lote", "unidades", "vencimiento", "vencido", "id_producto", "producto", "id_sucursal",
             "sucursal", "id_proveedor", "proveedor"), {}),
    "q09": (("id_venta", "fecha", "id_cliente", "id_farmaceutico", "total", "estado", "medio_pago"), {}),
    "q10": (("id_cliente", "nombre", "apellido", "dni", "activo", "cantidad_ventas"), {}),
    "q11": (("id_farmaceutico", "nombre", "apellido", "id_sucursal", "cantidad_ventas", "ingresos"), {}),
    "q12": (("id_cliente", "nombre", "apellido", "activo", "ultima_venta"),
            {"ultima_venta": ("id_venta", "fecha", "estado", "total")}),
}


def ordenar(elemento, claves, anidados=None):
    if not isinstance(elemento, dict):
        return elemento
    primero = {k: elemento[k] for k in claves if k in elemento}
    salida = {**primero, **{k: v for k, v in elemento.items() if k not in primero}}
    for clave, orden in (anidados or {}).items():
        if isinstance(salida.get(clave), dict):
            salida[clave] = ordenar(salida[clave], orden)
    return salida


def escribir(destino, nombre, parametros, resultado):
    ruta = Path(destino) / f"{nombre}.json"
    contenido = {"generado": fechas.a_iso(fechas.hoy()), "parametros": parametros, "resultado": resultado}
    ruta.write_text(json.dumps(contenido, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return str(ruta)


def ejecutar(destino):
    """Recarga los datos completos y escribe los resultados de ejemplo de cada consulta y servicio.

    Parámetros:
        destino: carpeta donde se escriben los archivos qNN.json.
    Retorna:
        Lista con las rutas escritas.
    Motor: MongoDB y Redis.
    Errores: ValidacionError si los datos a cargar no son válidos.
    """
    from farmared import demo_servicios

    Path(destino).mkdir(parents=True, exist_ok=True)
    carga.cargar()
    escritas = []
    for nombre, modulo, funcion, parametros in CONSULTAS:
        try:
            resultado = getattr(modulo, funcion)(**parametros)
        except NotImplementedError:
            print(f"{nombre}: sin implementar", file=sys.stderr)
            continue
        claves, anidados = ORDEN[nombre]
        escritas.append(escribir(destino, nombre, parametros, [ordenar(e, claves, anidados) for e in resultado]))
    try:
        escritas += demo_servicios.ejecutar(destino)
    except NotImplementedError:
        print("demo_servicios: sin implementar", file=sys.stderr)
    return escritas
