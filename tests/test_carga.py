import csv
import datetime
import json
import os
import pathlib
import shutil

import bson
import pytest
from pymongo.errors import DuplicateKeyError

import snapshots
from farmared import carga, claves, config, ids
from farmared.__main__ import main
from farmared.carga import carga_mongo, carga_redis, lector
from farmared.errores import ValidacionError

PROVISTOS = lector.DATOS / "provistos"
PK = {"clientes": "id_cliente", "sucursales": "id_sucursal", "farmaceuticos": "id_farmaceutico",
      "proveedores": "id_proveedor", "productos": "id_producto", "recetas": "id_receta", "ventas": "id_venta"}
CONTEOS = {"clientes": 8, "sucursales": 5, "farmaceuticos": 7, "proveedores": 5, "productos": 13, "recetas": 9,
           "ventas": 16, "contadores": 3}
RESULTADO = {"mongo": CONTEOS, "redis": {"lotes": 18}}

FILAS = {
    "clientes": {"id_cliente": "C001", "nombre": "Lucía", "apellido": "Fernández", "dni": "31245678",
                 "email": "lucia.f@gmail.com", "telefono": "1145112233", "ciudad": "Buenos Aires",
                 "provincia": "Buenos Aires", "obra_social": "OSDE", "nro_afiliado": "OS-310045", "activo": True},
    "sucursales": {"id_sucursal": "S001", "nombre": "Farmacia Palermo", "tipo": "Farmacia",
                   "direccion": "Av. Santa Fe 3350", "ciudad": "Buenos Aires", "provincia": "Buenos Aires",
                   "telefono": "1148001001", "activo": True},
    "farmaceuticos": {"id_farmaceutico": "F004", "nombre": "Julián", "apellido": "Pereyra", "matricula": "MN-17955",
                      "cargo": "Farmacéutico", "id_sucursal": "S002", "activo": False},
    "proveedores": {"id_proveedor": "PRV001", "razon_social": "Laboratorios Andinos S.A.", "cuit": "30-71234567-1",
                    "tipo": "Laboratorio", "ciudad": "Buenos Aires", "provincia": "Buenos Aires",
                    "telefono": "1143001100", "activo": True},
    "productos": {"id_producto": "PRD001", "nombre": "Paracetamol 500mg x30", "principio_activo": "Paracetamol",
                  "categoria": "Analgésico", "presentacion": "Comprimidos x30", "condicion_venta": "Venta libre",
                  "precio_unit": 2800, "id_proveedor": "PRV001", "activo": True},
    "stock_lotes": {"id_lote": "L001", "id_producto": "PRD001", "id_sucursal": "S001", "nro_lote": "L-2501A",
                    "unidades": 120, "vencimiento": "2027-08-31"},
    "recetas": {"id_receta": "RC002", "id_cliente": "C003", "medico": "Dra. Silvia Montenegro",
                "matricula_medico": "MP-39877", "fecha_emision": datetime.datetime(2026, 7, 15),
                "tipo": "Tratamiento prolongado", "dispensas_autorizadas": 3, "dispensas_realizadas": 2,
                "proxima_dispensa": datetime.datetime(2026, 9, 15), "estado": "Vigente"},
    "ventas": {"id_venta": "V001", "id_cliente": "C004", "id_farmaceutico": "F004", "id_receta": "RC007",
               "fecha": datetime.datetime(2025, 9, 18), "tipo": "Con receta", "medio_pago": "Obra social",
               "total": 3850, "estado": "Completada"},
    "detalle_ventas": {"id_detalle": "D001", "id_venta": "V001", "id_producto": "PRD007", "cantidad": 1,
                       "precio_unit": 3850},
}

TIPOS = {
    "clientes": {"_id": "string", "nombre": "string", "apellido": "string", "dni": "string", "email": "string",
                 "telefono": "string", "ciudad": "string", "provincia": "string", "obra_social": "string",
                 "nro_afiliado": "string", "activo": "bool"},
    "sucursales": {"_id": "string", "nombre": "string", "tipo": "string", "direccion": "string", "ciudad": "string",
                   "provincia": "string", "telefono": "string", "activo": "bool"},
    "farmaceuticos": {"_id": "string", "nombre": "string", "apellido": "string", "matricula": "string",
                      "cargo": "string", "id_sucursal": "string", "activo": "bool"},
    "proveedores": {"_id": "string", "razon_social": "string", "cuit": "string", "tipo": "string", "ciudad": "string",
                    "provincia": "string", "telefono": "string", "activo": "bool"},
    "productos": {"_id": "string", "nombre": "string", "principio_activo": "string", "categoria": "string",
                  "presentacion": "string", "condicion_venta": "string", "precio_unit": "int",
                  "id_proveedor": "string", "activo": "bool"},
    "recetas": {"_id": "string", "id_cliente": "string", "medico": "string", "matricula_medico": "string",
                "fecha_emision": "date", "tipo": "string", "dispensas_autorizadas": "int",
                "dispensas_realizadas": "int", "proxima_dispensa": "date", "estado": "string"},
    "ventas": {"_id": "string", "id_cliente": "string", "id_farmaceutico": "string", "id_receta": "string",
               "fecha": "date", "tipo": "string", "medio_pago": "string", "total": "int", "estado": "string",
               "items": "array", "stock_descontado": "bool"},
    "contadores": {"_id": "string", "ultimo": "int"},
}
TIPOS_ITEM = {"id_detalle": "string", "id_producto": "string", "cantidad": "int", "precio_unit": "int"}
NULOS = {
    "clientes": {("C005", "nro_afiliado"), ("C008", "nro_afiliado")},
    "recetas": {(id_, "proxima_dispensa") for id_ in ("RC001", "RC005", "RC006", "RC007", "RC008", "RC009")},
    "ventas": {(id_, "id_receta") for id_ in ("V002", "V012", "V013", "V014", "V015", "V016")},
}
TIPOS_POR_DOCUMENTO = {"$arrayToObject": {"$map": {"input": {"$objectToArray": "$$ROOT"}, "as": "campo",
                                                   "in": {"k": "$$campo.k", "v": {"$type": "$$campo.v"}}}}}

UNICOS = [("clientes", "dni"), ("farmaceuticos", "matricula"), ("proveedores", "cuit")]
COMPUESTOS = [
    ("recetas", ["id_cliente", "fecha_emision"]),
    ("recetas", ["tipo", "estado", "proxima_dispensa"]),
    ("ventas", ["id_cliente", "fecha"]),
    ("ventas", ["id_farmaceutico", "fecha"]),
]

