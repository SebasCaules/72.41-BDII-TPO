import csv
import datetime
from pathlib import Path

from farmared.errores import ValidacionError

DATOS = Path(__file__).resolve().parents[2] / "datos"
ARCHIVOS = ("clientes", "sucursales", "farmaceuticos", "proveedores", "productos", "stock_lotes",
            "recetas", "ventas", "detalle_ventas")
ENTEROS = {"unidades", "precio_unit", "cantidad", "total", "dispensas_autorizadas", "dispensas_realizadas"}
BOOLEANOS = {"activo"}
FECHAS = {"fecha", "fecha_emision", "proxima_dispensa"}   # vencimiento queda texto: va a Redis


def valor(columna, texto):
    if texto == "":
        return None
    if columna in ENTEROS:
        return int(texto)
    if columna in BOOLEANOS:
        if texto not in ("True", "False"):
            raise ValueError(f"{columna}: booleano inválido {texto!r}")
        return texto == "True"
    if columna in FECHAS:
        return datetime.datetime.strptime(texto, "%Y-%m-%d")
    return texto


def leer(nombre, carpeta):
    ruta = DATOS / carpeta / f"{nombre}.csv"
    if not ruta.exists():
        return []
    filas = []
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        for n, fila in enumerate(csv.DictReader(f), start=2):
            try:
                filas.append({k: valor(k, v) for k, v in fila.items()})
            except (ValueError, TypeError) as e:
                raise ValidacionError("DATO_INVALIDO", f"{carpeta}/{nombre}.csv línea {n}: {e}") from e
    return filas


def leer_todo(solo_provistos=False):
    return {n: leer(n, "provistos") + ([] if solo_provistos else leer(n, "adicionales")) for n in ARCHIVOS}
