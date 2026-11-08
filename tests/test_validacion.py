import copy
import csv
import datetime
import re
import shutil

import pytest

from farmared import fechas
from farmared.carga import lector
from farmared.carga.validacion import CLAVES, PREFIJOS, REFERENCIAS, errores

ETIQUETAS = {"encabezado", "obligatorio", "id-repetido", "clave-unica", "referencia", "dominio", "afiliado", "total",
             "tipo-venta", "receta-cliente", "receta-requerida", "venta-en-farmacia", "dispensas", "receta-coherente",
             "receta-fecha", "formato-id", "rango", "fecha-futura"}
FORMATO = re.compile(r"^(?:%s)\.csv (?:fila \d+|\S+): \[([a-z-]+)\] \S.*$" % "|".join(CLAVES))
PROVISTOS = lector.DATOS / "provistos"


@pytest.fixture(scope="module")
def originales():
    return lector.leer_todo(True)


@pytest.fixture
def filas(originales):
    return copy.deepcopy(originales)


def fila(filas, archivo, id_):
    return next(f for f in filas[archivo] if f[CLAVES[archivo]] == id_)


def etiquetas(filas):
    encontrados = errores(filas)
    assert len(encontrados) == len(set(encontrados)), encontrados
    encontradas = set()
    for error in encontrados:
        coincidencia = FORMATO.match(error)
        assert coincidencia, error
        assert coincidencia.group(1) in ETIQUETAS, error
        encontradas.add(coincidencia.group(1))
    return encontradas


def fecha(texto):
    return datetime.datetime.strptime(texto, "%Y-%m-%d")


def test_los_provistos_son_validos(originales):
    assert errores(originales) == []


def test_encabezado_columna_faltante(filas):
    del fila(filas, "clientes", "C002")["email"]
    assert etiquetas(filas) == {"encabezado"}


def test_encabezado_columna_de_mas(filas):
    fila(filas, "clientes", "C002")[None] = ["sobra"]
    assert etiquetas(filas) == {"encabezado"}


def test_encabezado_otro_orden(filas):
    f = fila(filas, "sucursales", "S002")
    f["nombre"] = f.pop("nombre")
    assert etiquetas(filas) == {"encabezado"}
    assert errores(filas) == ["sucursales.csv S002: [encabezado] columnas distintas de las esperadas"]


@pytest.mark.parametrize("archivo,id_,campo", [
    ("clientes", "C002", "email"),
    ("sucursales", "S002", "direccion"),
    ("farmaceuticos", "F002", "nombre"),
    ("proveedores", "PRV002", "razon_social"),
    ("productos", "PRD002", "precio_unit"),
    ("stock_lotes", "L002", "vencimiento"),
    ("recetas", "RC003", "medico"),
    ("ventas", "V004", "medio_pago"),
    ("detalle_ventas", "D005", "cantidad"),
])
def test_obligatorio_columna_vacia(filas, archivo, id_, campo):
    fila(filas, archivo, id_)[campo] = None
    assert errores(filas) == [f"{archivo}.csv {id_}: [obligatorio] {campo} vacío"]


# Filas que ninguna otra referencia, salvo donde no hay ninguna así: toda sucursal y todo proveedor tienen filas que
# los referencian, y toda venta tiene ítems.
FILA_POR_ARCHIVO = {"clientes": "C008", "sucursales": "S001", "farmaceuticos": "F007", "proveedores": "PRV005",
                    "productos": "PRD013", "stock_lotes": "L001", "recetas": "RC009", "ventas": "V002",
                    "detalle_ventas": "D002"}
ENLACE_PERDIDO = {("sucursales", "id_sucursal"): "referencia", ("proveedores", "id_proveedor"): "referencia",
                  ("ventas", "id_venta"): "referencia", ("detalle_ventas", "id_venta"): "total"}
OPCIONALES = {("clientes", "nro_afiliado"), ("ventas", "id_receta"), ("recetas", "proxima_dispensa")}


@pytest.mark.parametrize("archivo", CLAVES)
def test_obligatorio_cada_columna_de_una_fila(originales, archivo):
    id_ = FILA_POR_ARCHIVO[archivo]
    columnas = [c for c in fila(originales, archivo, id_) if (archivo, c) not in OPCIONALES]
    assert CLAVES[archivo] in columnas
    for columna in columnas:
        filas = copy.deepcopy(originales)
        fila(filas, archivo, id_)[columna] = None
        enlace = {ENLACE_PERDIDO[archivo, columna]} if (archivo, columna) in ENLACE_PERDIDO else set()
        assert etiquetas(filas) == {"obligatorio"} | enlace, columna
        assert sum("[obligatorio]" in e for e in errores(filas)) == 1, columna


@pytest.mark.parametrize("archivo,id_,campo,esperadas", [
    ("clientes", "C001", "nro_afiliado", {"afiliado"}),
    ("ventas", "V011", "id_receta", {"tipo-venta", "receta-requerida"}),
    ("ventas", "V001", "id_receta", {"tipo-venta", "receta-requerida", "dispensas"}),
    ("recetas", "RC002", "proxima_dispensa", {"receta-coherente"}),
])
def test_obligatorio_no_alcanza_a_las_opcionales(filas, archivo, id_, campo, esperadas):
    fila(filas, archivo, id_)[campo] = None
    assert etiquetas(filas) == esperadas


def test_obligatorio_opcionales_vacias_en_los_provistos(originales):
    assert fila(originales, "clientes", "C005")["nro_afiliado"] is None
    assert fila(originales, "ventas", "V002")["id_receta"] is None
    assert fila(originales, "recetas", "RC001")["proxima_dispensa"] is None
    assert errores(originales) == []