ADICIONALES = {
    "clientes": "C009,Ana,Sosa,30111222,ana.s@gmail.com,1140001111,Buenos Aires,Buenos Aires,OSDE,OS-999001,True",
    "stock_lotes": "L019,PRD001,S001,L-2701A,10,2027-12-31",
    "ventas": "V017,C009,F001,,2026-10-20,Venta libre,Efectivo,2800,Completada",
    "detalle_ventas": "D023,V017,PRD001,1,2800",
}
LOTE = "L002,PRD001,S002,L-2501A,35,2027-08-31"


@pytest.fixture(scope="module", autouse=True)
def base_con_provistos_al_terminar():
    yield
    carga.cargar(solo_provistos=True)


@pytest.fixture
def copia(tmp_path, monkeypatch):
    shutil.copytree(PROVISTOS, tmp_path / "provistos")
    (tmp_path / "adicionales").mkdir()
    monkeypatch.setattr(lector, "DATOS", tmp_path)
    return tmp_path


@pytest.fixture
def con_adicionales(copia):
    for archivo, fila in ADICIONALES.items():
        encabezado = (copia / "provistos" / f"{archivo}.csv").read_text(encoding="utf-8").splitlines()[0]
        (copia / "adicionales" / f"{archivo}.csv").write_text(f"{encabezado}\n{fila}\n", encoding="utf-8")
    return copia


AJENAS = ("otra:clave", "lote", "lotes_viejos", "stockeo", "stock")
# SET con los ids de los lotes que escribía una carga anterior; ya no es parte del esquema.
SET_ANTERIOR = "lotes"


@pytest.fixture
def clave_ajena(r):
    assert config.redis_db() == 1
    r.flushdb()
    for clave in AJENAS:
        r.set(clave, "valor")
    yield AJENAS
    r.delete(*AJENAS)


def crudas(archivo):
    with open(PROVISTOS / f"{archivo}.csv", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def reemplazar(ruta, desde, hacia):
    texto = ruta.read_text(encoding="utf-8")
    assert texto.count(desde) == 1, desde
    ruta.write_text(texto.replace(desde, hacia), encoding="utf-8")


def corromper_total(carpeta):
    reemplazar(carpeta / "provistos" / "ventas.csv", "Obra social,3850,Completada", "Obra social,3851,Completada")


def fotos():
    return snapshots.mongo_snap(), snapshots.redis_snap()


def alterar_motores(db, r):
    """Deja un estado que ninguna carga produce: si después algo escribe, las fotos cambian."""
    assert db.ventas.delete_one({"_id": "V001"}).deleted_count == 1
    r.hset(claves.lote("L001"), "unidades", 0)
    r.zadd(claves.UNIDADES, {"L001": 0})


def tipos_en_motor(coleccion, *previo):
    return list(coleccion.aggregate([*previo, {"$project": {"tipos": TIPOS_POR_DOCUMENTO}}]))


def campos(documento):
    for campo, valor in documento.items():
        yield campo
        if isinstance(valor, list):
            for elemento in valor:
                yield from campos(elemento)


def como_texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, datetime.datetime):
        # Una hora distinta de medianoche deja el sufijo y no coincide con el CSV.
        return valor.isoformat().removesuffix("T00:00:00")
    return str(valor)


@pytest.mark.parametrize("archivo", FILAS)
def test_tipo_de_cada_columna_por_archivo(archivo):
    esperada = FILAS[archivo]
    clave = next(iter(esperada))
    fila = next(f for f in lector.leer_todo(True)[archivo] if f[clave] == esperada[clave])
    assert fila == esperada
    assert list(fila) == list(esperada)
    assert {k: type(v) for k, v in fila.items()} == {k: type(v) for k, v in esperada.items()}


def test_cantidad_de_filas_por_archivo():
    filas = lector.leer_todo(True)
    assert {a: len(f) for a, f in filas.items()} == {
        "clientes": 8, "sucursales": 5, "farmaceuticos": 7, "proveedores": 5, "productos": 13, "stock_lotes": 18,
        "recetas": 9, "ventas": 16, "detalle_ventas": 22}


def test_booleanos():
    assert lector.valor("activo", "True") is True
    assert lector.valor("activo", "False") is False
    clientes = {c["id_cliente"]: c for c in lector.leer_todo(True)["clientes"]}
    assert clientes["C001"]["activo"] is True
    assert clientes["C008"]["activo"] is False


@pytest.mark.parametrize("invalido", ["true", "FALSE", "1", "Si", "True "])
def test_booleano_invalido(copia, capsys, invalido):
    reemplazar(copia / "provistos" / "clientes.csv", "OS-310045,True", f"OS-310045,{invalido}")
    with pytest.raises(ValidacionError) as e:
        lector.leer("clientes", "provistos")
    assert e.value.codigo == "DATO_INVALIDO"
    assert "clientes.csv línea 2" in e.value.mensaje
    assert "activo" in e.value.mensaje
    with pytest.raises(ValidacionError) as e:
        carga.validar(True)
    assert e.value.codigo == "DATO_INVALIDO"
    assert main(["carga", "--validar"]) == 1
    assert "DATO_INVALIDO" in capsys.readouterr().err


@pytest.mark.parametrize("archivo, desde, hacia, linea, motivo", [
    ("ventas", "RC007,2025-09-18,", "RC007,2026-13-10,", 2, "fecha: fecha inválida"),
    ("ventas", "RC007,2025-09-18,", "RC007,10/09/2026,", 2, "fecha: fecha inválida"),
    ("ventas", "Obra social,3850,", "Obra social,98.00,", 2, "total: entero inválido"),
    ("stock_lotes", "L-2501A,120,", "L-2501A,12a,", 2, "unidades: entero inválido"),
    ("stock_lotes", "L-2506A,40,2026-11-30", "L-2506A,40,2026-11-31", 6, "vencimiento: fecha inválida"),
])
def test_entero_o_fecha_invalidos(copia, capsys, archivo, desde, hacia, linea, motivo):
    reemplazar(copia / "provistos" / f"{archivo}.csv", desde, hacia)
    invalido = hacia.split(",")[-1] or hacia.split(",")[-2]
    with pytest.raises(ValidacionError) as e:
        lector.leer(archivo, "provistos")
    assert e.value.codigo == "DATO_INVALIDO"
    assert e.value.mensaje == f"provistos/{archivo}.csv línea {linea}: {motivo} {invalido!r}"
    with pytest.raises(ValidacionError) as e:
        carga.validar(True)
    assert e.value.codigo == "DATO_INVALIDO"
    assert main(["carga", "--validar"]) == 1
    assert "DATO_INVALIDO" in capsys.readouterr().err


