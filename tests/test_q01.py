import json
import pathlib
import subprocess
import sys

from farmared.consultas import q01_productos_activos as q01

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CAMPOS_PRODUCTO = {"id_producto", "nombre", "principio_activo", "categoria", "presentacion", "condicion_venta",
                   "precio_unit", "activo", "proveedor"}
CAMPOS_PROVEEDOR = {"id_proveedor", "razon_social", "cuit", "tipo", "ciudad", "provincia", "telefono", "activo"}


def correr_cli(*argumentos):
    return subprocess.run([sys.executable, "-m", "farmared", *argumentos], cwd=RAIZ, capture_output=True,
                          text=True, timeout=60)


def test_productos_activos_de_los_provistos(datos_provistos):
    resultado = q01.productos_activos_con_proveedor()
    assert [p["id_producto"] for p in resultado] == [f"PRD{n:03d}" for n in range(1, 12)]
    assert "PRV005" not in {p["proveedor"]["id_proveedor"] for p in resultado}
    assert resultado[0] == {
        "id_producto": "PRD001", "nombre": "Paracetamol 500mg x30", "principio_activo": "Paracetamol",
        "categoria": "Analgésico", "presentacion": "Comprimidos x30", "condicion_venta": "Venta libre",
        "precio_unit": 2800, "activo": True,
        "proveedor": {"id_proveedor": "PRV001", "razon_social": "Laboratorios Andinos S.A.", "cuit": "30-71234567-1",
                      "tipo": "Laboratorio", "ciudad": "Buenos Aires", "provincia": "Buenos Aires",
                      "telefono": "1143001100", "activo": True}}


def test_el_orden_por_id_no_depende_del_orden_de_insercion(datos_provistos, db):
    # PRD001 vuelve a insertarse y queda último en el orden natural de la colección
    producto = db.productos.find_one({"_id": "PRD001"})
    db.productos.delete_one({"_id": "PRD001"})
    db.productos.insert_one(producto)
    assert [p["_id"] for p in db.productos.find({"activo": True})][-1] == "PRD001"
    resultado = q01.productos_activos_con_proveedor()
    assert [p["id_producto"] for p in resultado] == [f"PRD{n:03d}" for n in range(1, 12)]


def test_cada_producto_trae_su_proveedor_completo(datos_provistos, db):
    productos = {p["_id"]: p for p in db.productos.find()}
    proveedores = {p["_id"]: p for p in db.proveedores.find()}
    for item in q01.productos_activos_con_proveedor():
        assert set(item) == CAMPOS_PRODUCTO
        assert set(item["proveedor"]) == CAMPOS_PROVEEDOR
        producto = productos[item["id_producto"]]
        assert producto["activo"] is True
        assert {k: v for k, v in item.items() if k not in ("id_producto", "proveedor")} == \
            {k: v for k, v in producto.items() if k not in ("_id", "id_proveedor")}
        assert item["proveedor"]["id_proveedor"] == producto["id_proveedor"]
        assert {k: v for k, v in item["proveedor"].items() if k != "id_proveedor"} == \
            {k: v for k, v in proveedores[producto["id_proveedor"]].items() if k != "_id"}


def test_productos_activos_con_datos_completos(datos_completos):
    resultado = q01.productos_activos_con_proveedor()
    esperados = [f"PRD{n:03d}" for n in [*range(1, 12), *range(14, 21), 22, 23]]
    assert [p["id_producto"] for p in resultado] == esperados
    por_id = {p["id_producto"]: p for p in resultado}
    assert por_id["PRD018"]["proveedor"]["id_proveedor"] == "PRV010"
    assert por_id["PRD018"]["proveedor"]["activo"] is False
    assert por_id["PRD014"]["condicion_venta"] == "Bajo receta archivada"
    assert not {"PRD012", "PRD013", "PRD021"} & set(por_id)


def test_resultado_serializable_sin_conversiones(datos_completos):
    resultado = q01.productos_activos_con_proveedor()
    assert json.loads(json.dumps(resultado)) == resultado


def test_linea_de_comandos_igual_a_la_funcion(datos_completos):
    salida = correr_cli("q01")
    assert salida.returncode == 0, salida.stderr
    assert json.loads(salida.stdout) == q01.productos_activos_con_proveedor()


def test_linea_de_comandos_rechaza_argumentos_de_mas():
    salida = correr_cli("q01", "PRD001")
    assert salida.returncode == 2
    assert salida.stdout == ""