def test_obligatorio_id_receta_es_opcional_solo_en_ventas(filas):
    fila(filas, "recetas", "RC009")["id_receta"] = None
    assert errores(filas) == ["recetas.csv fila 9: [obligatorio] id_receta vacío"]


def test_obligatorio_no_informa_la_columna_ausente(filas):
    del fila(filas, "stock_lotes", "L002")["vencimiento"]
    assert etiquetas(filas) == {"encabezado"}


@pytest.mark.parametrize("id_,cambios,detalle", [
    ("C005", {"nro_afiliado": "SC-1"}, "Sin cobertura con nro_afiliado SC-1"),
    ("C001", {"nro_afiliado": None}, "OSDE sin nro_afiliado"),
    ("C001", {"obra_social": "Sin cobertura"}, "Sin cobertura con nro_afiliado OS-310045"),
    ("C005", {"obra_social": "PAMI"}, "PAMI sin nro_afiliado"),
])
def test_afiliado(filas, id_, cambios, detalle):
    fila(filas, "clientes", id_).update(cambios)
    assert etiquetas(filas) == {"afiliado"}
    assert errores(filas) == [f"clientes.csv {id_}: [afiliado] {detalle}"]


@pytest.mark.parametrize("id_,obra_social,esperadas", [("C001", None, {"obligatorio"}), ("C005", None, {"obligatorio"}),
                                                       ("C001", "Otra", {"dominio"}), ("C005", "Otra", {"dominio"})])
def test_afiliado_calla_sin_obra_social_valida(filas, id_, obra_social, esperadas):
    fila(filas, "clientes", id_)["obra_social"] = obra_social
    assert etiquetas(filas) == esperadas


@pytest.mark.parametrize("archivo", CLAVES)
def test_id_repetido_fila_agregada_con_otros_campos(filas, archivo):
    clave = CLAVES[archivo]
    primera, segunda = filas[archivo][0], filas[archivo][1]
    agregada = {**segunda, clave: primera[clave]}
    for campo in ("dni", "matricula", "cuit"):
        if campo in agregada:
            agregada[campo] = "NUEVO"
    filas[archivo].append(agregada)
    assert errores(filas) == [f"{archivo}.csv {primera[clave]}: [id-repetido] id repetido"]


@pytest.mark.parametrize("cambios", [
    {},
    {"tipo": "Venta libre"},
    {"total": 1},
    {"id_cliente": "C002"},
    {"id_farmaceutico": "F007"},
    {"fecha": fecha("2026-09-09")},
    {"id_receta": None},
    {"estado": "Anulada"},
])
def test_id_repetido_venta_descartada_no_altera_otra_regla(filas, cambios):
    filas["ventas"].append({**fila(filas, "ventas", "V003"), **cambios})
    assert errores(filas) == ["ventas.csv V003: [id-repetido] id repetido"]


@pytest.mark.parametrize("cambios", [
    {"estado": "Vigente"},
    {"dispensas_autorizadas": 0},
    {"dispensas_realizadas": 9},
    {"proxima_dispensa": fecha("2026-12-01")},
])
def test_id_repetido_receta_descartada_no_altera_otra_regla(filas, cambios):
    filas["recetas"].append({**fila(filas, "recetas", "RC001"), **cambios})
    assert errores(filas) == ["recetas.csv RC001: [id-repetido] id repetido"]


def test_id_repetido_identico_tambien_repite_la_clave_unica(filas):
    cliente = fila(filas, "clientes", "C003")
    filas["clientes"].append(copy.deepcopy(cliente))
    assert errores(filas) == ["clientes.csv C003: [id-repetido] id repetido",
                              f"clientes.csv C003: [clave-unica] dni {cliente['dni']} repetido"]


def test_id_repetido_con_columna_obligatoria_vacia_la_informa(filas):
    filas["clientes"].append({**fila(filas, "clientes", "C001"), "dni": None})
    assert etiquetas(filas) == {"id-repetido", "obligatorio"}


def test_id_repetido_con_afiliado_incoherente_lo_informa(filas):
    filas["clientes"].append({**fila(filas, "clientes", "C001"), "dni": "NUEVO", "obra_social": "Sin cobertura"})
    assert etiquetas(filas) == {"id-repetido", "afiliado"}


def test_id_repetido_con_columna_faltante_informa_el_encabezado(filas):
    filas["clientes"].append({k: v for k, v in fila(filas, "clientes", "C001").items() if k not in ("email", "dni")})
    assert errores(filas) == ["clientes.csv C001: [encabezado] columnas distintas de las esperadas",
                              "clientes.csv C001: [id-repetido] id repetido"]


def test_id_repetido_con_referencia_y_dominio_invalidos_los_informa(filas):
    filas["farmaceuticos"].append({**fila(filas, "farmaceuticos", "F001"), "matricula": "MN-00000",
                                   "id_sucursal": "X999", "cargo": "Otro"})
    assert errores(filas) == ["farmaceuticos.csv F001: [id-repetido] id repetido",
                              "farmaceuticos.csv F001: [referencia] id_sucursal X999 inexistente",
                              "farmaceuticos.csv F001: [dominio] cargo Otro fuera de dominio"]


def agregar_venta_libre(filas, id_, total):
    filas["ventas"].append({**fila(filas, "ventas", "V002"), "id_venta": id_, "total": total})


def test_id_repetido_item_descartado_no_deja_la_venta_sin_items(filas):
    agregar_venta_libre(filas, "V017", 2800)
    filas["detalle_ventas"].append({"id_detalle": "D001", "id_venta": "V017", "id_producto": "PRD001",
                                    "cantidad": 1, "precio_unit": 2800})
    assert errores(filas) == ["detalle_ventas.csv D001: [id-repetido] id repetido"]