@pytest.mark.parametrize("columna", ["fecha", "fecha_emision", "proxima_dispensa", "unidades", "total", "activo",
                                     "dni", "nro_afiliado", "vencimiento", "id_receta"])
def test_vacio_da_none(columna):
    assert lector.valor(columna, "") is None


def test_vacios_en_los_archivos():
    filas = lector.leer_todo(True)
    recetas = {f["id_receta"]: f for f in filas["recetas"]}
    assert recetas["RC001"]["proxima_dispensa"] is None
    assert recetas["RC002"]["proxima_dispensa"] == datetime.datetime(2026, 9, 15)
    assert {c["id_cliente"]: c["nro_afiliado"] for c in filas["clientes"]}["C005"] is None
    assert {v["id_venta"]: v["id_receta"] for v in filas["ventas"]}["V002"] is None


@pytest.mark.parametrize("columna, texto", [("telefono", "01145112233"), ("cuit", "30-71234567-1"),
                                            ("nro_afiliado", "0012")])
def test_identificadores_conservan_el_texto(columna, texto):
    assert lector.valor(columna, texto) == texto


def test_identificadores_quedan_str_en_los_archivos():
    filas = lector.leer_todo(True)
    for archivo, columna in [("clientes", "dni"), ("clientes", "telefono"), ("proveedores", "cuit"),
                             ("proveedores", "telefono"), ("sucursales", "telefono")]:
        assert all(type(f[columna]) is str for f in filas[archivo]), columna
    assert all(type(f["nro_afiliado"]) is str or f["nro_afiliado"] is None for f in filas["clientes"])


def test_vencimiento_queda_str():
    lotes = lector.leer_todo(True)["stock_lotes"]
    assert len(lotes) == 18
    assert all(type(l["vencimiento"]) is str for l in lotes)
    assert lector.valor("vencimiento", "2027-08-31") == "2027-08-31"
    assert lector.valor("vencimiento", "2028-02-29") == "2028-02-29"


@pytest.mark.parametrize("texto", ["2027-02-30", "2027-13-01", "31/08/2027", "20270831", "2027-8-31", "2027-08-31 ",
                                   "2027-08-31\n", "2027-08-31T00:00", "２０２７-08-31"])
def test_vencimiento_invalido(texto):
    with pytest.raises(ValueError) as e:
        lector.valor("vencimiento", texto)
    assert str(e.value) == f"vencimiento: fecha inválida {texto!r}"


@pytest.mark.parametrize("texto", [str(2**63 - 1), str(-2**63), "0", "-5"])
def test_entero_dentro_de_int64(texto):
    assert lector.valor("precio_unit", texto) == int(texto)


@pytest.mark.parametrize("texto", [str(2**63), str(-2**63 - 1), "1" + "0" * 309])
def test_entero_fuera_de_int64(texto):
    with pytest.raises(ValueError) as e:
        lector.valor("precio_unit", texto)
    assert str(e.value) == f"precio_unit: entero inválido {texto!r}"


def test_archivo_que_no_esta_en_utf8(copia, capsys):
    encabezado = (copia / "provistos" / "clientes.csv").read_text(encoding="utf-8").splitlines()[0]
    fila = "C009,Ana,Sosa,30111222,ana.s@gmail.com,1140001111,Córdoba,Córdoba,OSDE,OS-999001,True"
    (copia / "adicionales" / "clientes.csv").write_bytes(f"{encabezado}\n{fila}\n".encode("latin-1"))
    mensaje = "adicionales/clientes.csv línea 2: no está en UTF-8"
    with pytest.raises(ValidacionError) as e:
        carga.validar()
    assert (e.value.codigo, e.value.mensaje) == ("DATO_INVALIDO", mensaje)
    assert main(["carga", "--validar"]) == 1
    assert capsys.readouterr().err == f"Error [DATO_INVALIDO]: {mensaje}\n"
    assert carga.validar(True) == []


def test_error_del_formato_csv(copia, capsys):
    reemplazar(copia / "provistos" / "stock_lotes.csv", LOTE, f"L002,PRD001,S002,{'x' * 200_000},35,2027-08-31")
    with pytest.raises(ValidacionError) as e:
        lector.leer("stock_lotes", "provistos")
    assert e.value.codigo == "DATO_INVALIDO"
    assert e.value.mensaje.startswith("provistos/stock_lotes.csv línea 3: field larger than field limit")
    assert main(["carga"]) == 1
    assert capsys.readouterr().err.startswith("Error [DATO_INVALIDO]: provistos/stock_lotes.csv línea 3: ")


def test_fila_corta_no_agrega_las_columnas_que_faltan(copia):
    reemplazar(copia / "provistos" / "stock_lotes.csv", LOTE, "L002,PRD001,S002,L-2501A,35")
    corta = lector.leer("stock_lotes", "provistos")[1]
    assert list(corta) == ["id_lote", "id_producto", "id_sucursal", "nro_lote", "unidades"]


def test_fila_larga_conserva_lo_que_sobra(copia):
    reemplazar(copia / "provistos" / "stock_lotes.csv", LOTE, LOTE + ",extra")
    larga = lector.leer("stock_lotes", "provistos")[1]
    assert larga[None] == ["extra"]


