def ventas_pendientes():
    """Ventas 'Pendiente' con el farmacéutico asignado, su sucursal y el total.

    Parámetros: ninguno.
    Retorna:
        Lista con id_venta, fecha, id_cliente, tipo, total, farmaceutico y sucursal, por fecha e id_venta.
    Motor: MongoDB (aggregate sobre ventas con $lookup de farmaceuticos y sucursales).
    """
    raise NotImplementedError