def test_id_repetido_item_descartado_no_desarma_la_suma(filas):
    agregar_venta_libre(filas, "V017", 3800)
    filas["detalle_ventas"] += [
        {"id_detalle": "D023", "id_venta": "V017", "id_producto": "PRD001", "cantidad": 1, "precio_unit": 2800},
        {"id_detalle": "D001", "id_venta": "V017", "id_producto": "PRD001", "cantidad": 1, "precio_unit": 1000},
    ]
    assert errores(filas) == ["detalle_ventas.csv D001: [id-repetido] id repetido"]


def test_id_repetido_item_descartado_pudo_ser_el_que_requeria_receta(filas):
    fila(filas, "detalle_ventas", "D004")["id_producto"] = "PRD001"
    filas["detalle_ventas"].append({"id_detalle": "D001", "id_venta": "V003", "id_producto": "PRD003",
                                    "cantidad": 1, "precio_unit": 9800})
    assert errores(filas) == ["detalle_ventas.csv D001: [id-repetido] id repetido"]


def test_id_repetido_venta_descartada_pudo_ser_la_dispensa_que_falta(filas):
    filas["ventas"].append({**fila(filas, "ventas", "V011"), "id_venta": "V001", "total": 1, "estado": "Completada"})
    fila(filas, "recetas", "RC006").update(dispensas_realizadas=1, estado="Completada")
    assert errores(filas) == ["ventas.csv V001: [id-repetido] id repetido"]


def test_id_repetido_venta_descartada_con_item_propio_no_acusa_a_la_original(filas):
    filas["ventas"].append({**fila(filas, "ventas", "V001"), "total": 3950})
    filas["detalle_ventas"].append({"id_detalle": "D023", "id_venta": "V001", "id_producto": "PRD001",
                                    "cantidad": 1, "precio_unit": 100})
    assert errores(filas) == ["ventas.csv V001: [id-repetido] id repetido"]


def test_id_repetido_item_descartado_no_oculta_la_receta_que_falta(filas):
    fila(filas, "detalle_ventas", "D002")["id_producto"] = "PRD003"
    filas["detalle_ventas"].append({"id_detalle": "D001", "id_venta": "V002", "id_producto": "PRD001",
                                    "cantidad": 1, "precio_unit": 100})
    assert errores(filas) == ["detalle_ventas.csv D001: [id-repetido] id repetido",
                              "ventas.csv V002: [receta-requerida] sin receta y con productos que la requieren"]


def test_id_repetido_la_incertidumbre_no_alcanza_a_otras_filas(filas):
    filas["detalle_ventas"].append({**fila(filas, "detalle_ventas", "D002"), "id_detalle": "D001"})
    filas["ventas"].append(copy.deepcopy(fila(filas, "ventas", "V003")))
    fila(filas, "ventas", "V001")["total"] = 5000
    fila(filas, "recetas", "RC006").update(dispensas_realizadas=1, estado="Completada")
    assert errores(filas) == ["ventas.csv V003: [id-repetido] id repetido",
                              "detalle_ventas.csv D001: [id-repetido] id repetido",
                              "ventas.csv V001: [total] 5000 ≠ suma de ítems 3850",
                              "recetas.csv RC006: [dispensas] 1 realizadas ≠ 0 ventas completadas"]


def test_id_vacio_aunque_sea_uno_solo(filas):
    fila(filas, "clientes", "C008")["id_cliente"] = None
    assert errores(filas) == ["clientes.csv fila 8: [obligatorio] id_cliente vacío"]


def test_id_vacio_en_detalle_no_altera_el_total(filas):
    fila(filas, "detalle_ventas", "D001")["id_detalle"] = None
    assert etiquetas(filas) == {"obligatorio"}


def test_id_vacio_en_venta_con_items_deja_su_detalle_sin_referencia_cascada_inherente(filas):
    fila(filas, "ventas", "V001")["id_venta"] = None
    assert errores(filas) == ["ventas.csv fila 1: [obligatorio] id_venta vacío",
                              "detalle_ventas.csv D001: [referencia] id_venta V001 inexistente"]


UNICAS = [("clientes", "C002", "dni", "31245678"), ("farmaceuticos", "F002", "matricula", "MN-18041"),
          ("proveedores", "PRV002", "cuit", "30-71234567-1")]


@pytest.mark.parametrize("archivo,id_,campo,repetido", UNICAS)
def test_clave_unica_valor_repetido(filas, archivo, id_, campo, repetido):
    fila(filas, archivo, id_)[campo] = repetido
    assert etiquetas(filas) == {"clave-unica"}


@pytest.mark.parametrize("archivo,id_,campo,repetido", UNICAS)
def test_clave_unica_ignora_los_vacios(filas, archivo, id_, campo, repetido):
    filas[archivo][0][campo] = None
    fila(filas, archivo, id_)[campo] = None
    assert etiquetas(filas) == {"obligatorio"}


@pytest.mark.parametrize("archivo,id_,campo", [
    ("farmaceuticos", "F001", "id_sucursal"),
    ("productos", "PRD001", "id_proveedor"),
    ("stock_lotes", "L001", "id_producto"),
    ("stock_lotes", "L001", "id_sucursal"),
    ("recetas", "RC001", "id_cliente"),
    ("ventas", "V003", "id_cliente"),
    ("ventas", "V003", "id_farmaceutico"),
    ("ventas", "V011", "id_receta"),
    ("detalle_ventas", "D004", "id_producto"),
])
def test_referencia_inexistente_sin_cascada(filas, archivo, id_, campo):
    fila(filas, archivo, id_)[campo] = "X999"
    assert etiquetas(filas) == {"referencia"}