VENCIMIENTO_INVALIDO = "provistos/stock_lotes.csv línea 3: vencimiento: fecha inválida"
UNIDADES_INVALIDAS = "provistos/stock_lotes.csv línea 3: unidades: entero inválido"
LOTES_INVALIDOS = [
    ("L002,PRD001,S002,L-2501A,35,2027-02-30", f"{VENCIMIENTO_INVALIDO} '2027-02-30'"),
    ("L002,PRD001,S002,L-2501A,35,31/08/2027", f"{VENCIMIENTO_INVALIDO} '31/08/2027'"),
    ("L002,PRD001,S002,L-2501A,35,20270831", f"{VENCIMIENTO_INVALIDO} '20270831'"),
    ("L002,PRD001,S002,L-2501A,9223372036854775808,2027-08-31", f"{UNIDADES_INVALIDAS} '9223372036854775808'"),
    ("L002,PRD001,S002,L-2501A,-9223372036854775809,2027-08-31", f"{UNIDADES_INVALIDAS} '-9223372036854775809'"),
    (f"L002,PRD001,S002,L-2501A,1{'0' * 309},2027-08-31", f"{UNIDADES_INVALIDAS} '1{'0' * 309}'"),
    ("L002,PRD001,S002,L-2501A,35,", "stock_lotes.csv L002: [obligatorio] vencimiento vacío"),
    ("L002,PRD001,S002,L-2501A,-1,2027-08-31",
     "stock_lotes.csv L002: [rango] unidades -1 debe ser mayor o igual que 0"),
    ("L002,PRD001,S002,L-2501A,,2027-08-31", "stock_lotes.csv L002: [obligatorio] unidades vacío"),
    ("L002,PRD001,S002,,35,2027-08-31", "stock_lotes.csv L002: [obligatorio] nro_lote vacío"),
    ("L002,PRD001,S002,L-2501A,35", "stock_lotes.csv L002: [encabezado] columnas distintas de las esperadas"),
    ("L002,PRD001,S002,L-2501A,35,2027-08-31,extra",
     "stock_lotes.csv L002: [encabezado] columnas distintas de las esperadas"),
]
PRODUCTO = "Venta libre,3500,PRV001"
PRECIO_INVALIDO = "provistos/productos.csv línea 3: precio_unit: entero inválido"
DATOS_INVALIDOS = [("stock_lotes", LOTE, hacia, motivo) for hacia, motivo in LOTES_INVALIDOS] + [
    ("productos", PRODUCTO, "Venta libre,9223372036854775808,PRV001", f"{PRECIO_INVALIDO} '9223372036854775808'"),
    ("productos", PRODUCTO, "Venta libre,-9223372036854775809,PRV001", f"{PRECIO_INVALIDO} '-9223372036854775809'"),
]


@pytest.mark.parametrize("archivo, desde, hacia, motivo", DATOS_INVALIDOS)
def test_dato_invalido_no_llega_a_ningun_motor(copia, capsys, db, r, archivo, desde, hacia, motivo):
    carga.cargar(solo_provistos=True)
    alterar_motores(db, r)
    reemplazar(copia / "provistos" / f"{archivo}.csv", desde, hacia)
    antes = fotos()
    try:
        assert carga.validar(True) == [motivo]
    except ValidacionError as e:
        assert (e.codigo, e.mensaje) == ("DATO_INVALIDO", motivo)
    with pytest.raises(ValidacionError) as e:
        carga.cargar(solo_provistos=True)
    assert e.value.codigo == "DATO_INVALIDO"
    assert main(["carga"]) == 1
    error = capsys.readouterr().err
    assert error == f"Error [DATO_INVALIDO]: {motivo}\n"
    assert fotos() == antes


ENCABEZADOS_MAL_ESCRITOS = [("stock_lotes", "nro_lote", "nro_lte"), ("stock_lotes", "unidades", "unidad"),
                            ("clientes", "dni", "dnii")]


def escribir_mal_el_encabezado(carpeta, archivo, columna, mal_escrita):
    ruta = carpeta / "provistos" / f"{archivo}.csv"
    encabezado, resto = ruta.read_text(encoding="utf-8").split("\n", 1)
    columnas = encabezado.split(",")
    assert columnas.count(columna) == 1
    ruta.write_text(",".join(mal_escrita if c == columna else c for c in columnas) + "\n" + resto, encoding="utf-8")


@pytest.mark.parametrize("archivo, columna, mal_escrita", ENCABEZADOS_MAL_ESCRITOS)
def test_encabezado_mal_escrito_no_llega_a_ningun_motor(copia, capsys, db, r, archivo, columna, mal_escrita):
    carga.cargar(solo_provistos=True)
    alterar_motores(db, r)
    escribir_mal_el_encabezado(copia, archivo, columna, mal_escrita)
    antes = fotos()
    assert {e.split(": ")[1].split()[0] for e in carga.validar(True)} == {"[encabezado]"}
    assert main(["carga"]) == 1
    assert capsys.readouterr().err.startswith(f"Error [DATO_INVALIDO]: {archivo}.csv ")
    assert fotos() == antes


@pytest.mark.parametrize("archivo, columna, mal_escrita", ENCABEZADOS_MAL_ESCRITOS)
def test_sin_validar_el_encabezado_mal_escrito_falla_antes_de_borrar(copia, db, r, monkeypatch, archivo, columna,
                                                                     mal_escrita):
    carga.cargar(solo_provistos=True)
    alterar_motores(db, r)
    escribir_mal_el_encabezado(copia, archivo, columna, mal_escrita)
    antes = fotos()
    monkeypatch.setattr(carga, "validar", lambda *_: [])
    with pytest.raises((KeyError, ValidacionError)):
        carga.cargar(solo_provistos=True)
    assert fotos() == antes


def test_columna_repetida_en_el_encabezado(copia, capsys):
    escribir_mal_el_encabezado(copia, "clientes", "telefono", "email")
    mensaje = "provistos/clientes.csv línea 1: columna repetida email"
    with pytest.raises(ValidacionError) as e:
        lector.leer("clientes", "provistos")
    assert (e.value.codigo, e.value.mensaje) == ("DATO_INVALIDO", mensaje)
    with pytest.raises(ValidacionError) as e:
        carga.validar(True)
    assert (e.value.codigo, e.value.mensaje) == ("DATO_INVALIDO", mensaje)
    assert main(["carga", "--validar"]) == 1
    assert capsys.readouterr().err == f"Error [DATO_INVALIDO]: {mensaje}\n"


@pytest.mark.parametrize("nombre", ["cliente.csv", "Clientes.csv", "clientes.txt", "viejos"])
def test_archivo_desconocido_en_adicionales(con_adicionales, capsys, nombre):
    if nombre == "viejos":
        (con_adicionales / "adicionales" / nombre).mkdir()
    else:
        shutil.copy(con_adicionales / "adicionales" / "clientes.csv", con_adicionales / "adicionales" / nombre)
    mensaje = f"adicionales/{nombre}: archivo desconocido"
    with pytest.raises(ValidacionError) as e:
        carga.validar()
    assert (e.value.codigo, e.value.mensaje) == ("DATO_INVALIDO", mensaje)
    assert main(["carga", "--validar"]) == 1
    assert capsys.readouterr().err == f"Error [DATO_INVALIDO]: {mensaje}\n"
    assert carga.validar(True) == []
    assert len(lector.leer_todo(True)["clientes"]) == 8


def test_casos_y_ocultos_se_ignoran(con_adicionales):
    (con_adicionales / "adicionales" / "CASOS.md").write_text("# Casos\n", encoding="utf-8")
    for carpeta in ("provistos", "adicionales"):
        (con_adicionales / carpeta / ".DS_Store").write_bytes(b"\x00\x01")
        (con_adicionales / carpeta / ".gitkeep").write_text("", encoding="utf-8")
    assert carga.validar() == []
    assert len(lector.leer_todo()["clientes"]) == 9


