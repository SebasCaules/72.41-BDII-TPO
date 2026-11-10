import datetime
import json

import pytest

from farmared import demo, demo_servicios, fechas
from farmared.consultas import q01_productos_activos, q13_abm_clientes, q14_registrar_venta
from farmared.errores import FarmaRedError

HOY = datetime.date(2026, 11, 3)
NOMBRES = [f"q{n:02d}" for n in range(1, 16)]
PARAMETROS = {"q03": {"id_cliente": "C001"}, "q05": {"dias": 60}, "q07": {"limite": 5}, "q08": {"umbral": 50},
              "q09": {"monto": 5000}, "q10": {"id_sucursal": "S001"}}


@pytest.fixture(scope="module")
def generados(tmp_path_factory):
    destino = tmp_path_factory.mktemp("resultados")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fechas, "hoy", lambda: HOY)
        rutas = demo.ejecutar(destino)
    return destino, rutas


@pytest.fixture(scope="module")
def archivos(generados):
    destino, _ = generados
    return {n: json.loads((destino / f"{n}.json").read_text(encoding="utf-8")) for n in NOMBRES}


def escenarios(archivo):
    return {e["escenario"]: e for e in archivo["resultado"]}


def lotes(estado):
    return {lote["id_lote"]: lote["unidades"] for lote in estado["lotes"]}


def test_escribe_los_quince_archivos(generados):
    destino, rutas = generados
    assert rutas == [str(destino / f"{n}.json") for n in NOMBRES]
    assert sorted(p.name for p in destino.iterdir()) == [f"{n}.json" for n in NOMBRES]


def test_forma_de_cada_archivo(archivos):
    for nombre, archivo in archivos.items():
        assert list(archivo) == ["generado", "parametros", "resultado"], nombre
        assert archivo["generado"] == "2026-11-03"
        assert isinstance(archivo["parametros"], dict)
        assert isinstance(archivo["resultado"], list)


def test_parametros_de_ejemplo(archivos):
    for nombre in NOMBRES[:12]:
        assert archivos[nombre]["parametros"] == PARAMETROS.get(nombre, {}), nombre


def test_consultas_con_datos_completos(archivos):
    def ids(nombre, clave):
        return [e[clave] for e in archivos[nombre]["resultado"]]

    assert len(archivos["q01"]["resultado"]) == 20
    assert ids("q02", "id_venta") == ["V012", "V011", "V025", "V024", "V023"]
    assert ids("q03", "id") == ["RC001", "V003", "V015", "V013", "RC008", "V010"]
    assert [(e["id_cliente"], e["cantidad_recetas"]) for e in archivos["q04"]["resultado"]] == [
        ("C014", 3), ("C001", 2), ("C002", 2), ("C006", 2)]
    assert ids("q06", "id_receta") == ["RC002", "RC003", "RC004", "RC011"]
    assert ids("q07", "id_producto") == ["PRD005", "PRD011", "PRD001", "PRD004", "PRD009"]
    assert ids("q09", "id_venta") == ["V013", "V014", "V030", "V025", "V031"]
    assert [(e["id_cliente"], e["cantidad_ventas"]) for e in archivos["q10"]["resultado"]] == [("C001", 3), ("C006", 4)]
    assert ids("q12", "id_cliente") == ["C004", "C008", "C009", "C010", "C011", "C012", "C018"]


def test_claves_en_el_orden_documentado(archivos):
    assert list(archivos["q02"]["resultado"][0]) == ["id_venta", "fecha", "id_cliente", "tipo", "total",
                                                     "farmaceutico", "sucursal"]
    assert list(archivos["q01"]["resultado"][0])[0] == "id_producto"
    assert list(archivos["q01"]["resultado"][0]["proveedor"])[0] == "id_proveedor"
    assert list(archivos["q12"]["resultado"][0]["ultima_venta"]) == ["id_venta", "fecha", "estado", "total"]