@pytest.mark.parametrize("archivo,id_,campo", [
    ("farmaceuticos", "F001", "id_sucursal"),
    ("productos", "PRD001", "id_proveedor"),
    ("stock_lotes", "L001", "id_producto"),
    ("stock_lotes", "L001", "id_sucursal"),
    ("recetas", "RC001", "id_cliente"),
    ("ventas", "V003", "id_cliente"),
    ("ventas", "V003", "id_farmaceutico"),
    ("detalle_ventas", "D004", "id_producto"),
])
def test_referencia_vacia_solo_la_informa_obligatorio(filas, archivo, id_, campo):
    fila(filas, archivo, id_)[campo] = None
    assert errores(filas) == [f"{archivo}.csv {id_}: [obligatorio] {campo} vacío"]


def test_referencia_detalle_a_venta_inexistente_rompe_el_total_de_la_original_cascada_inherente(filas):
    fila(filas, "detalle_ventas", "D001")["id_venta"] = "X999"
    assert etiquetas(filas) == {"referencia", "total"}


def test_referencia_receta_inexistente_en_venta_completada_cambia_las_dispensas_cascada_inherente(filas):
    fila(filas, "ventas", "V003")["id_receta"] = "X999"
    assert etiquetas(filas) == {"referencia", "dispensas"}


def test_referencia_receta_inexistente_en_venta_libre_contradice_el_tipo_cascada_inherente(filas):
    fila(filas, "ventas", "V002")["id_receta"] = "X999"
    assert etiquetas(filas) == {"referencia", "tipo-venta"}


def test_referencia_id_receta_vacio_no_es_error(filas):
    assert fila(filas, "ventas", "V002")["id_receta"] is None
    assert errores(filas) == []


@pytest.mark.parametrize("valor", ["Otro", None])
@pytest.mark.parametrize("archivo,id_,campo", [
    ("clientes", "C001", "obra_social"),
    ("sucursales", "S001", "tipo"),
    ("farmaceuticos", "F001", "cargo"),
    ("proveedores", "PRV001", "tipo"),
    ("productos", "PRD003", "condicion_venta"),
    ("recetas", "RC001", "tipo"),
    ("recetas", "RC001", "estado"),
    ("recetas", "RC002", "tipo"),
    ("recetas", "RC002", "estado"),
    ("ventas", "V001", "tipo"),
    ("ventas", "V001", "medio_pago"),
    ("ventas", "V001", "estado"),
])
def test_dominio_sin_cascada(filas, archivo, id_, campo, valor):
    fila(filas, archivo, id_)[campo] = valor
    assert etiquetas(filas) == ({"dominio"} if valor else {"obligatorio"})


def test_total_distinto_de_la_suma(filas):
    fila(filas, "ventas", "V001")["total"] = 5000
    assert errores(filas) == ["ventas.csv V001: [total] 5000 ≠ suma de ítems 3850"]


def test_formato_literal_del_mensaje(filas):
    filas["ventas"].append({**fila(filas, "ventas", "V002"), "id_venta": "V023", "total": 5000})
    filas["detalle_ventas"].append({"id_detalle": "D023", "id_venta": "V023", "id_producto": "PRD011",
                                    "cantidad": 1, "precio_unit": 4800})
    assert errores(filas) == ["ventas.csv V023: [total] 5000 ≠ suma de ítems 4800"]


def test_total_suma_cantidad_por_precio_de_todos_los_items(filas):
    fila(filas, "detalle_ventas", "D002")["cantidad"] = 3
    assert errores(filas) == ["ventas.csv V002: [total] 5750 ≠ suma de ítems 7500"]


def test_total_venta_sin_items(filas):
    filas["detalle_ventas"] = [d for d in filas["detalle_ventas"] if d["id_venta"] != "V003"]
    assert errores(filas) == ["ventas.csv V003: [total] venta sin ítems"]


@pytest.mark.parametrize("archivo,id_,campo", [
    ("ventas", "V001", "total"),
    ("detalle_ventas", "D004", "cantidad"),
    ("detalle_ventas", "D004", "precio_unit"),
])
def test_total_con_valores_vacios_solo_informa_obligatorio(filas, archivo, id_, campo):
    fila(filas, archivo, id_)[campo] = None
    assert etiquetas(filas) == {"obligatorio"}


def test_tipo_venta_con_receta_sin_id_receta(filas):
    fila(filas, "ventas", "V002")["tipo"] = "Con receta"
    assert etiquetas(filas) == {"tipo-venta"}


def test_tipo_venta_libre_con_id_receta(filas):
    fila(filas, "ventas", "V003")["tipo"] = "Venta libre"
    assert etiquetas(filas) == {"tipo-venta"}


def test_receta_cliente_de_otro_cliente(filas):
    fila(filas, "ventas", "V011")["id_cliente"] = "C001"
    assert etiquetas(filas) == {"receta-cliente"}


def test_receta_requerida_con_receta_sin_producto_que_la_requiera(filas):
    fila(filas, "detalle_ventas", "D004")["id_producto"] = "PRD001"
    assert etiquetas(filas) == {"receta-requerida"}


def test_receta_requerida_sin_receta_con_producto_que_la_requiere(filas):
    fila(filas, "detalle_ventas", "D002")["id_producto"] = "PRD003"
    assert etiquetas(filas) == {"receta-requerida"}


def test_receta_requerida_vale_para_condicion_archivada(filas):
    fila(filas, "detalle_ventas", "D002")["id_producto"] = "PRD008"
    assert etiquetas(filas) == {"receta-requerida"}


