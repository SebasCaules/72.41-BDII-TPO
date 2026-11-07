def ventas_libres_menores(monto=5000):
    """Ventas 'Venta libre' con total menor al monto, sin contar las anuladas.

    Parámetros:
        monto: total máximo en pesos, 5000 por defecto (exclusivo).
    Retorna:
        Lista con id_venta, fecha, id_cliente, id_farmaceutico, total, estado y medio_pago,
        ordenada por fecha e id_venta.
    Motor: MongoDB (aggregate sobre ventas).
    """
    raise NotImplementedError