def test_falta_un_provisto(copia, capsys):
    (copia / "provistos" / "stock_lotes.csv").unlink()
    (copia / "provistos" / "notas.txt").write_text("", encoding="utf-8")
    (copia / "adicionales" / "otro.csv").write_text("", encoding="utf-8")
    mensaje = "provistos/stock_lotes.csv: falta el archivo"
    for solo_provistos in (False, True):
        with pytest.raises(ValidacionError) as e:
            carga.validar(solo_provistos)
        assert (e.value.codigo, e.value.mensaje) == ("DATO_INVALIDO", mensaje)
    assert main(["carga", "--validar"]) == 1
    assert capsys.readouterr().err == f"Error [DATO_INVALIDO]: {mensaje}\n"


def sin_distinguir_mayusculas(monkeypatch):
    """Hace que is_file y exists encuentren un archivo aunque el nombre difiera en mayúsculas, como en macOS."""
    def real(ruta):
        padre, nombre = os.path.split(os.fspath(ruta))
        try:
            return next((os.path.join(padre, n) for n in os.listdir(padre) if n.lower() == nombre.lower()), None)
        except OSError:
            return None

    monkeypatch.setattr(pathlib.Path, "is_file", lambda self, *_, **__: os.path.isfile(real(self) or ""))
    monkeypatch.setattr(pathlib.Path, "exists", lambda self, *_, **__: real(self) is not None)


def test_otro_nombre_es_desconocido_aunque_el_sistema_no_distinga_mayusculas(con_adicionales, monkeypatch):
    sin_distinguir_mayusculas(monkeypatch)
    (con_adicionales / "adicionales" / "clientes.csv").rename(con_adicionales / "adicionales" / "Clientes.csv")
    assert (con_adicionales / "adicionales" / "clientes.csv").is_file()   # la simulación está activa
    with pytest.raises(ValidacionError, match="^adicionales/Clientes.csv: archivo desconocido$"):
        carga.validar()
    (con_adicionales / "provistos" / "clientes.csv").rename(con_adicionales / "provistos" / "Clientes.csv")
    assert (con_adicionales / "provistos" / "clientes.csv").exists()
    for solo_provistos in (False, True):
        with pytest.raises(ValidacionError, match="^provistos/clientes.csv: falta el archivo$"):
            carga.validar(solo_provistos)


def test_sobra_un_archivo_en_provistos(copia):
    (copia / "provistos" / "viejo.csv").write_text("", encoding="utf-8")
    (copia / "adicionales" / "otro.csv").write_text("", encoding="utf-8")
    for solo_provistos in (False, True):
        with pytest.raises(ValidacionError) as e:
            carga.validar(solo_provistos)
        assert (e.value.codigo, e.value.mensaje) == ("DATO_INVALIDO", "provistos/viejo.csv: archivo desconocido")


def test_sobra_una_subcarpeta_en_provistos(copia):
    (copia / "provistos" / "viejos").mkdir()
    with pytest.raises(ValidacionError, match="^provistos/viejos: archivo desconocido$"):
        carga.validar(True)


@pytest.mark.parametrize("id_", ["CX", "C" + "9" * 19, "C1" + "0" * 4400], ids=["sin-numero", "19-digitos",
                                                                                 "4401-digitos"])
def test_id_con_formato_invalido_no_llega_a_ningun_motor(copia, capsys, db, r, id_):
    carga.cargar(solo_provistos=True)
    alterar_motores(db, r)
    reemplazar(copia / "provistos" / "clientes.csv", "C008,", f"{id_},")
    antes = fotos()
    motivo = f"clientes.csv {id_}: [formato-id] formato inválido; se espera C y un número de tres dígitos, como C001"
    assert main(["carga", "--validar"]) == 1
    salida = capsys.readouterr()
    assert (salida.out, salida.err) == ("", f"Error [DATO_INVALIDO]: {motivo}\n")
    with pytest.raises(ValidacionError) as e:
        carga.cargar(solo_provistos=True)
    assert (e.value.codigo, e.value.mensaje) == ("DATO_INVALIDO", motivo)
    assert fotos() == antes


def documento_de(largo):
    """Un cliente que codificado en BSON ocupa exactamente largo bytes."""
    base = len(bson.encode({"_id": "C001", "nombre": ""}))
    return {"_id": "C001", "nombre": "x" * (largo - base)}


def test_comprobar_admite_hasta_16_mib():
    maximo = documento_de(carga_mongo.MAXIMO_BSON)
    assert len(bson.encode(maximo)) == 16 * 1024 * 1024
    assert carga_mongo._comprobar({"clientes": [maximo]}) == {"clientes": [maximo]}
    with pytest.raises(ValidacionError) as e:
        carga_mongo._comprobar({"clientes": [documento_de(carga_mongo.MAXIMO_BSON + 1)]})
    assert (e.value.codigo, e.value.mensaje) == (
        "DATO_INVALIDO", "clientes C001: documento de 16777217 bytes, más que el máximo de 16 MiB")


def test_documento_de_mas_de_16_mib_falla_antes_de_borrar(copia, db, r, monkeypatch):
    carga.cargar(solo_provistos=True)
    alterar_motores(db, r)
    antes = fotos()
    filas = lector.leer_todo(True)
    filas["clientes"][0]["nombre"] = "x" * carga_mongo.MAXIMO_BSON
    monkeypatch.setattr(carga, "validar", lambda *_: [])
    monkeypatch.setattr(lector, "leer_todo", lambda *_: filas)
    with pytest.raises(ValidacionError, match="^clientes C001: documento de [0-9]+ bytes, más que el máximo"):
        carga.cargar(solo_provistos=True)
    assert fotos() == antes


def test_documentos_rechaza_lo_que_mongo_no_aceptaria():
    filas = lector.leer_todo(True)
    filas["clientes"].append(dict(filas["clientes"][0], dni="NUEVO"))
    with pytest.raises(ValidacionError, match="clientes: _id repetido"):
        carga_mongo.documentos(filas)
    filas = lector.leer_todo(True)
    filas["productos"][1]["precio_unit"] = 2**63
    with pytest.raises(ValidacionError, match="productos PRD002: "):
        carga_mongo.documentos(filas)


def test_preparar_rechaza_un_lote_con_valor_vacio():
    lotes = lector.leer_todo(True)["stock_lotes"]
    lotes[1]["nro_lote"] = None
    with pytest.raises(ValidacionError, match="lote L002: valor vacío"):
        carga_redis.preparar(lotes)