def test_receta_requerida_basta_un_producto_de_varios(filas):
    assert fila(filas, "detalle_ventas", "D008")["id_venta"] == "V006"
    fila(filas, "detalle_ventas", "D008")["id_producto"] = "PRD001"
    assert errores(filas) == []


def test_receta_requerida_producto_inexistente_no_oculta_al_que_la_requiere(filas):
    fila(filas, "detalle_ventas", "D002")["id_producto"] = "PRD003"
    fila(filas, "detalle_ventas", "D003")["id_producto"] = "X999"
    assert errores(filas) == ["detalle_ventas.csv D003: [referencia] id_producto X999 inexistente",
                              "ventas.csv V002: [receta-requerida] sin receta y con productos que la requieren"]


def test_receta_requerida_con_receta_y_producto_inexistente_solo_informa_la_referencia(filas):
    fila(filas, "detalle_ventas", "D007")["id_producto"] = "PRD001"
    fila(filas, "detalle_ventas", "D008")["id_producto"] = "X999"
    assert errores(filas) == ["detalle_ventas.csv D008: [referencia] id_producto X999 inexistente"]


def test_receta_faltante_en_venta_con_producto_que_la_requiere_da_dos_hechos_cascada_inherente(filas):
    fila(filas, "ventas", "V011")["id_receta"] = None
    assert etiquetas(filas) == {"tipo-venta", "receta-requerida"}


def test_venta_en_farmacia_farmaceutico_de_drogueria(filas):
    fila(filas, "ventas", "V001")["id_farmaceutico"] = "F007"
    assert errores(filas) == ["ventas.csv V001: [venta-en-farmacia] F007 es de S005, que es Droguería"]


def test_venta_en_farmacia_sucursal_que_pasa_a_drogueria(filas):
    fila(filas, "sucursales", "S003")["tipo"] = "Droguería"
    assert etiquetas(filas) == {"venta-en-farmacia"}


def test_dispensas_realizadas_distintas_de_las_ventas_completadas(filas):
    fila(filas, "recetas", "RC002")["dispensas_realizadas"] = 1
    assert etiquetas(filas) == {"dispensas"}


@pytest.mark.parametrize("id_,estado", [("V011", "Completada"), ("V003", "Anulada"), ("V003", "Pendiente")])
def test_dispensas_cuentan_solo_las_ventas_completadas(filas, id_, estado):
    fila(filas, "ventas", id_)["estado"] = estado
    assert etiquetas(filas) == {"dispensas"}


def test_dispensas_realizadas_mayores_que_autorizadas(filas):
    fila(filas, "recetas", "RC002")["dispensas_autorizadas"] = 1
    assert errores(filas) == ["recetas.csv RC002: [dispensas] 2 realizadas > 1 autorizadas"]


def test_dispensas_venta_de_estado_invalido_no_saltea_el_limite_de_autorizadas(filas):
    fila(filas, "ventas", "V004")["estado"] = "Otro"
    fila(filas, "recetas", "RC002")["dispensas_autorizadas"] = 1
    assert errores(filas) == ["ventas.csv V004: [dominio] estado Otro fuera de dominio",
                              "recetas.csv RC002: [dispensas] 2 realizadas > 1 autorizadas"]


def test_dispensas_realizadas_vacias_solo_informa_obligatorio(filas):
    fila(filas, "recetas", "RC001")["dispensas_realizadas"] = None
    assert etiquetas(filas) == {"obligatorio"}


@pytest.mark.parametrize("id_,autorizadas", [("RC006", 2), ("RC006", 0), ("RC002", 4)])
def test_receta_coherente_dispensas_autorizadas_segun_tipo(filas, id_, autorizadas):
    fila(filas, "recetas", id_)["dispensas_autorizadas"] = autorizadas
    assert etiquetas(filas) == {"receta-coherente"}


def test_receta_coherente_cero_autorizadas_aun_estando_completada(filas):
    fila(filas, "recetas", "RC006").update(dispensas_autorizadas=0, estado="Completada")
    assert errores(filas) == ["recetas.csv RC006: [receta-coherente] Simple con 0 dispensas autorizadas"]


def test_receta_coherente_archivada_admite_una_sola(filas):
    fila(filas, "recetas", "RC006")["tipo"] = "Archivada"
    assert errores(filas) == []
    fila(filas, "recetas", "RC006")["dispensas_autorizadas"] = 2
    assert etiquetas(filas) == {"receta-coherente"}


def test_receta_coherente_completada_sin_todas_las_dispensas(filas):
    fila(filas, "recetas", "RC006")["estado"] = "Completada"
    assert errores(filas) == ["recetas.csv RC006: [receta-coherente] Completada con 0 de 1 dispensas"]


def test_receta_coherente_todas_las_dispensas_sin_estar_completada(filas):
    fila(filas, "recetas", "RC001")["estado"] = "Vigente"
    assert errores(filas) == ["recetas.csv RC001: [receta-coherente] Vigente con 1 de 1 dispensas"]


@pytest.mark.parametrize("id_", ["RC001", "RC006", "RC009"])
def test_receta_coherente_proxima_dispensa_que_no_corresponde(filas, id_):
    fila(filas, "recetas", id_)["proxima_dispensa"] = fecha("2026-12-01")
    assert errores(filas) == [f"recetas.csv {id_}: [receta-coherente] proxima_dispensa no corresponde"]


