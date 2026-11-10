import datetime

import pytest

from farmared.consultas import q05_ventas_por_farmaceutico as q05


# hoy es 2026-11-03 (conftest) y F007 no tiene ventas
@pytest.mark.parametrize("fecha,cuenta", [
    (datetime.datetime(2026, 11, 3, 15, 30), 1),         # hoy, con hora
    (datetime.datetime(2026, 11, 3, 23, 59, 59), 1),     # último instante de hoy
    (datetime.datetime(2026, 11, 4), 0),                 # mañana
    (datetime.datetime(2026, 9, 4, 8, 0), 1),            # hace 60 días, con hora
    (datetime.datetime(2026, 9, 3, 23, 0), 0),           # hace 61 días
])
def test_la_ventana_cuenta_dias_enteros_aunque_la_venta_tenga_hora(datos_provistos, db, fecha, cuenta):
    db.ventas.insert_one({
        "_id": "V900", "id_cliente": "C001", "id_farmaceutico": "F007", "id_receta": None, "fecha": fecha,
        "tipo": "Venta libre", "medio_pago": "Efectivo", "total": 2800, "estado": "Completada",
        "items": [{"id_detalle": "D900", "id_producto": "PRD001", "cantidad": 1, "precio_unit": 2800}],
        "stock_descontado": True})
    resultado = {f["id_farmaceutico"]: f["cantidad_ventas"] for f in q05.ventas_recientes_por_farmaceutico()}
    assert resultado["F007"] == cuenta