@pytest.mark.parametrize("modulo, funcion", [(carga_redis, "preparar"), (carga_mongo, "documentos")])
def test_nada_se_borra_si_falla_la_preparacion(copia, db, r, monkeypatch, modulo, funcion):
    carga.cargar(solo_provistos=True)
    alterar_motores(db, r)
    antes = fotos()

    def falla(*_):
        raise RuntimeError("preparación interrumpida")

    monkeypatch.setattr(modulo, funcion, falla)
    with pytest.raises(RuntimeError):
        carga.cargar(solo_provistos=True)
    assert fotos() == antes


def test_conteos(datos_provistos, db):
    assert {c: db[c].count_documents({}) for c in CONTEOS} == CONTEOS


def test_contadores(datos_provistos, db):
    assert list(db.contadores.find(sort=[("_id", 1)])) == [
        {"_id": "clientes", "ultimo": 8}, {"_id": "detalle_ventas", "ultimo": 22}, {"_id": "ventas", "ultimo": 16}]


def test_v002_con_sus_dos_items_ordenados(datos_provistos, db):
    assert db.ventas.find_one({"_id": "V002"})["items"] == [
        {"id_detalle": "D002", "id_producto": "PRD011", "cantidad": 2, "precio_unit": 1750},
        {"id_detalle": "D003", "id_producto": "PRD001", "cantidad": 1, "precio_unit": 2250}]


def test_items_de_todas_las_ventas(datos_provistos, db):
    detalle = crudas("detalle_ventas")
    ventas = list(db.ventas.find())
    assert sum(len(v["items"]) for v in ventas) == 22
    for v in ventas:
        assert [i["id_detalle"] for i in v["items"]] == [d["id_detalle"] for d in detalle if d["id_venta"] == v["_id"]]
        assert v["total"] == sum(i["cantidad"] * i["precio_unit"] for i in v["items"])


def test_items_se_ordenan_aunque_el_csv_venga_desordenado(copia, db):
    ruta = copia / "provistos" / "detalle_ventas.csv"
    encabezado, *filas = ruta.read_text(encoding="utf-8").splitlines()
    ruta.write_text("\n".join([encabezado, *reversed(filas)]) + "\n", encoding="utf-8")
    carga.cargar(solo_provistos=True)
    assert [i["id_detalle"] for i in db.ventas.find_one({"_id": "V002"})["items"]] == ["D002", "D003"]


@pytest.mark.parametrize("coleccion", PK)
def test_id_de_cada_documento(datos_provistos, db, coleccion):
    documentos = list(db[coleccion].find())
    assert sorted(d["_id"] for d in documentos) == sorted(f[PK[coleccion]] for f in crudas(coleccion))
    assert all(PK[coleccion] not in d for d in documentos)


@pytest.mark.parametrize("coleccion", TIPOS)
def test_tipo_de_cada_campo(datos_provistos, db, coleccion):
    obtenidos = tipos_en_motor(db[coleccion])
    assert len(obtenidos) == CONTEOS[coleccion]
    nulos = NULOS.get(coleccion, set())
    for documento in obtenidos:
        esperados = {c: "null" if (documento["_id"], c) in nulos else t for c, t in TIPOS[coleccion].items()}
        assert documento["tipos"] == esperados, documento["_id"]


def test_tipo_de_cada_campo_de_los_items(datos_provistos, db):
    obtenidos = tipos_en_motor(db.ventas, {"$unwind": "$items"}, {"$replaceWith": "$items"})
    assert len(obtenidos) == 22
    assert all(d["tipos"] == TIPOS_ITEM for d in obtenidos)


@pytest.mark.parametrize("coleccion", PK)
def test_nulos_donde_el_csv_tiene_vacio(datos_provistos, db, coleccion):
    en_csv = {(f[PK[coleccion]], c) for f in crudas(coleccion) for c, v in f.items() if v == ""}
    en_motor = {(d["_id"], c) for d in db[coleccion].find() for c, v in d.items() if v is None}
    assert en_motor == en_csv == NULOS.get(coleccion, set())


@pytest.mark.parametrize("coleccion", PK)
def test_valores_iguales_a_los_del_csv(datos_provistos, db, coleccion):
    documentos = {d["_id"]: d for d in db[coleccion].find()}
    for fila in crudas(coleccion):
        documento = documentos[fila[PK[coleccion]]]
        for columna, texto in fila.items():
            campo = "_id" if columna == PK[coleccion] else columna
            assert como_texto(documento[campo]) == texto, (fila[PK[coleccion]], columna)


def test_stock_descontado_solo_en_completadas(datos_provistos, db):
    ventas = list(db.ventas.find())
    assert {v["estado"] for v in ventas} == {"Completada", "Pendiente", "Anulada"}
    assert all(v["stock_descontado"] is (v["estado"] == "Completada") for v in ventas)
    assert sorted(v["_id"] for v in ventas if not v["stock_descontado"]) == ["V011", "V012", "V015"]


def test_ninguna_coleccion_guarda_stock(datos_provistos, db):
    assert not {"stock", "stock_lotes", "lotes"} & set(db.list_collection_names())
    prohibidos = {"stock", "stock_lotes", "lotes", "id_lote", "nro_lote", "unidades", "vencimiento"}
    for coleccion in CONTEOS:
        for documento in db[coleccion].find():
            assert not prohibidos & set(campos(documento)), documento["_id"]


def test_claves_de_redis(datos_provistos, r):
    estado = snapshots.redis_snap()
    assert len(estado) == 36
    assert sum(k.startswith("lote:") for k in estado) == 18
    assert sum(k.startswith("stock:") for k in estado) == 17
    assert claves.UNIDADES in estado
    assert not r.exists(SET_ANTERIOR)
    assert len(list(r.scan_iter(match="lote:*"))) == 18
    assert len(list(r.scan_iter(match="stock:*"))) == 17


def test_contenido_y_tipos_de_un_lote(datos_provistos, r):
    assert r.type("lote:L005") == "hash"
    assert r.hgetall("lote:L005") == {"id_producto": "PRD003", "id_sucursal": "S001", "nro_lote": "L-2506A",
                                      "unidades": "40", "vencimiento": "2026-11-30"}
    assert r.type("stock:S001:PRD003") == "zset"
    assert r.zrange("stock:S001:PRD003", 0, -1, withscores=True) == [("L005", 20261130.0), ("L015", 20270630.0)]
    assert r.type(claves.UNIDADES) == "zset"


def test_zrange_en_orden_de_vencimiento(datos_provistos, r):
    assert r.zrange("stock:S001:PRD003", 0, -1) == ["L005", "L015"]


