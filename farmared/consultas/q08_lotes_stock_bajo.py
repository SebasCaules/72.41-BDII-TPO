def lotes_stock_bajo(umbral=50):
    """Lotes con menos unidades que el umbral, con producto, sucursal y proveedor.

    Parámetros:
        umbral: unidades mínimas, 50 por defecto (exclusivo).
    Retorna:
        Lista de lotes ordenada por unidades e id_lote.
    Motor: Redis (lotes por unidades) y MongoDB (nombres).
    """
    raise NotImplementedError
