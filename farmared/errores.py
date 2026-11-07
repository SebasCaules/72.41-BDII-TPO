class FarmaRedError(Exception):
    def __init__(self, codigo, mensaje):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


class ValidacionError(FarmaRedError):
    pass


class NoEncontrado(ValidacionError):
    pass


class StockInsuficiente(FarmaRedError):
    def __init__(self, id_producto, requerido, disponible):
        super().__init__("STOCK_INSUFICIENTE",
                         f"stock insuficiente de {id_producto}: se piden {requerido}, hay {disponible} vigentes")
        self.id_producto = id_producto
        self.requerido = requerido
        self.disponible = disponible