def test_servicios_tienen_antes_despues_y_resultado_o_error(archivos):
    for nombre in ("q13", "q14", "q15"):
        archivo = archivos[nombre]
        assert list(archivo["parametros"]) == [e["escenario"] for e in archivo["resultado"]]
        for e in archivo["resultado"]:
            assert set(e) in ({"escenario", "antes", "despues", "resultado"},
                              {"escenario", "antes", "despues", "error"}), e["escenario"]
            if "error" in e:
                assert e["antes"] == e["despues"], e["escenario"]


def test_q13(archivos):
    alta, modificacion, baja, repetido = archivos["q13"]["resultado"]
    assert alta["antes"] == {"clientes_con_dni": [], "contadores": {"clientes": 22}}
    assert alta["resultado"]["id_cliente"] == "C023" and alta["resultado"]["activo"] is True
    assert alta["despues"] == {"clientes_con_dni": [alta["resultado"]], "contadores": {"clientes": 23}}
    cliente = modificacion["despues"]["clientes_con_dni"][0]
    assert (cliente["email"], cliente["obra_social"], cliente["nro_afiliado"]) == (
        "vquiroga@hotmail.com", "OSDE", "OS-993004")
    assert baja["despues"]["clientes_con_dni"][0]["activo"] is False
    assert repetido["error"]["codigo"] == "DNI_DUPLICADO"
    assert repetido["despues"]["contadores"] == {"clientes": 23}
    # El rechazo usa el mismo DNI del alta, el del cliente recién dado de baja, y no crea a nadie.
    entrada = archivos["q13"]["parametros"][repetido["escenario"]]
    assert (entrada["dni"], entrada["nombre"]) == ("99300400", "Valentina")
    assert archivos["q13"]["parametros"]["alta"]["dni"] == "99300400"
    assert [(c["id_cliente"], c["activo"]) for c in repetido["antes"]["clientes_con_dni"]] == [("C023", False)]
    assert [(c["id_cliente"], c["activo"]) for c in repetido["despues"]["clientes_con_dni"]] == [("C023", False)]


def test_q14(archivos):
    exitosa, intermedia, inactivo, vencido = archivos["q14"]["resultado"]
    venta = exitosa["resultado"]["venta"]
    assert venta["id_venta"] == "V032" and venta["total"] == 6200 and venta["fecha"] == "2026-11-03"
    assert venta["items"] == [{"id_detalle": "D040", "id_producto": "PRD004", "cantidad": 1, "precio_unit": 6200}]
    assert exitosa["despues"]["venta_nueva"] == venta
    assert (exitosa["antes"]["venta_nueva"], lotes(exitosa["antes"]), lotes(exitosa["despues"])) == (
        None, {"L007": 22}, {"L007": 21})
    receta = exitosa["despues"]["receta"]
    assert (receta["dispensas_realizadas"], receta["estado"], receta["proxima_dispensa"]) == (3, "Completada", None)
    assert exitosa["despues"]["contadores"] == {"detalle_ventas": 40, "ventas": 32}

    receta = intermedia["despues"]["receta"]
    assert (receta["dispensas_realizadas"], receta["estado"], receta["proxima_dispensa"]) == (2, "Vigente",
                                                                                             "2026-12-03")
    assert intermedia["resultado"]["venta"]["id_venta"] == "V033"
    assert lotes(intermedia["despues"]) == {"L005": 39, "L015": 100}
    # Los lotes se listan por vencimiento, del más próximo al más lejano.
    assert [(l["id_lote"], l["vencimiento"]) for l in intermedia["antes"]["lotes"]] == [
        ("L005", "2026-11-30"), ("L015", "2027-06-30")]
    assert [l["id_lote"] for l in intermedia["despues"]["lotes"]] == ["L005", "L015"]

    parametros = archivos["q14"]["parametros"]
    assert parametros[exitosa["escenario"]] == {
        "id_cliente": "C003", "id_farmaceutico": "F006", "items": [{"id_producto": "PRD004", "cantidad": 1}],
        "medio_pago": "Obra social", "id_receta": "RC002"}
    assert parametros[intermedia["escenario"]]["id_receta"] == "RC004"
    assert parametros[inactivo["escenario"]]["id_cliente"] == "C008"
    assert (inactivo["antes"]["cliente"]["id_cliente"], inactivo["antes"]["cliente"]["activo"]) == ("C008", False)
    entrada = parametros[vencido["escenario"]]
    assert (entrada["id_cliente"], entrada["id_farmaceutico"], entrada["items"], entrada["id_receta"]) == (
        "C007", "F003", [{"id_producto": "PRD010", "cantidad": 1}], "RC006")

    assert inactivo["error"]["codigo"] == "CLIENTE_INACTIVO"
    assert vencido["error"]["codigo"] == "STOCK_INSUFICIENTE"
    assert lotes(vencido["antes"]) == {"L012": 30}
    assert vencido["despues"]["receta"]["dispensas_realizadas"] == 0
    assert vencido["despues"]["contadores"] == {"detalle_ventas": 41, "ventas": 33}


