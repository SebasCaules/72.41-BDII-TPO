import datetime
import json
import pathlib
import subprocess
import sys

import pytest

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


def test_recrea_la_vista_con_la_definicion_del_codigo(datos_provistos, db):
    db.drop_collection("ingresos_mes_actual")
    db.create_collection("ingresos_mes_actual", viewOn="ventas", pipeline=[{"$match": {"estado": "Anulada"}}])
    insertar_venta(db, "V901", "F001", dia_real(), "Completada", 7300)
    assert q11.ingresos_mes_actual() == [farmaceutico(db, "F001", 1, 7300)]
    assert next(db.list_collections(filter={"name": "ingresos_mes_actual"}))["options"]["pipeline"] == \
        q11.PIPELINE_VISTA
    assert q11.ingresos_mes_actual() == [farmaceutico(db, "F001", 1, 7300)]


@pytest.mark.skipif(datetime.date.today().strftime("%Y-%m") != "2026-11",
                    reason="las ventas adicionales del mes actual son de noviembre de 2026")
def test_datos_completos_en_noviembre_de_2026(datos_completos):
    assert [(f["id_farmaceutico"], f["cantidad_ventas"], f["ingresos"]) for f in q11.ingresos_mes_actual()] == [
        ("F008", 2, 9100), ("F010", 1, 6900), ("F009", 1, 5100)]


def test_resultado_serializable_en_json(datos_completos):
    resultado = q11.ingresos_mes_actual()
    assert json.loads(json.dumps(resultado)) == resultado


def test_cli_da_lo_mismo_que_la_funcion(datos_completos):
    resultado = correr_cli("q11")
    assert resultado.returncode == 0, resultado.stderr
    assert json.loads(resultado.stdout) == q11.ingresos_mes_actual()


def test_cli_con_un_argumento_de_mas_sale_con_2():
    assert correr_cli("q11", "S001").returncode == 2