@pytest.mark.parametrize("id_,cambios", [
    ("RC002", {"estado": "Vencida"}),
    ("RC002", {"estado": "Completada", "dispensas_autorizadas": 2}),
    ("RC006", {"tipo": "Tratamiento prolongado", "dispensas_autorizadas": 3, "proxima_dispensa": fecha("2026-12-01")}),
])
def test_receta_coherente_tratamiento_prolongado_con_proxima_que_no_corresponde(filas, id_, cambios):
    fila(filas, "recetas", id_).update(cambios)
    assert errores(filas) == [f"recetas.csv {id_}: [receta-coherente] proxima_dispensa no corresponde"]


def test_receta_coherente_tratamiento_prolongado_sin_dispensas_no_lleva_proxima(filas):
    fila(filas, "recetas", "RC006").update(tipo="Tratamiento prolongado", dispensas_autorizadas=3)
    assert errores(filas) == []


def test_receta_coherente_falta_proxima_dispensa(filas):
    fila(filas, "recetas", "RC004")["proxima_dispensa"] = None
    assert errores(filas) == ["recetas.csv RC004: [receta-coherente] falta proxima_dispensa"]


def test_receta_fecha_anterior_a_la_emision(filas):
    fila(filas, "ventas", "V003")["fecha"] = fecha("2026-09-09")
    assert errores(filas) == ["ventas.csv V003: [receta-fecha] 2026-09-09 anterior a la receta 2026-09-10"]


def test_receta_fecha_igual_a_la_emision_es_valida(filas):
    assert fila(filas, "ventas", "V003")["fecha"] == fila(filas, "recetas", "RC001")["fecha_emision"]
    assert errores(filas) == []


@pytest.mark.parametrize("archivo,id_,campo", [("ventas", "V003", "fecha"), ("recetas", "RC001", "fecha_emision")])
def test_receta_fecha_con_fechas_vacias_solo_informa_obligatorio(filas, archivo, id_, campo):
    fila(filas, archivo, id_)[campo] = None
    assert etiquetas(filas) == {"obligatorio"}


def test_no_se_validan_actividad_treinta_dias_ni_stock(filas):
    fila(filas, "farmaceuticos", "F001")["activo"] = False
    fila(filas, "productos", "PRD001")["activo"] = False
    fila(filas, "recetas", "RC002")["proxima_dispensa"] = fecha("2026-08-16")
    filas["stock_lotes"] = [f for f in filas["stock_lotes"] if f["id_producto"] != "PRD003"]
    assert errores(filas) == []


def renombrar(filas, archivo, id_, nuevo):
    """Cambia el id de una fila y el de las filas que la citan, para que no se pierda ningún enlace."""
    fila(filas, archivo, id_)[CLAVES[archivo]] = nuevo
    for origen, campos in REFERENCIAS.items():
        for campo, destino in campos.items():
            for f in filas[origen]:
                if destino == archivo and f.get(campo) == id_:
                    f[campo] = nuevo


def formato_invalido(archivo, id_):
    prefijo = PREFIJOS[archivo]
    return (f"{archivo}.csv {id_}: [formato-id] formato inválido; se espera {prefijo} y un número de tres dígitos, "
            f"como {prefijo}001")


@pytest.mark.parametrize("archivo", CLAVES)
def test_formato_id_en_cada_archivo(filas, archivo):
    id_ = filas[archivo][0][CLAVES[archivo]]
    renombrar(filas, archivo, id_, PREFIJOS[archivo] + "X")
    assert errores(filas) == [formato_invalido(archivo, PREFIJOS[archivo] + "X")]


@pytest.mark.parametrize("id_", ["C001", "C999", "C1000", "C12345", "C" + "9" * 18])
def test_formato_id_valido(filas, id_):
    renombrar(filas, "clientes", "C001", "C900")
    fila(filas, "clientes", "C008")["id_cliente"] = id_
    assert errores(filas) == []


@pytest.mark.parametrize("id_", ["CX", "C1", "C01", "C0001", "c001", " C001", "C001 ", "C001\n", "C١٢٣", "PRD001",
                                 "C" + "1" * 19])
def test_formato_id_invalido(filas, id_):
    fila(filas, "clientes", "C008")["id_cliente"] = id_
    assert errores(filas) == [formato_invalido("clientes", id_)]


def test_formato_id_prefijo_de_otro_archivo(filas):
    fila(filas, "productos", "PRD013")["id_producto"] = "PRV001"
    assert errores(filas) == [formato_invalido("productos", "PRV001")]


def test_formato_id_tambien_en_las_filas_repetidas(filas):
    filas["clientes"] += [{**fila(filas, "clientes", "C008"), "id_cliente": "CX", "dni": str(n)} for n in (1, 2)]
    assert errores(filas) == ["clientes.csv CX: [id-repetido] id repetido", formato_invalido("clientes", "CX"),
                              formato_invalido("clientes", "CX")]


def test_formato_id_citado_con_otra_forma_da_referencia_cascada_inherente(filas):
    fila(filas, "recetas", "RC001")["id_receta"] = "RC1"
    assert etiquetas(filas) == {"formato-id", "referencia", "dispensas"}


def test_formato_id_vacio_solo_informa_obligatorio(filas):
    fila(filas, "clientes", "C008")["id_cliente"] = None
    assert etiquetas(filas) == {"obligatorio"}


def ajustar_total(filas, id_venta):
    fila(filas, "ventas", id_venta)["total"] = sum(d["cantidad"] * d["precio_unit"] for d in filas["detalle_ventas"]
                                                   if d["id_venta"] == id_venta)