def test_todos_los_lotes_iguales_al_csv(datos_provistos, r):
    lotes = crudas("stock_lotes")
    assert {k.removeprefix("lote:") for k in r.scan_iter(match="lote:*")} == {l["id_lote"] for l in lotes}
    for l in lotes:
        assert r.hgetall(claves.lote(l["id_lote"])) == {k: v for k, v in l.items() if k != "id_lote"}
        puntaje = int(l["vencimiento"].replace("-", ""))
        assert r.zscore(claves.stock(l["id_sucursal"], l["id_producto"]), l["id_lote"]) == puntaje


def test_lotes_unidades_con_las_unidades_como_score(datos_provistos, r):
    por_unidades = r.zrange(claves.UNIDADES, 0, -1, withscores=True)
    assert dict(por_unidades) == {l["id_lote"]: float(l["unidades"]) for l in crudas("stock_lotes")}
    assert len(por_unidades) == 18
    assert por_unidades[0] == ("L010", 12.0)
    assert por_unidades[-1] == ("L016", 4000.0)


def test_clave_ajena_sobrevive(r, clave_ajena):
    carga.cargar(solo_provistos=True)
    assert [r.get(clave) for clave in clave_ajena] == ["valor"] * len(clave_ajena)
    assert len(snapshots.redis_snap()) == 36
    assert r.dbsize() == 36 + len(clave_ajena)


def test_claves_viejas_del_esquema_se_borran(datos_provistos, r):
    # Más de una tanda de borrado, para pasar por el corte de 500.
    p = r.pipeline()
    for n in range(1201):
        p.hset(f"lote:X{n}", "unidades", 1)
    p.execute()
    r.zadd("stock:S999:PRD999", {"X0": 20270101})
    r.sadd(SET_ANTERIOR, "X0")
    r.zadd(claves.UNIDADES, {"X0": 1})
    carga.cargar(solo_provistos=True)
    estado = snapshots.redis_snap()
    assert len(estado) == 36
    assert "lote:X0" not in estado and "stock:S999:PRD999" not in estado
    assert not r.exists(SET_ANTERIOR)
    assert r.zscore(claves.UNIDADES, "X0") is None


@pytest.mark.parametrize("coleccion, campo", UNICOS)
def test_indices_unicos(datos_provistos, db, coleccion, campo):
    indice = db[coleccion].index_information()[f"{campo}_1"]
    assert indice["key"] == [(campo, 1)]
    assert indice["unique"] is True


@pytest.mark.parametrize("coleccion, llaves", COMPUESTOS)
def test_indices_compuestos(datos_provistos, db, coleccion, llaves):
    indice = db[coleccion].index_information()["_".join(f"{c}_1" for c in llaves)]
    assert indice["key"] == [(c, 1) for c in llaves]
    assert not indice.get("unique", False)


def test_indices_de_cada_coleccion(datos_provistos, db):
    assert {c: set(db[c].index_information()) for c in CONTEOS} == {
        "clientes": {"_id_", "dni_1"},
        "sucursales": {"_id_"},
        "farmaceuticos": {"_id_", "matricula_1"},
        "proveedores": {"_id_", "cuit_1"},
        "productos": {"_id_"},
        "recetas": {"_id_", "id_cliente_1_fecha_emision_1", "tipo_1_estado_1_proxima_dispensa_1"},
        "ventas": {"_id_", "id_cliente_1_fecha_1", "id_farmaceutico_1_fecha_1", "fecha_1"},
        "contadores": {"_id_"},
    }


@pytest.mark.parametrize("coleccion, campo", UNICOS)
def test_indice_unico_rechaza_el_duplicado(datos_provistos, db, coleccion, campo):
    existente = db[coleccion].find_one()
    with pytest.raises(DuplicateKeyError):
        db[coleccion].insert_one({"_id": "NUEVO", campo: existente[campo]})
    assert db[coleccion].count_documents({}) == CONTEOS[coleccion]


def test_volver_a_cargar_restaura_el_estado(datos_provistos, db, r):
    mongo, redis_ = fotos()
    alterar_motores(db, r)
    assert snapshots.mongo_snap() != mongo
    assert snapshots.redis_snap() != redis_
    carga.cargar(solo_provistos=True)
    assert snapshots.mongo_snap() == mongo
    assert snapshots.redis_snap() == redis_


def test_volver_a_cargar_restaura_indices_contadores_y_altas(datos_provistos, db, r):
    mongo, redis_ = fotos()
    db.clientes.drop_index("dni_1")
    db.clientes.insert_one({"_id": "C009", "dni": "30111222"})
    db.contadores.update_one({"_id": "clientes"}, {"$set": {"ultimo": 9}})
    db.ventas.update_one({"_id": "V011"}, {"$set": {"stock_descontado": True, "consumos": []}})
    r.hset(claves.lote("L999"), "unidades", 1)
    assert snapshots.mongo_snap() != mongo
    assert snapshots.redis_snap() != redis_
    carga.cargar(solo_provistos=True)
    assert snapshots.mongo_snap() == mongo
    assert snapshots.redis_snap() == redis_


def test_cargar_devuelve_los_conteos(copia):
    assert carga.cargar() == RESULTADO
    assert carga.cargar(solo_provistos=True) == RESULTADO


def test_validar_provistos_sin_errores():
    assert carga.validar(True) == []


def test_total_corrupto_no_escribe_en_ningun_motor(copia, db, r):
    carga.cargar(solo_provistos=True)
    alterar_motores(db, r)
    corromper_total(copia)
    antes = fotos()
    for argumentos in ({}, {"solo_provistos": True}):
        with pytest.raises(ValidacionError) as e:
            carga.cargar(**argumentos)
        assert e.value.codigo == "DATO_INVALIDO"
        assert "ventas.csv V001: [total] 3851" in e.value.mensaje
    assert fotos() == antes


def test_comando_validar_con_total_corrupto(copia, capsys):
    corromper_total(copia)
    assert main(["carga", "--validar"]) == 1
    salida = capsys.readouterr()
    assert "[total]" in salida.err
    assert "DATO_INVALIDO" in salida.err
    assert salida.out == ""


def test_comando_carga_con_total_corrupto_no_escribe(copia, capsys, db, r):
    carga.cargar(solo_provistos=True)
    alterar_motores(db, r)
    corromper_total(copia)
    antes = fotos()
    assert main(["carga"]) == 1
    assert "[total]" in capsys.readouterr().err
    assert fotos() == antes


