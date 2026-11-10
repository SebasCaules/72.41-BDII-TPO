import datetime
import shutil

import pytest

import snapshots
from farmared import carga
from farmared.__main__ import main
from farmared.carga import lector
from farmared.errores import ValidacionError

PROVISTOS = lector.DATOS / "provistos"
COLUMNAS_FECHA = ["fecha", "fecha_emision", "proxima_dispensa", "vencimiento"]


@pytest.fixture(scope="module", autouse=True)
def base_con_provistos_al_terminar():
    yield
    carga.cargar(solo_provistos=True)


@pytest.fixture
def copia(tmp_path, monkeypatch):
    """Los provistos y una carpeta de adicionales vacía, fuera del repositorio."""
    shutil.copytree(PROVISTOS, tmp_path / "provistos")
    (tmp_path / "adicionales").mkdir()
    monkeypatch.setattr(lector, "DATOS", tmp_path)
    return tmp_path


def reemplazar(ruta, desde, hacia):
    texto = ruta.read_text(encoding="utf-8")
    assert texto.count(desde) == 1, desde
    ruta.write_text(texto.replace(desde, hacia), encoding="utf-8")


def fotos():
    return snapshots.mongo_snap(), snapshots.redis_snap()


def rechazo_de_validar(solo_provistos=True):
    with pytest.raises(ValidacionError) as e:
        carga.validar(solo_provistos)
    assert e.value.codigo == "DATO_INVALIDO"
    return e.value.mensaje


# Enteros: solo dígitos ASCII, con un signo menos opcional

@pytest.mark.parametrize("texto", [" 12 ", "12 ", "+12", "1_000", "١٢", "１２", "0x10", "1e3", "12.0", "-"])
def test_entero_con_otra_forma_que_la_de_digitos_es_invalido(texto):
    with pytest.raises(ValueError) as e:
        lector.valor("unidades", texto)
    assert str(e.value) == f"unidades: entero inválido {texto!r}"


@pytest.mark.parametrize("texto,numero", [("0", 0), ("12", 12), ("-5", -5), ("4000", 4000)])
def test_entero_de_digitos(texto, numero):
    assert lector.valor("unidades", texto) == numero


@pytest.mark.parametrize("hacia", ["+35", " 35", "3_5", "٣٥"])
def test_unidades_con_otra_forma_detienen_la_carga(copia, hacia):
    reemplazar(copia / "provistos" / "stock_lotes.csv", "L-2501A,35,", f"L-2501A,{hacia},")
    assert rechazo_de_validar() == f"provistos/stock_lotes.csv línea 3: unidades: entero inválido {hacia!r}"


def test_unidades_hasta_2_a_la_53():
    # Las unidades son además el puntaje de un zset de Redis, un double: pasado 2^53 ya no es exacto.
    assert lector.valor("unidades", str(2**53)) == 2**53
    with pytest.raises(ValueError, match=r"^unidades: entero inválido '9007199254740993'$"):
        lector.valor("unidades", str(2**53 + 1))
    assert lector.valor("precio_unit", str(2**53 + 1)) == 2**53 + 1


def test_unidades_mayores_que_2_a_la_53_detienen_la_carga(copia, db, r):
    carga.cargar(solo_provistos=True)
    antes = fotos()
    reemplazar(copia / "provistos" / "stock_lotes.csv", "L-2501A,120,", f"L-2501A,{2**53 + 1},")
    mensaje = f"provistos/stock_lotes.csv línea 2: unidades: entero inválido '{2**53 + 1}'"
    assert rechazo_de_validar() == mensaje
    with pytest.raises(ValidacionError, match=f"^{mensaje}$"):
        carga.cargar(solo_provistos=True)
    assert fotos() == antes


# Fechas: AAAA-MM-DD con ceros, de 1900 a 2099, igual en todas las columnas de fecha

@pytest.mark.parametrize("columna", COLUMNAS_FECHA)
@pytest.mark.parametrize("texto", ["2026-1-5", "2026-01-5", "0001-01-01", "1899-12-31", "2100-01-01", "02026-01-05",
                                   "２０２６-01-05"])
def test_fecha_con_otra_forma_o_fuera_de_rango_es_invalida(columna, texto):
    with pytest.raises(ValueError) as e:
        lector.valor(columna, texto)
    assert str(e.value) == f"{columna}: fecha inválida {texto!r}"