@pytest.mark.parametrize("archivo,id_,campo,valor,condicion", [
    ("stock_lotes", "L001", "unidades", -1, "mayor o igual que 0"),
    ("productos", "PRD013", "precio_unit", 0, "mayor que 0"),
    ("productos", "PRD013", "precio_unit", -100, "mayor que 0"),
    ("detalle_ventas", "D001", "cantidad", 0, "mayor que 0"),
    ("detalle_ventas", "D001", "cantidad", -1, "mayor que 0"),
    ("detalle_ventas", "D001", "precio_unit", 0, "mayor que 0"),
    ("detalle_ventas", "D001", "precio_unit", -3850, "mayor que 0"),
])
def test_rango(filas, archivo, id_, campo, valor, condicion):
    f = fila(filas, archivo, id_)
    f[campo] = valor
    if archivo == "detalle_ventas":
        ajustar_total(filas, f["id_venta"])
    assert errores(filas) == [f"{archivo}.csv {id_}: [rango] {campo} {valor} debe ser {condicion}"]


def test_rango_lote_agotado_es_valido(filas):
    fila(filas, "stock_lotes", "L001")["unidades"] = 0
    assert errores(filas) == []


def test_rango_cantidad_fuera_de_rango_cambia_el_total_cascada_inherente(filas):
    fila(filas, "detalle_ventas", "D001")["cantidad"] = 0
    assert etiquetas(filas) == {"rango", "total"}


@pytest.mark.parametrize("archivo,id_,campo", [("stock_lotes", "L001", "unidades"),
                                               ("productos", "PRD013", "precio_unit"),
                                               ("detalle_ventas", "D001", "cantidad")])
def test_rango_vacio_solo_informa_obligatorio(filas, archivo, id_, campo):
    fila(filas, archivo, id_)[campo] = None
    assert etiquetas(filas) == {"obligatorio"}


@pytest.mark.parametrize("archivo,id_,campo", [("ventas", "V013", "fecha"), ("recetas", "RC009", "fecha_emision")])
def test_fecha_futura(filas, hoy_fijo, archivo, id_, campo):
    assert hoy_fijo == datetime.date(2026, 11, 3)
    fila(filas, archivo, id_)[campo] = fecha("2026-11-03")
    assert errores(filas) == []
    fila(filas, archivo, id_)[campo] = fecha("2026-11-04")
    assert errores(filas) == [f"{archivo}.csv {id_}: [fecha-futura] {campo} 2026-11-04 posterior a hoy (2026-11-03)"]


def test_fecha_futura_depende_de_hoy(originales, monkeypatch):
    monkeypatch.setattr(fechas, "hoy", lambda: datetime.date(2026, 10, 11))
    assert errores(originales) == ["ventas.csv V011: [fecha-futura] fecha 2026-10-12 posterior a hoy (2026-10-11)"]
    monkeypatch.setattr(fechas, "hoy", lambda: datetime.date(2026, 10, 12))
    assert errores(originales) == []


def test_fecha_futura_no_alcanza_a_proxima_dispensa_ni_a_vencimiento(filas):
    fila(filas, "recetas", "RC002")["proxima_dispensa"] = fecha("2027-01-15")
    fila(filas, "stock_lotes", "L001")["vencimiento"] = "2030-01-01"
    assert errores(filas) == []


def test_fecha_futura_de_la_receta_puede_dar_receta_fecha_cascada_inherente(filas):
    fila(filas, "recetas", "RC001")["fecha_emision"] = fecha("2026-12-01")
    assert etiquetas(filas) == {"fecha-futura", "receta-fecha"}


@pytest.mark.parametrize("archivo,id_,campo", [("ventas", "V013", "fecha"), ("recetas", "RC009", "fecha_emision")])
def test_fecha_futura_vacia_solo_informa_obligatorio(filas, archivo, id_, campo):
    fila(filas, archivo, id_)[campo] = None
    assert etiquetas(filas) == {"obligatorio"}


PERDIDA_DE_ENLACE = {("clientes", "id_cliente"): "referencia", ("sucursales", "id_sucursal"): "referencia",
                     ("farmaceuticos", "id_farmaceutico"): "referencia", ("proveedores", "id_proveedor"): "referencia",
                     ("productos", "id_producto"): "referencia", ("recetas", "id_receta"): "referencia",
                     ("ventas", "id_venta"): "referencia", ("ventas", "id_receta"): "dispensas",
                     ("detalle_ventas", "id_venta"): "total"}


@pytest.mark.parametrize("archivo", CLAVES)
def test_columna_ausente_solo_informa_encabezado(originales, archivo):
    for columna in originales[archivo][0]:
        esperadas = {"encabezado", PERDIDA_DE_ENLACE.get((archivo, columna), "encabezado")}
        for posicion in range(len(originales[archivo])):
            filas = copy.deepcopy(originales)
            del filas[archivo][posicion][columna]
            encontradas = etiquetas(filas)
            # La primera fila de cada archivo tiene enlaces; otras pueden no perder ninguno.
            if posicion == 0:
                assert encontradas == esperadas, columna
            else:
                assert "encabezado" in encontradas and encontradas <= esperadas, (columna, posicion)


@pytest.mark.parametrize("archivo", CLAVES)
def test_columna_renombrada_en_todo_el_archivo_solo_informa_encabezado(originales, archivo):
    for columna in originales[archivo][0]:
        filas = copy.deepcopy(originales)
        filas[archivo] = [{(f"{k}_x" if k == columna else k): v for k, v in f.items()} for f in filas[archivo]]
        encontradas = etiquetas(filas)
        assert encontradas == {"encabezado", PERDIDA_DE_ENLACE.get((archivo, columna), "encabezado")}, columna
        assert sum("[encabezado]" in e for e in errores(filas)) == len(filas[archivo]), columna


@pytest.mark.parametrize("archivo", CLAVES)
def test_no_lanza_con_vacios_en_cualquier_campo(originales, archivo):
    for columna in originales[archivo][0]:
        for posicion in range(len(originales[archivo])):
            filas = copy.deepcopy(originales)
            filas[archivo][posicion][columna] = None
            assert isinstance(errores(filas), list)


