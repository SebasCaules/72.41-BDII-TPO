import csv
import datetime
import io
import re
from pathlib import Path

from farmared.dominio import normalizar_dni
from farmared.errores import ValidacionError

DATOS = Path(__file__).resolve().parents[2] / "datos"
ARCHIVOS = ("clientes", "sucursales", "farmaceuticos", "proveedores", "productos", "stock_lotes",
            "recetas", "ventas", "detalle_ventas")
ENTEROS = {"unidades", "precio_unit", "cantidad", "total", "dispensas_autorizadas", "dispensas_realizadas"}
BOOLEANOS = {"activo"}
FECHAS = {"fecha", "fecha_emision", "proxima_dispensa"}
TEXTO_FECHA = {"vencimiento"}   # se valida pero queda texto: va a Redis
CSV = {f"{n}.csv" for n in ARCHIVOS}
# [0-9] y no \d, que acepta dígitos de otros alfabetos; int() acepta además '+12', ' 12 ' y '1_2'.
ENTERO = re.compile(r"-?[0-9]+")
# Fuera de int64 no entra en MongoDB. Las unidades, además, son el puntaje de un zset de Redis, un double, que pasado
# 2^53 ya no distingue un entero del siguiente.
INT64 = range(-2**63, 2**63)
RANGOS = {"unidades": range(-2**53, 2**53 + 1)}
# La misma forma para toda fecha, con ceros; un año fuera de 1900-2099 es un error de tipeo, no un dato.
FECHA = re.compile(r"(19|20)[0-9]{2}-[0-9]{2}-[0-9]{2}")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")   # NUL, tabulador, saltos de línea y los demás de control


def valor(columna, texto):
    if columna is None:   # la lista con lo que sobra de una fila larga; la informa [encabezado]
        return texto
    if not texto.strip():   # en blanco cuenta como vacío, igual que en q13
        return None
    if columna in BOOLEANOS:
        if texto not in ("True", "False"):
            raise ValueError(f"{columna}: booleano inválido {texto!r}")
        return texto == "True"
    if columna == "dni":
        dni = normalizar_dni(texto)
        if dni is None:
            raise ValueError(f"dni: número de documento inválido {texto!r}")
        return dni
    try:
        if columna in ENTEROS:
            if not ENTERO.fullmatch(texto) or int(texto) not in RANGOS.get(columna, INT64):
                raise ValueError(texto)
            return int(texto)
        if columna in FECHAS | TEXTO_FECHA:
            if not FECHA.fullmatch(texto):
                raise ValueError(texto)
            fecha = datetime.datetime.strptime(texto, "%Y-%m-%d")
            return fecha if columna in FECHAS else texto
    except ValueError:
        tipo = "entero inválido" if columna in ENTEROS else "fecha inválida"
        raise ValueError(f"{columna}: {tipo} {texto!r}") from None
    if CONTROL.search(texto):
        raise ValueError(f"{columna}: carácter de control en {texto!r}")
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
        # Sin la carpeta, la carga completa cargaría solo los provistos sin avisar.
        if not (DATOS / "adicionales").is_dir():
            sugerencia = "para cargar solo los provistos, usar --solo-provistos"
            raise ValidacionError("DATO_INVALIDO", f"adicionales: falta la carpeta; {sugerencia}")
        otros += [f"adicionales/{nombre}" for nombre, es_archivo in _entradas("adicionales")
                  if not es_archivo or nombre not in CSV | {"CASOS.md"}]
    if otros:
        raise ValidacionError("DATO_INVALIDO", f"{otros[0]}: archivo desconocido")


def leer_todo(solo_provistos=False):
    _revisar_carpetas(solo_provistos)
    filas = {}
    for n in ARCHIVOS:
        provistas = leer(n, "provistos")
        if not provistas:   # un provisto sin filas es un archivo dañado, como uno que falta
            raise ValidacionError("DATO_INVALIDO", f"provistos/{n}.csv: no tiene filas")
        filas[n] = provistas + ([] if solo_provistos else leer(n, "adicionales"))
    return filas