def test_comando_validar_sin_errores_no_escribe(copia, capsys, db, r):
    carga.cargar(solo_provistos=True)
    alterar_motores(db, r)
    antes = fotos()
    assert main(["carga", "--validar"]) == 0
    salida = capsys.readouterr()
    assert salida.out.strip() == "[]"
    assert salida.err == ""
    assert fotos() == antes


def test_adicionales_se_suman(con_adicionales, db, r):
    filas = lector.leer_todo()
    assert len(filas["clientes"]) == 9
    assert len(filas["detalle_ventas"]) == 23
    assert filas["sucursales"] == lector.leer_todo(True)["sucursales"]
    assert carga.validar() == []
    assert carga.cargar() == {"mongo": {**CONTEOS, "clientes": 9, "ventas": 17}, "redis": {"lotes": 19}}
    assert list(db.contadores.find(sort=[("_id", 1)])) == [
        {"_id": "clientes", "ultimo": 9}, {"_id": "detalle_ventas", "ultimo": 23}, {"_id": "ventas", "ultimo": 17}]
    venta = db.ventas.find_one({"_id": "V017"})
    assert venta["stock_descontado"] is True
    assert [i["id_detalle"] for i in venta["items"]] == ["D023"]
    assert r.hget("lote:L019", "unidades") == "10"
    assert r.zrange("stock:S001:PRD001", 0, -1) == ["L001", "L019"]


def test_contadores_toman_el_mayor_sufijo(copia, db):
    filas = {
        "clientes": ["C120,Ana,Sosa,30111222,ana.s@gmail.com,1140001111,Buenos Aires,Buenos Aires,OSDE,OS-999001,True",
                     "C010,Juan,Paz,30111333,juan.p@gmail.com,1140002222,Buenos Aires,Buenos Aires,PAMI,PA-999002,True"],
        "ventas": ["V1000,C120,F001,,2026-10-20,Venta libre,Efectivo,2800,Completada",
                   "V999,C010,F001,,2026-10-21,Venta libre,Efectivo,2800,Completada"],
        "detalle_ventas": ["D1000,V1000,PRD001,1,2800", "D999,V999,PRD001,1,2800"],
    }
    for archivo, lineas in filas.items():
        encabezado = (copia / "provistos" / f"{archivo}.csv").read_text(encoding="utf-8").splitlines()[0]
        (copia / "adicionales" / f"{archivo}.csv").write_text("\n".join([encabezado, *lineas]) + "\n",
                                                              encoding="utf-8")
    assert carga.validar() == []
    carga.cargar()
    assert list(db.contadores.find(sort=[("_id", 1)])) == [
        {"_id": "clientes", "ultimo": 120}, {"_id": "detalle_ventas", "ultimo": 1000},
        {"_id": "ventas", "ultimo": 1000}]


def cargar_estas_filas(monkeypatch, filas):
    """Hace que la carga tome estas filas en lugar de leer los CSV, donde un provisto sin filas se rechaza."""
    monkeypatch.setattr(lector, "leer_todo", lambda *_: filas)


def test_sin_filas_se_carga_vacio_y_los_contadores_quedan_en_cero(db, r, monkeypatch):
    cargar_estas_filas(monkeypatch, {archivo: [] for archivo in lector.ARCHIVOS})
    assert carga.validar(True) == []
    assert carga.cargar(solo_provistos=True) == {"mongo": {**dict.fromkeys(CONTEOS, 0), "contadores": 3},
                                                 "redis": {"lotes": 0}}
    assert {c: db[c].count_documents({}) for c in PK} == dict.fromkeys(PK, 0)
    assert list(db.contadores.find(sort=[("_id", 1)])) == [
        {"_id": "clientes", "ultimo": 0}, {"_id": "detalle_ventas", "ultimo": 0}, {"_id": "ventas", "ultimo": 0}]
    assert not r.exists(SET_ANTERIOR, claves.UNIDADES)
    assert ids.siguiente_id("clientes", "C") == "C001"


def test_sin_ventas_ni_detalle_los_contadores_de_ventas_quedan_en_cero(db, monkeypatch):
    filas = lector.leer_todo(True)
    filas["ventas"], filas["detalle_ventas"] = [], []
    # Sin ventas, ninguna receta puede tener dispensas.
    for receta in filas["recetas"]:
        receta.update(dispensas_realizadas=0, proxima_dispensa=None, estado="Vigente")
    cargar_estas_filas(monkeypatch, filas)
    assert carga.validar(True) == []
    assert carga.cargar(solo_provistos=True)["mongo"] == {**CONTEOS, "ventas": 0}
    assert list(db.contadores.find(sort=[("_id", 1)])) == [
        {"_id": "clientes", "ultimo": 8}, {"_id": "detalle_ventas", "ultimo": 0}, {"_id": "ventas", "ultimo": 0}]
    assert db.recetas.count_documents({"estado": "Vigente", "dispensas_realizadas": 0}) == CONTEOS["recetas"]


def test_solo_provistos_ignora_adicionales(con_adicionales, capsys, db, r):
    assert len(lector.leer_todo(True)["clientes"]) == 8
    assert main(["carga"]) == 0
    assert json.loads(capsys.readouterr().out)["mongo"]["clientes"] == 9
    assert main(["carga", "--solo-provistos"]) == 0
    assert json.loads(capsys.readouterr().out) == RESULTADO
    assert db.clientes.find_one({"_id": "C009"}) is None
    assert not r.exists("lote:L019")


def test_validar_con_adicional_corrupto(con_adicionales, capsys):
    reemplazar(con_adicionales / "adicionales" / "ventas.csv", "Efectivo,2800", "Efectivo,2801")
    assert main(["carga", "--validar"]) == 1
    assert "ventas.csv V017: [total]" in capsys.readouterr().err
    assert main(["carga", "--validar", "--solo-provistos"]) == 0
    assert capsys.readouterr().out.strip() == "[]"


def test_id_repetido_entre_carpetas_se_conserva_y_se_informa(copia):
    shutil.copy(copia / "provistos" / "clientes.csv", copia / "adicionales" / "clientes.csv")
    assert len(lector.leer_todo()["clientes"]) == 16
    assert any(e.startswith("clientes.csv C001: [id-repetido]") for e in carga.validar())
    assert carga.validar(True) == []


def test_ruta_de_los_datos_no_depende_del_directorio_actual(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert lector.DATOS.is_absolute()
    assert len(lector.leer_todo(True)["clientes"]) == 8
    assert carga.validar(True) == []
    assert carga.cargar(solo_provistos=True) == RESULTADO
    assert main(["carga", "--validar", "--solo-provistos"]) == 0
    assert capsys.readouterr().out.strip() == "[]"