def test_no_lanza_con_todos_los_campos_vacios(originales):
    filas = {a: [dict.fromkeys(f) for f in lista] for a, lista in originales.items()}
    assert etiquetas(filas) == {"obligatorio"}


@pytest.mark.parametrize("archivo", CLAVES)
def test_no_lanza_con_filas_sin_columnas_ni_con_columnas_de_mas(originales, archivo):
    filas = copy.deepcopy(originales)
    filas[archivo].append({})
    filas[archivo].append({None: ["a", "b"]})
    assert "encabezado" in etiquetas(filas)
    assert errores({a: [{}, {None: ["a"]}] for a in CLAVES})


@pytest.mark.parametrize("archivo", CLAVES)
def test_no_lanza_con_archivo_vacio_o_ausente(originales, archivo):
    vacio = {**copy.deepcopy(originales), archivo: []}
    ausente = {a: copy.deepcopy(lista) for a, lista in originales.items() if a != archivo}
    assert errores(vacio) == errores(ausente)


def test_sin_datos_no_hay_errores():
    assert errores({}) == []
    assert errores({a: [] for a in CLAVES}) == []


def test_archivo_ausente_informa_lo_que_dependia_de_el(originales):
    filas = {a: lista for a, lista in originales.items() if a != "sucursales"}
    assert etiquetas(filas) == {"referencia"}


def test_orden_por_regla_y_dentro_de_ella_por_fila(filas):
    fila(filas, "ventas", "V003")["total"] = 1
    fila(filas, "ventas", "V001")["total"] = 2
    fila(filas, "clientes", "C002")["obra_social"] = "Otra"
    del fila(filas, "proveedores", "PRV002")["telefono"]
    primera = errores(filas)
    assert [re.search(r"csv (\S+):", e).group(1) for e in primera] == ["PRV002", "C002", "V001", "V003"]
    assert errores(copy.deepcopy(filas)) == primera


def agregar_adicionales(tmp_path, monkeypatch, archivo, encabezado, *renglones):
    shutil.copytree(PROVISTOS, tmp_path / "provistos")
    (tmp_path / "adicionales").mkdir()
    with open(tmp_path / "adicionales" / f"{archivo}.csv", "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        escritor.writerow(encabezado)
        escritor.writerows(renglones)
    monkeypatch.setattr(lector, "DATOS", tmp_path)


@pytest.mark.parametrize("archivo,columna,mal_escrita", [
    ("clientes", "dni", "dnii"),
    ("sucursales", "direccion", "dirección"),
    ("farmaceuticos", "matricula", "matrícula"),
    ("proveedores", "cuit", "CUIT"),
    ("productos", "condicion_venta", "condicion"),
    ("stock_lotes", "nro_lote", "nro_lte"),
    ("stock_lotes", "unidades", "unidad"),
    ("recetas", "proxima_dispensa", "proxima"),
    ("ventas", "total", "totl"),
    ("detalle_ventas", "cantidad", "cant"),
])
def test_encabezado_mal_escrito_en_todo_el_archivo_leido_del_csv(tmp_path, monkeypatch, archivo, columna, mal_escrita):
    shutil.copytree(PROVISTOS, tmp_path / "provistos")
    ruta = tmp_path / "provistos" / f"{archivo}.csv"
    encabezado, resto = ruta.read_text(encoding="utf-8").split("\n", 1)
    assert encabezado.split(",").count(columna) == 1
    ruta.write_text(",".join(mal_escrita if c == columna else c for c in encabezado.split(",")) + "\n" + resto,
                    encoding="utf-8")
    monkeypatch.setattr(lector, "DATOS", tmp_path)
    filas = lector.leer_todo(True)
    assert etiquetas(filas) == {"encabezado"}
    assert len(errores(filas)) == len(filas[archivo])


def test_id_repetido_entre_provistos_y_adicionales_leidos_del_csv(tmp_path, monkeypatch):
    encabezado = ["id_venta", "id_cliente", "id_farmaceutico", "id_receta", "fecha", "tipo", "medio_pago", "total",
                  "estado"]
    agregar_adicionales(tmp_path, monkeypatch, "ventas", encabezado,
                        ["V001", "C005", "F001", "", "2026-10-01", "Venta libre", "Efectivo", "100", "Anulada"])
    assert errores(lector.leer_todo()) == ["ventas.csv V001: [id-repetido] id repetido"]


def test_columna_de_mas_leida_del_csv(tmp_path, monkeypatch):
    encabezado = ["id_proveedor", "razon_social", "cuit", "tipo", "ciudad", "provincia", "telefono", "activo"]
    agregar_adicionales(tmp_path, monkeypatch, "proveedores", encabezado,
                        ["PRV006", "Otro S.A.", "30-1", "Laboratorio", "X", "Y", "1", "True", "de más"])
    filas = lector.leer_todo()
    assert None in filas["proveedores"][-1]
    assert errores(filas) == ["proveedores.csv PRV006: [encabezado] columnas distintas de las esperadas"]


def test_columnas_en_otro_orden_leidas_del_csv(tmp_path, monkeypatch):
    encabezado = ["razon_social", "id_proveedor", "cuit", "tipo", "ciudad", "provincia", "telefono", "activo"]
    agregar_adicionales(tmp_path, monkeypatch, "proveedores", encabezado,
                        ["Otro S.A.", "PRV006", "30-1", "Laboratorio", "X", "Y", "1", "True"])
    assert errores(lector.leer_todo()) == [
        "proveedores.csv PRV006: [encabezado] columnas distintas de las esperadas"]