@pytest.mark.parametrize("texto", ["1900-01-01", "2026-01-05", "2099-12-31"])
def test_fecha_valida_en_todas_las_columnas_de_fecha(texto):
    assert lector.valor("fecha", texto) == datetime.datetime.strptime(texto, "%Y-%m-%d")
    assert lector.valor("vencimiento", texto) == texto


@pytest.mark.parametrize("hacia", ["2026-1-5", "0001-01-01"])
def test_fecha_de_venta_con_otra_forma_detiene_la_carga(copia, hacia):
    reemplazar(copia / "provistos" / "ventas.csv", "V002,C005,F005,,2025-06-24,", f"V002,C005,F005,,{hacia},")
    assert rechazo_de_validar() == f"provistos/ventas.csv línea 3: fecha: fecha inválida {hacia!r}"


# Textos

@pytest.mark.parametrize("texto", ["Hu\x00go", "Hu\tgo", "Hugo\r", "Hu\x7fgo", "Hu\x85go"])
def test_texto_con_caracteres_de_control_es_invalido(texto):
    with pytest.raises(ValueError) as e:
        lector.valor("nombre", texto)
    assert str(e.value) == f"nombre: carácter de control en {texto!r}"


def test_byte_nul_en_un_nombre_detiene_la_carga(copia):
    ruta = copia / "provistos" / "clientes.csv"
    ruta.write_bytes(ruta.read_bytes().replace(b"Hugo", b"Hu\x00go"))
    assert rechazo_de_validar() == "provistos/clientes.csv línea 9: nombre: carácter de control en 'Hu\\x00go'"


@pytest.mark.parametrize("texto", [" ", "   ", "\t "])
def test_valor_en_blanco_es_un_vacio(texto):
    assert lector.valor("nombre", texto) is None


def test_nombre_de_solo_espacios_es_obligatorio_vacio(copia):
    reemplazar(copia / "provistos" / "clientes.csv", "C001,Lucía,", "C001,   ,")
    assert carga.validar(True) == ["clientes.csv C001: [obligatorio] nombre vacío"]


# Archivos y carpetas

@pytest.mark.parametrize("archivo", lector.ARCHIVOS)
@pytest.mark.parametrize("sobra", [None, "", "\n\n"], ids=["sin-bytes", "solo-encabezado", "lineas-en-blanco"])
def test_provisto_sin_filas_detiene_la_carga(copia, archivo, sobra):
    ruta = copia / "provistos" / f"{archivo}.csv"
    encabezado = ruta.read_text(encoding="utf-8").splitlines()[0] + "\n"
    ruta.write_text("" if sobra is None else encabezado + sobra, encoding="utf-8")
    mensaje = f"provistos/{archivo}.csv: no tiene filas"
    assert rechazo_de_validar(True) == mensaje
    assert rechazo_de_validar(False) == mensaje


def test_stock_provisto_vacio_no_llega_a_ningun_motor(copia, capsys, db, r):
    carga.cargar(solo_provistos=True)
    antes = fotos()
    (copia / "provistos" / "stock_lotes.csv").write_bytes(b"")
    for argumentos in (["carga"], ["carga", "--solo-provistos"], ["carga", "--validar"]):
        assert main(argumentos) == 1
        salida = capsys.readouterr()
        assert (salida.out, salida.err) == ("", "Error [DATO_INVALIDO]: provistos/stock_lotes.csv: no tiene filas\n")
    assert fotos() == antes


def test_adicional_sin_filas_es_valido(copia):
    encabezado = (copia / "provistos" / "stock_lotes.csv").read_text(encoding="utf-8").splitlines()[0]
    (copia / "adicionales" / "stock_lotes.csv").write_text(encabezado + "\n", encoding="utf-8")
    (copia / "adicionales" / "ventas.csv").write_text("", encoding="utf-8")
    assert carga.validar() == []


@pytest.mark.parametrize("como", ["sin-carpeta", "archivo"])
def test_sin_la_carpeta_adicionales_la_carga_completa_se_rechaza(copia, capsys, db, r, como):
    carga.cargar(solo_provistos=True)
    antes = fotos()
    (copia / "adicionales").rmdir()
    if como == "archivo":
        (copia / "adicionales").write_text("", encoding="utf-8")
    mensaje = "adicionales: falta la carpeta; para cargar solo los provistos, usar --solo-provistos"
    assert rechazo_de_validar(False) == mensaje
    assert main(["carga"]) == 1
    assert capsys.readouterr().err == f"Error [DATO_INVALIDO]: {mensaje}\n"
    assert fotos() == antes
    assert carga.validar(True) == []
    assert main(["carga", "--solo-provistos"]) == 0
