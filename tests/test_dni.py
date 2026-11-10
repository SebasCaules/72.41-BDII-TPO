import csv
import pathlib
import shutil
import subprocess
import sys

import pytest

import snapshots
from farmared import carga
from farmared.carga import lector
from farmared.consultas import q13_abm_clientes as q13
from farmared.dominio import normalizar_dni
from farmared.errores import FarmaRedError, ValidacionError

RAIZ = pathlib.Path(__file__).resolve().parent.parent
DATOS = {"nombre": "Paula", "apellido": "Sosa", "dni": "99100200", "email": "paula.sosa@gmail.com",
         "telefono": "1144556677", "ciudad": "La Plata", "provincia": "Buenos Aires", "obra_social": "OSDE",
         "nro_afiliado": "OS-990001"}
DNI_C001 = "31245678"
ENCABEZADO = "id_cliente,nombre,apellido,dni,email,telefono,ciudad,provincia,obra_social,nro_afiliado,activo"
CLIENTE_NUEVO = "C009,Ana,Sosa,{dni},ana.s@gmail.com,1140001111,Buenos Aires,Buenos Aires,OSDE,OS-999001,True"
OTRAS_ESCRITURAS_C001 = ["31.245.678", "031245678", "031.245.678", "0031.245.678", " 31245678 "]
NO_SON_DNI = ["abc", "31-245-678", "31 245 678", "3.1245678", "31245.678", "31.245.678.", "123456789", "0", "000",
              "+31245678", "-31245678", "١٢٣٤٥٦٧٨", "31245678a"]


@pytest.fixture(scope="module", autouse=True)
def base_con_provistos_al_terminar():
    yield
    carga.cargar(solo_provistos=True)


def estado():
    return snapshots.mongo_snap(), snapshots.redis_snap()


def rechaza(codigo, funcion, *argumentos):
    antes = estado()
    with pytest.raises(FarmaRedError) as capturado:
        funcion(*argumentos)
    assert capturado.value.codigo == codigo
    assert estado() == antes
    return capturado.value


def correr_cli(*argumentos):
    return subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                          text=True, timeout=60)


# La regla

@pytest.mark.parametrize("texto,numero", [
    ("31245678", "31245678"), ("31.245.678", "31245678"), ("031245678", "31245678"), ("031.245.678", "31245678"),
    (" 31245678 ", "31245678"), ("1.234.567", "1234567"), ("7", "7"), ("00000007", "7"), ("99999999", "99999999"),
    ("0031.245.678", "31245678"), ("00000.007", "7"),
])
def test_normalizar_deja_solo_el_numero(texto, numero):
    assert normalizar_dni(texto) == numero


@pytest.mark.parametrize("texto", NO_SON_DNI + ["", "   "])
def test_normalizar_rechaza_lo_que_no_es_un_numero_de_documento(texto):
    assert normalizar_dni(texto) is None


# Alta

@pytest.mark.parametrize("dni", OTRAS_ESCRITURAS_C001)
def test_alta_con_el_dni_de_c001_escrito_de_otra_forma_se_rechaza(datos_provistos, dni):
    error = rechaza("DNI_DUPLICADO", q13.alta_cliente, {**DATOS, "dni": dni})
    assert error.mensaje == f"ya existe un cliente con DNI {DNI_C001}"


@pytest.mark.parametrize("dni", NO_SON_DNI)
def test_alta_con_un_dni_que_no_es_un_numero_de_documento_se_rechaza(datos_provistos, dni):
    error = rechaza("DATO_INVALIDO", q13.alta_cliente, {**DATOS, "dni": dni})
    assert error.mensaje.startswith(f"dni inválido: {dni.strip()}")


def test_alta_guarda_el_dni_solo_con_digitos(datos_provistos, db):
    cliente = q13.alta_cliente({**DATOS, "dni": "099.100.200"})
    assert cliente["dni"] == "99100200"
    assert db.clientes.find_one({"_id": cliente["id_cliente"]})["dni"] == "99100200"
    rechaza("DNI_DUPLICADO", q13.alta_cliente, {**DATOS, "dni": "99100200"})


def test_linea_de_comandos_alta_con_el_dni_de_c001_con_puntos(datos_provistos):
    antes = estado()
    salida = correr_cli("q13", "alta", "--nombre", "Ana", "--apellido", "Prueba", "--dni", "31.245.678", "--email",
                        "a@x.com", "--telefono", "1", "--ciudad", "CABA", "--provincia", "Buenos Aires",
                        "--obra-social", "Sin cobertura")
    assert (salida.returncode, salida.stdout) == (1, "")
    assert salida.stderr == f"Error [DNI_DUPLICADO]: ya existe un cliente con DNI {DNI_C001}\n"
    assert estado() == antes


# Carga

@pytest.fixture
def con_cliente_adicional(tmp_path, monkeypatch):
    """Copia los provistos y agrega en adicionales un cliente C009 con el DNI que se indique."""
    shutil.copytree(lector.DATOS / "provistos", tmp_path / "provistos")
    (tmp_path / "adicionales").mkdir()
    monkeypatch.setattr(lector, "DATOS", tmp_path)

    def escribir(dni):
        with open(tmp_path / "adicionales" / "clientes.csv", "w", newline="", encoding="utf-8") as f:
            f.write(f"{ENCABEZADO}\n")
            csv.writer(f).writerow(CLIENTE_NUEVO.format(dni=dni).split(","))
    return escribir


@pytest.mark.parametrize("dni", OTRAS_ESCRITURAS_C001 + ["31245678 "])
def test_carga_con_el_dni_de_c001_escrito_de_otra_forma_se_rechaza(con_cliente_adicional, dni):
    con_cliente_adicional(dni)
    assert carga.validar() == [f"clientes.csv C009: [clave-unica] dni {DNI_C001} repetido"]


@pytest.mark.parametrize("dni", NO_SON_DNI)
def test_carga_con_un_dni_que_no_es_un_numero_de_documento_se_rechaza(con_cliente_adicional, dni):
    con_cliente_adicional(dni)
    with pytest.raises(ValidacionError) as e:
        carga.validar()
    assert (e.value.codigo, e.value.mensaje) == (
        "DATO_INVALIDO", f"adicionales/clientes.csv línea 2: dni: número de documento inválido {dni!r}")


def test_carga_guarda_el_dni_solo_con_digitos(con_cliente_adicional, db):
    con_cliente_adicional("030.111.222")
    assert carga.validar() == []
    carga.cargar()
    assert db.clientes.find_one({"_id": "C009"})["dni"] == "30111222"


def test_los_dni_de_los_datos_ya_estan_normalizados():
    # Normalizar no cambia ningún dato: cada DNI leído es igual al texto del CSV.
    for carpeta in ("provistos", "adicionales"):
        with open(lector.DATOS / carpeta / "clientes.csv", newline="", encoding="utf-8-sig") as f:
            crudos = [fila["dni"] for fila in csv.DictReader(f)]
        assert crudos and all(normalizar_dni(dni) == dni for dni in crudos), carpeta
    assert len(lector.leer_todo()["clientes"]) == 22
