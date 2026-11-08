import datetime
import json
import pathlib
import subprocess
import sys

from farmared import fechas, formato
from farmared.consultas import q06_dispensas_atrasadas as q06

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CAMPOS_RECETA = {"id_receta", "id_cliente", "medico", "matricula_medico", "fecha_emision", "tipo",
                 "dispensas_autorizadas", "dispensas_realizadas", "proxima_dispensa", "estado", "cliente"}
CAMPOS_CLIENTE = {"id_cliente", "nombre", "apellido", "dni", "email", "telefono", "ciudad", "provincia",
                  "obra_social", "nro_afiliado", "activo"}


def correr_cli(*argumentos):
    return subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                          text=True, timeout=60)


def hoy_del_sistema():
    salida = subprocess.run([sys.executable, "-c", "from farmared import fechas; print(fechas.hoy())"], cwd=RAIZ,
                            capture_output=True, text=True, timeout=60)
    return fechas.desde_iso(salida.stdout.strip())


def resumen(resultado):
    return [(r["id_receta"], r["cliente"]["id_cliente"], r["proxima_dispensa"]) for r in resultado]


def fijar_hoy(monkeypatch, dia):
    monkeypatch.setattr(fechas, "hoy", lambda: dia)


def test_dispensas_atrasadas_de_los_provistos(datos_provistos):
    resultado = q06.dispensas_atrasadas()
    assert resumen(resultado) == [
        ("RC002", "C003", "2026-09-15"), ("RC003", "C006", "2026-10-01"), ("RC004", "C006", "2026-10-20")]
    assert resultado[0] == {
        "id_receta": "RC002", "id_cliente": "C003", "medico": "Dra. Silvia Montenegro", "matricula_medico": "MP-39877",
        "fecha_emision": "2026-07-15", "tipo": "Tratamiento prolongado", "dispensas_autorizadas": 3,
        "dispensas_realizadas": 2, "proxima_dispensa": "2026-09-15", "estado": "Vigente",
        "cliente": {"id_cliente": "C003", "nombre": "Carla", "apellido": "Ruiz", "dni": "40123456",
                    "email": "carla.r@gmail.com", "telefono": "3515334455", "ciudad": "Córdoba",
                    "provincia": "Córdoba", "obra_social": "PAMI", "nro_afiliado": "PA-771203", "activo": True}}


def test_cada_receta_trae_su_cliente_completo(datos_completos, db):
    for receta in q06.dispensas_atrasadas():
        assert set(receta) == CAMPOS_RECETA
        assert set(receta["cliente"]) == CAMPOS_CLIENTE
        cliente = formato.a_json(db.clientes.find_one({"_id": receta["id_cliente"]}))
        assert receta["cliente"] == {**cliente, "id_cliente": receta["id_cliente"]}


def test_dispensas_atrasadas_con_datos_completos(datos_completos):
    resultado = q06.dispensas_atrasadas()
    assert resumen(resultado) == [
        ("RC002", "C003", "2026-09-15"), ("RC003", "C006", "2026-10-01"), ("RC004", "C006", "2026-10-20"),
        ("RC011", "C014", "2026-10-26")]
    assert "RC013" not in {r["id_receta"] for r in resultado}


def test_proxima_dispensa_de_hoy_no_esta_atrasada(datos_provistos, monkeypatch):
    fijar_hoy(monkeypatch, datetime.date(2026, 10, 20))
    assert [r["id_receta"] for r in q06.dispensas_atrasadas()] == ["RC002", "RC003"]
    fijar_hoy(monkeypatch, datetime.date(2026, 10, 21))
    assert [r["id_receta"] for r in q06.dispensas_atrasadas()] == ["RC002", "RC003", "RC004"]


def test_solo_tratamiento_prolongado_vigente(datos_provistos, db):
    db.recetas.update_one({"_id": "RC003"}, {"$set": {"estado": "Completada"}})
    db.recetas.update_one({"_id": "RC004"}, {"$set": {"tipo": "Simple"}})
    assert [r["id_receta"] for r in q06.dispensas_atrasadas()] == ["RC002"]


def test_misma_proxima_dispensa_se_ordena_por_id_receta(datos_provistos, db):
    # RC003 pasa a la fecha de RC002, y RC002 vuelve a insertarse para quedar después en el orden natural
    db.recetas.update_one({"_id": "RC003"},
                          {"$set": {"proxima_dispensa": fechas.a_datetime(datetime.date(2026, 9, 15))}})
    receta = db.recetas.find_one({"_id": "RC002"})
    db.recetas.delete_one({"_id": "RC002"})
    db.recetas.insert_one(receta)
    assert resumen(q06.dispensas_atrasadas()) == [
        ("RC002", "C003", "2026-09-15"), ("RC003", "C006", "2026-09-15"), ("RC004", "C006", "2026-10-20")]


def test_tratamiento_vigente_sin_dispensas_no_esta_atrasado(datos_provistos, db):
    # sin dispensas realizadas la receta no tiene proxima_dispensa
    db.recetas.update_one({"_id": "RC009"}, {"$set": {
        "tipo": "Tratamiento prolongado", "estado": "Vigente", "dispensas_autorizadas": 3,
        "dispensas_realizadas": 0, "proxima_dispensa": None}})
    assert [r["id_receta"] for r in q06.dispensas_atrasadas()] == ["RC002", "RC003", "RC004"]


def test_plan_usa_el_indice_de_recetas(datos_provistos, db):
    pipeline = q06.pipeline(fechas.a_datetime(fechas.hoy()))
    plan = db.command("explain", {"aggregate": "recetas", "pipeline": pipeline, "cursor": {}},
                      verbosity="executionStats")
    texto = json.dumps(plan, default=str)
    assert "IXSCAN" in texto
    assert "tipo_1_estado_1_proxima_dispensa_1" in texto
    assert "COLLSCAN" not in texto


def test_resultado_serializable_sin_conversiones(datos_completos):
    resultado = q06.dispensas_atrasadas()
    assert json.loads(json.dumps(resultado)) == resultado


def test_linea_de_comandos_igual_a_la_funcion(datos_completos, monkeypatch):
    fijar_hoy(monkeypatch, hoy_del_sistema())
    salida = correr_cli("q06")
    assert salida.returncode == 0, salida.stderr
    assert json.loads(salida.stdout) == q06.dispensas_atrasadas()


def test_linea_de_comandos_rechaza_argumentos_de_mas():
    salida = correr_cli("q06", "--hoy", "2026-11-03")
    assert salida.returncode == 2
    assert salida.stdout == ""
