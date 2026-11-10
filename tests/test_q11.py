import datetime
import json
import pathlib
import subprocess
import sys

import pytest

from farmared import carga
from farmared.consultas import q11_ingresos_mes_actual as q11

RAIZ = pathlib.Path(__file__).resolve().parent.parent


# La vista calcula el mes con la fecha del servidor, que no se puede fijar: estos tests usan la fecha real.
def dia_real():
    return datetime.date.today()


def a_medianoche(dia):
    return datetime.datetime(dia.year, dia.month, dia.day)


def correr_cli(*argumentos):
    return subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                          text=True, timeout=60)


def insertar_venta(db, id_venta, id_farmaceutico, dia, estado, total):
    db.ventas.insert_one({
        "_id": id_venta, "id_cliente": "C005", "id_farmaceutico": id_farmaceutico, "id_receta": None,
        "fecha": a_medianoche(dia), "tipo": "Venta libre", "medio_pago": "Efectivo", "total": total,
        "estado": estado, "items": [{"id_detalle": f"D{id_venta[1:]}", "id_producto": "PRD002", "cantidad": 1,
                                     "precio_unit": total}],
        "stock_descontado": estado == "Completada"})


def farmaceutico(db, id_farmaceutico, cantidad_ventas, ingresos):
    f = db.farmaceuticos.find_one({"_id": id_farmaceutico})
    return {"id_farmaceutico": id_farmaceutico, "nombre": f["nombre"], "apellido": f["apellido"],
            "id_sucursal": f["id_sucursal"], "cantidad_ventas": cantidad_ventas, "ingresos": ingresos}


def test_con_datos_provistos_da_lista_vacia(datos_provistos):
    assert q11.ingresos_mes_actual() == []


def test_completada_de_hoy_sale_con_su_total_y_pendiente_no(datos_provistos, db):
    insertar_venta(db, "V901", "F001", dia_real(), "Completada", 7300)
    insertar_venta(db, "V902", "F002", dia_real(), "Pendiente", 9100)
    insertar_venta(db, "V903", "F003", dia_real(), "Anulada", 8200)
    assert q11.ingresos_mes_actual() == [farmaceutico(db, "F001", 1, 7300)]


def test_suma_por_farmaceutico_y_ordena_por_ingresos_e_id(datos_provistos, db):
    hoy = dia_real()
    insertar_venta(db, "V901", "F003", hoy, "Completada", 7000)
    insertar_venta(db, "V902", "F001", hoy, "Completada", 7000)
    insertar_venta(db, "V903", "F002", hoy, "Completada", 3000)
    insertar_venta(db, "V904", "F002", hoy.replace(day=1), "Completada", 5000)
    assert q11.ingresos_mes_actual() == [
        farmaceutico(db, "F002", 2, 8000), farmaceutico(db, "F001", 1, 7000), farmaceutico(db, "F003", 1, 7000)]


def test_otros_meses_no_cuentan(datos_provistos, db):
    hoy = dia_real()
    fin_mes_anterior = hoy.replace(day=1) - datetime.timedelta(days=1)
    inicio_mes_siguiente = (hoy.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    insertar_venta(db, "V901", "F005", fin_mes_anterior, "Completada", 6000)
    insertar_venta(db, "V902", "F006", inicio_mes_siguiente, "Completada", 6000)
    insertar_venta(db, "V903", "F005", hoy - datetime.timedelta(days=366), "Completada", 6000)
    assert q11.ingresos_mes_actual() == []


def test_crea_la_vista_sobre_ventas(datos_provistos, db):
    q11.ingresos_mes_actual()
    vista = next(db.list_collections(filter={"name": "ingresos_mes_actual"}))
    assert vista["type"] == "view"
    assert vista["options"]["viewOn"] == "ventas"
    assert vista["options"]["pipeline"] == q11.PIPELINE_VISTA


def test_la_carga_reemplaza_una_vista_ya_creada(datos_provistos, db):
    db.drop_collection("ingresos_mes_actual")
    db.create_collection("ingresos_mes_actual", viewOn="ventas", pipeline=[{"$match": {"estado": "Anulada"}}])
    carga.cargar(solo_provistos=True)
    insertar_venta(db, "V901", "F001", dia_real(), "Completada", 7300)
    assert next(db.list_collections(filter={"name": "ingresos_mes_actual"}))["options"]["pipeline"] == \
        q11.PIPELINE_VISTA
    assert q11.ingresos_mes_actual() == [farmaceutico(db, "F001", 1, 7300)]


def con_instante(nodo, instante):
    if nodo == "$$NOW":
        return instante
    if isinstance(nodo, dict):
        return {k: con_instante(v, instante) for k, v in nodo.items()}
    if isinstance(nodo, list):
        return [con_instante(v, instante) for v in nodo]
    return nodo


# La definición de la vista corrida sobre ventas con un instante fijo en lugar de $$NOW: vale en cualquier mes.
@pytest.mark.parametrize("instante_utc,esperado", [
    (datetime.datetime(2026, 11, 16, 15), [("F008", 2, 9100), ("F010", 1, 6900), ("F009", 1, 5100)]),
    (datetime.datetime(2026, 11, 1, 3), [("F008", 2, 9100), ("F010", 1, 6900), ("F009", 1, 5100)]),
    (datetime.datetime(2026, 12, 1, 2, 59, 59), [("F008", 2, 9100), ("F010", 1, 6900), ("F009", 1, 5100)]),
    (datetime.datetime(2026, 12, 1, 3), []),
    (datetime.datetime(2026, 11, 1, 2, 59, 59), [("F010", 1, 8400), ("F002", 1, 7800), ("F003", 1, 7100),
                                                 ("F017", 1, 5000), ("F005", 1, 4600), ("F001", 1, 4400),
                                                 ("F018", 1, 4200)]),
])
def test_datos_completos_con_el_mes_en_hora_argentina(datos_completos, db, instante_utc, esperado):
    pipeline = con_instante(q11.PIPELINE_VISTA, instante_utc) + [{"$sort": {"ingresos": -1, "id_farmaceutico": 1}}]
    assert [(f["id_farmaceutico"], f["cantidad_ventas"], f["ingresos"]) for f in db.ventas.aggregate(pipeline)] == \
        esperado


def test_resultado_serializable_en_json(datos_completos):
    resultado = q11.ingresos_mes_actual()
    assert json.loads(json.dumps(resultado)) == resultado


def test_cli_da_lo_mismo_que_la_funcion(datos_completos):
    resultado = correr_cli("q11")
    assert resultado.returncode == 0, resultado.stderr
    assert json.loads(resultado.stdout) == q11.ingresos_mes_actual()


def test_cli_con_un_argumento_de_mas_sale_con_2():
    assert correr_cli("q11", "S001").returncode == 2
