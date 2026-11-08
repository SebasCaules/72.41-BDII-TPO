import csv
import datetime
import io
import re
from pathlib import Path

from farmared.errores import ValidacionError

DATOS = Path(__file__).resolve().parents[2] / "datos"
ARCHIVOS = ("clientes", "sucursales", "farmaceuticos", "proveedores", "productos", "stock_lotes",
            "recetas", "ventas", "detalle_ventas")
ENTEROS = {"unidades", "precio_unit", "cantidad", "total", "dispensas_autorizadas", "dispensas_realizadas"}
BOOLEANOS = {"activo"}
FECHAS = {"fecha", "fecha_emision", "proxima_dispensa"}
TEXTO_FECHA = {"vencimiento"}   # se valida pero queda texto: va a Redis
CSV = {f"{n}.csv" for n in ARCHIVOS}


def valor(columna, texto):
    if texto == "":
        return None
    if columna in BOOLEANOS:
        if texto not in ("True", "False"):
            raise ValueError(f"{columna}: booleano inválido {texto!r}")
        return texto == "True"
    try:
        if columna in ENTEROS:
            n = int(texto)
            if not -2**63 <= n < 2**63:   # fuera de int64 no entra en MongoDB
                raise ValueError(texto)
            return n
        if columna in FECHAS:
            return datetime.datetime.strptime(texto, "%Y-%m-%d")
        if columna in TEXTO_FECHA:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", texto):
                raise ValueError(texto)
            datetime.date.fromisoformat(texto)
    except ValueError:
        tipo = "entero inválido" if columna in ENTEROS else "fecha inválida"
        raise ValueError(f"{columna}: {tipo} {texto!r}") from None
    return texto


def leer(nombre, carpeta):
    ruta = DATOS / carpeta / f"{nombre}.csv"
    if not ruta.exists():
        return []
    crudo, origen, filas = ruta.read_bytes(), f"{carpeta}/{nombre}.csv", []
    try:
        texto = crudo.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        linea = crudo.count(b"\n", 0, e.start) + 1
        raise ValidacionError("DATO_INVALIDO", f"{origen} línea {linea}: no está en UTF-8") from e
    lector = csv.DictReader(io.StringIO(texto, newline=""))
    try:
        columnas = lector.fieldnames or []
        repetidas = [c for c in columnas if columnas.count(c) > 1]
        if repetidas:
            raise ValidacionError("DATO_INVALIDO", f"{origen} línea {lector.line_num}: columna repetida {repetidas[0]}")
        for fila in lector:
            filas.append({k: valor(k, v) for k, v in fila.items() if v is not None})
    except (ValueError, TypeError) as e:
        raise ValidacionError("DATO_INVALIDO", f"{origen} línea {lector.line_num}: {e}") from e
    except csv.Error as e:   # line_num todavía no cuenta la línea que no se pudo leer
        raise ValidacionError("DATO_INVALIDO", f"{origen} línea {lector.line_num + 1}: {e}") from e
    return filas


def _entradas(carpeta):
    """Nombre de cada entrada de la carpeta, tal como lo da el sistema, y si es un archivo; sin las ocultas."""
    ruta = DATOS / carpeta
    return sorted((e.name, e.is_file()) for e in ruta.iterdir() if not e.name.startswith(".")) if ruta.is_dir() else []


def _revisar_carpetas(solo_provistos):
    provistos = _entradas("provistos")
    faltan = sorted(CSV - {nombre for nombre, es_archivo in provistos if es_archivo})
    if faltan:
        raise ValidacionError("DATO_INVALIDO", f"provistos/{faltan[0]}: falta el archivo")
    otros = [f"provistos/{nombre}" for nombre, es_archivo in provistos if not es_archivo or nombre not in CSV]
    if not solo_provistos:
        otros += [f"adicionales/{nombre}" for nombre, es_archivo in _entradas("adicionales")
                  if not es_archivo or nombre not in CSV | {"CASOS.md"}]
    if otros:
        raise ValidacionError("DATO_INVALIDO", f"{otros[0]}: archivo desconocido")


def leer_todo(solo_provistos=False):
    _revisar_carpetas(solo_provistos)
    return {n: leer(n, "provistos") + ([] if solo_provistos else leer(n, "adicionales")) for n in ARCHIVOS}