def test_q15(archivos):
    importada, repetida, pendiente = archivos["q15"]["resultado"]
    insertada = archivos["q15"]["parametros"][importada["escenario"]]["venta_insertada"]
    assert (insertada["id_cliente"], insertada["id_farmaceutico"], insertada["total"]) == ("C005", "F001", 3500)
    assert importada["antes"]["venta"]["stock_descontado"] is False
    assert importada["despues"]["venta"]["stock_descontado"] is True
    assert (lotes(importada["antes"]), lotes(importada["despues"])) == ({"L004": 90}, {"L004": 89})
    assert importada["resultado"]["consumos"] == [{"id_lote": "L004", "id_producto": "PRD002", "unidades": 1}]
    assert repetida["error"]["codigo"] == "STOCK_YA_DESCONTADO"
    assert archivos["q15"]["parametros"][repetida["escenario"]] == {"id_venta": insertada["id_venta"]}
    assert pendiente["error"]["codigo"] == "VENTA_NO_COMPLETADA"
    assert archivos["q15"]["parametros"][pendiente["escenario"]] == {"id_venta": "V012"}
    assert pendiente["antes"]["venta"] == {"id_venta": "V012", "estado": "Pendiente", "stock_descontado": False}


def test_el_despues_de_un_rechazo_se_mide_otra_vez():
    lecturas = iter(["antes", "despues"])

    def rechazo():
        raise FarmaRedError("CODIGO", "mensaje")

    escenario = demo_servicios._escenario("rechazo", lambda: next(lecturas), rechazo)
    assert escenario == {"escenario": "rechazo", "antes": "antes", "despues": "despues",
                         "error": {"codigo": "CODIGO", "mensaje": "mensaje"}}


@pytest.mark.parametrize("excepcion", [NotImplementedError, RuntimeError])
def test_si_una_consulta_falla_la_demo_se_corta_sin_omitirla(tmp_path, monkeypatch, excepcion):
    def falla(*args, **kwargs):
        raise excepcion

    monkeypatch.setattr(q01_productos_activos, "productos_activos_con_proveedor", falla)
    with pytest.raises(excepcion):
        demo.ejecutar(tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("excepcion", [NotImplementedError, RuntimeError])
def test_si_un_servicio_falla_la_demo_se_corta_sin_omitirlo(datos_completos, tmp_path, monkeypatch, excepcion):
    def falla(*args, **kwargs):
        raise excepcion

    monkeypatch.setattr(q13_abm_clientes, "alta_cliente", falla)
    with pytest.raises(excepcion):
        demo_servicios.ejecutar(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_los_servicios_parten_de_los_datos_recargados(datos_completos, tmp_path):
    q14_registrar_venta.registrar_venta(**demo_servicios.VENTAS[0][1])
    assert demo_servicios.ejecutar(tmp_path) == [str(tmp_path / f"{n}.json") for n in ("q13", "q14", "q15")]
    exitosa = json.loads((tmp_path / "q14.json").read_text(encoding="utf-8"))["resultado"][0]
    assert exitosa["antes"]["contadores"] == {"detalle_ventas": 39, "ventas": 31}
    assert lotes(exitosa["antes"]) == {"L007": 22}
