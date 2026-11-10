import re

from farmared.errores import ValidacionError

OBRAS_SOCIALES = {"OSDE", "Swiss Medical", "PAMI", "IOMA", "Galeno", "Sin cobertura"}
TIPOS_SUCURSAL = {"Farmacia", "Droguería"}
CARGOS = {"Director Técnico", "Farmacéutico"}
TIPOS_PROVEEDOR = {"Laboratorio", "Droguería"}
CONDICIONES_VENTA = {"Venta libre", "Bajo receta", "Bajo receta archivada"}
TIPOS_RECETA = {"Simple", "Archivada", "Tratamiento prolongado"}
ESTADOS_RECETA = {"Vigente", "Completada", "Vencida"}
TIPOS_VENTA = {"Venta libre", "Con receta"}
MEDIOS_DE_PAGO = {"Efectivo", "Débito", "Crédito", "Transferencia", "Obra social"}
ESTADOS_VENTA = {"Completada", "Pendiente", "Anulada"}
CONDICIONES_CON_RECETA = {"Bajo receta", "Bajo receta archivada"}
# Solo dígitos ASCII, o con puntos de miles (31.245.678); en las dos formas, los ceros a la izquierda no cuentan.
# Un DNI argentino tiene hasta 8 cifras.
FORMATO_DNI = re.compile(r"[0-9]+|0*[0-9]{1,3}(?:\.[0-9]{3})+")
CIFRAS_DNI = 8


def normalizar_dni(texto):
    """Lleva un DNI a su número: solo dígitos y sin ceros a la izquierda.

    Parámetros:
        texto: el DNI como se escribió, con o sin puntos de miles y con espacios en los extremos.
    Retorna:
        El número como texto ("31.245.678", "031245678" y " 31245678 " dan "31245678"), o None si no es un
        número de documento de 1 a 8 cifras. El alta y la carga lo usan para comparar y para guardar.
    Motor: ninguno.
    Errores: ninguno.
    """
    texto = texto.strip()
    if not FORMATO_DNI.fullmatch(texto):
        return None
    numero = texto.replace(".", "").lstrip("0")
    return numero if 0 < len(numero) <= CIFRAS_DNI else None


def validar_id(campo, valor):
    """Exige que un id recibido como parámetro sea texto, antes de usarlo en una consulta.

    En un filtro de MongoDB, un diccionario se lee como operador ({"$ne": None} coincide con cualquier
    documento): un id que no es texto se rechaza en lugar de buscarlo.

    Parámetros:
        campo: nombre del parámetro, para el mensaje (p. ej. "id_cliente").
        valor: el id recibido.
    Retorna:
        None.
    Motor: ninguno.
    Errores: ValidacionError con DATO_INVALIDO si el valor no es texto.
    """
    if not isinstance(valor, str):
        raise ValidacionError("DATO_INVALIDO", f"{campo} inválido: {valor!r} (se espera un id de texto)")
