import collections
import datetime
import json
import pathlib
import subprocess
import sys

import pytest

from farmared import carga
from farmared.consultas import q11_ingresos_mes_actual as q11
from farmared.errores import FarmaRedError

RAIZ = pathlib.Path(__file__).resolve().parent.parent
# Cada proceso llama a q11 tantas veces como diga su argumento y cuenta cuántas veces vio cada respuesta.
LECTOR = """
import collections, json, sys
from farmared.consultas import q11_ingresos_mes_actual as q11
vistas = collections.Counter()
for _ in range(int(sys.argv[1])):
    try:
        vistas[json.dumps(q11.ingresos_mes_actual())] += 1
    except Exception as e:
        vistas[f"{type(e).__name__}: {e}"] += 1
print(json.dumps(vistas))
"""


def correr_cli(*argumentos):
    return subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                          text=True, timeout=60)


def definicion(db):
    return next(db.list_collections(filter={"name": "ingresos_mes_actual"}), None)


def venta_completada_hoy(db, id_venta, id_farmaceutico, total):
    # La vista toma el mes del reloj del servidor, así que la venta va con la fecha real.
    hoy = datetime.date.today()
    db.ventas.insert_one({
        "_id": id_venta, "id_cliente": "C005", "id_farmaceutico": id_farmaceutico, "id_receta": None,
        "fecha": datetime.datetime(hoy.year, hoy.month, hoy.day), "tipo": "Venta libre", "medio_pago": "Efectivo",
        "total": total, "estado": "Completada",
        "items": [{"id_detalle": f"D{id_venta[1:]}", "id_producto": "PRD002", "cantidad": 1, "precio_unit": total}],
        "stock_descontado": True})


def test_en_una_base_nueva_la_vista_existe_apenas_termina_la_carga(db):
    db.client.drop_database(db.name)
    carga.cargar(solo_provistos=True)
    vista = definicion(db)
    assert vista is not None
    assert (vista["type"], vista["options"]["viewOn"]) == ("view", "ventas")
    assert vista["options"]["pipeline"] == q11.PIPELINE_VISTA


def test_la_consulta_lee_la_vista_sin_redefinirla(datos_provistos, db):
    otra = [{"$match": {"estado": "Anulada"}}, {"$project": {"_id": 0, "id_farmaceutico": 1}}]
    db.command("collMod", "ingresos_mes_actual", viewOn="ventas", pipeline=otra)
    q11.ingresos_mes_actual()
    assert definicion(db)["options"]["pipeline"] == otra


def test_cargar_dos_veces_deja_una_sola_vista_con_la_definicion_del_codigo(db):
    db.client.drop_database(db.name)
    carga.cargar(solo_provistos=True)
    carga.cargar(solo_provistos=True)
    vistas = list(db.list_collections(filter={"type": "view"}))
    assert [v["name"] for v in vistas] == ["ingresos_mes_actual"]
    assert vistas[0]["options"]["pipeline"] == q11.PIPELINE_VISTA


def test_sin_la_vista_informa_que_falta_la_carga(datos_provistos, db):
    db.drop_collection("ingresos_mes_actual")
    with pytest.raises(FarmaRedError) as error:
        q11.ingresos_mes_actual()
    assert error.value.codigo == "BASE_SIN_CARGA"
    assert definicion(db) is None
    salida = correr_cli("q11")
    assert (salida.returncode, salida.stdout) == (1, "")
    assert salida.stderr.startswith("Error [BASE_SIN_CARGA]: "), salida.stderr


def test_con_la_base_vacia_informa_que_falta_la_carga(db):
    db.client.drop_database(db.name)
    try:
        with pytest.raises(FarmaRedError) as error:
            q11.ingresos_mes_actual()
        assert error.value.codigo == "BASE_SIN_CARGA"
    finally:
        carga.cargar(solo_provistos=True)


def test_cuatro_procesos_leyendo_a_la_vez_reciben_siempre_el_resultado_completo(datos_provistos, db):
    venta_completada_hoy(db, "V901", "F001", 7300)
    venta_completada_hoy(db, "V902", "F002", 5100)
    esperado = q11.ingresos_mes_actual()
    assert [f["id_farmaceutico"] for f in esperado] == ["F001", "F002"]
    procesos = [subprocess.Popen([sys.executable, "-c", LECTOR, "100"], cwd=RAIZ, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True) for _ in range(4)]
    vistas = collections.Counter()
    for proceso in procesos:
        salida, errores = proceso.communicate(timeout=120)
        assert proceso.returncode == 0, errores
        vistas.update(json.loads(salida))
    assert vistas == {json.dumps(esperado): 400}
