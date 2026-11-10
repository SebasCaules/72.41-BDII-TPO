import random
import time

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError, ServerSelectionTimeoutError

from farmared import conexiones, formato, ids
from farmared.dominio import OBRAS_SOCIALES, normalizar_dni, validar_id
from farmared.errores import NoEncontrado, ValidacionError

OBLIGATORIOS = ("nombre", "apellido", "dni", "email", "telefono", "ciudad", "provincia", "obra_social")
MODIFICABLES = ("email", "telefono", "ciudad", "provincia", "obra_social", "nro_afiliado")
SIN_COBERTURA = "Sin cobertura"
INTENTOS = 5


def _texto(campo, valor):
    if not isinstance(valor, str) or not valor.strip():
        raise ValidacionError("DATO_INVALIDO", f"{campo}: falta o está vacío")
    return valor.strip()


def _validar_obra_social(obra_social):
    if obra_social not in OBRAS_SOCIALES:
        raise ValidacionError("OBRA_SOCIAL_INVALIDA", f"obra social inválida: {obra_social}")


def _dni_duplicado(dni):
    return ValidacionError("DNI_DUPLICADO", f"ya existe un cliente con DNI {dni}")


def _dni_registrado(db, s, dni):
    return db.clientes.find_one({"dni": dni}, {"_id": 1}, session=s) is not None


def _buscar_activo(db, s, id_cliente):
    cliente = db.clientes.find_one({"_id": id_cliente}, session=s)
    if cliente is None:
        raise NoEncontrado("CLIENTE_INEXISTENTE", f"no existe el cliente {id_cliente}")
    if not cliente["activo"]:
        raise ValidacionError("CLIENTE_INACTIVO", f"el cliente {id_cliente} está dado de baja")
    return cliente


def _en_transaccion(operacion):
    # Lectura y escritura en una misma transacción: si otro proceso escribe el mismo documento (o el contador)
    # en el medio, MongoDB aborta con TransientTransactionError y se vuelve a validar desde cero.
    for intento in range(INTENTOS):
        try:
            with conexiones.get_client().start_session() as s:
                with s.start_transaction():
                    cliente = operacion(conexiones.get_db(), s)
            return formato.a_json({"id_cliente": cliente["_id"], **cliente})
        except PyMongoError as e:
            # Sin servidor no hay conflicto que reintentar: pymongo marca igual como transitorio el error de
            # selección de servidor dentro de una transacción, y cada intento volvería a esperarlo entero.
            sin_servidor = isinstance(e, ServerSelectionTimeoutError)
            if sin_servidor or not e.has_error_label("TransientTransactionError") or intento == INTENTOS - 1:
                raise
            time.sleep(random.uniform(0.015, 0.15) * (intento + 1))


def alta_cliente(datos):
    """Da de alta un cliente activo con DNI único.

    El DNI se guarda y se compara como número (normalizar_dni): 31.245.678 y 031245678 son el mismo que 31245678.

    Parámetros:
        datos: campos del cliente; nro_afiliado es obligatorio salvo con 'Sin cobertura'.
    Retorna:
        El cliente creado, con id_cliente y sus campos.
    Motor: MongoDB (clientes y contador de ids).
    Errores: ValidacionError con DATO_INVALIDO (también un DNI que no es un número de documento),
        OBRA_SOCIAL_INVALIDA o DNI_DUPLICADO.
    """
    if not isinstance(datos, dict):
        raise ValidacionError("DATO_INVALIDO", "los datos del cliente deben ser un diccionario")
    desconocidos = [c for c in datos if c not in OBLIGATORIOS + ("nro_afiliado",)]
    if desconocidos:
        raise ValidacionError("DATO_INVALIDO", f"campo desconocido: {desconocidos[0]}")
    cliente = {c: _texto(c, datos.get(c)) for c in OBLIGATORIOS}
    dni = normalizar_dni(cliente["dni"])
    if dni is None:
        detalle = "se espera un número de hasta 8 cifras, con o sin puntos"
        raise ValidacionError("DATO_INVALIDO", f"dni inválido: {cliente['dni']} ({detalle})")
    cliente["dni"] = dni
    _validar_obra_social(cliente["obra_social"])
    # Si la clave viene se valida igual que en la modificación, aunque 'Sin cobertura' después la descarte.
    if "nro_afiliado" in datos:
        _texto("nro_afiliado", datos["nro_afiliado"])
    sin_cobertura = cliente["obra_social"] == SIN_COBERTURA
    cliente["nro_afiliado"] = None if sin_cobertura else _texto("nro_afiliado", datos.get("nro_afiliado"))
    cliente["activo"] = True

    def insertar(db, s):
        if _dni_registrado(db, s, cliente["dni"]):
            raise _dni_duplicado(cliente["dni"])
        nuevo = {"_id": ids.siguiente_id("clientes", "C", session=s), **cliente}
        try:
            db.clientes.insert_one(nuevo, session=s)
        except DuplicateKeyError:
            # Dos altas de q13 no llegan a este punto: las dos incrementan el contador, la segunda choca ahí, se
            # reintenta y la frena el chequeo previo. El índice único es la segunda barrera, ante una inserción con
            # ese DNI que no pase por q13.
            raise _dni_duplicado(cliente["dni"]) from None
        return nuevo

    return _en_transaccion(insertar)


def modificar_cliente(id_cliente, cambios):
    """Modifica el contacto, el domicilio o la cobertura de un cliente activo.

    Parámetros:
        id_cliente, cambios: id y claves entre email, telefono, ciudad, provincia, obra_social y nro_afiliado.
    Retorna:
        El cliente modificado, con id_cliente y sus campos.
    Motor: MongoDB (clientes).
    Errores: NoEncontrado si el cliente no existe; ValidacionError con DATO_INVALIDO (también un id que no es
        texto), CAMPO_NO_MODIFICABLE, OBRA_SOCIAL_INVALIDA, AFILIADO_REQUERIDO o CLIENTE_INACTIVO.
    """
    validar_id("id_cliente", id_cliente)
    if not isinstance(cambios, dict) or not cambios:
        raise ValidacionError("DATO_INVALIDO", "no se indicó ningún cambio")
    ajenos = [c for c in cambios if c not in MODIFICABLES]
    if ajenos:
        raise ValidacionError("CAMPO_NO_MODIFICABLE", f"{ajenos[0]} no se puede modificar")
    nuevos = {c: _texto(c, v) for c, v in cambios.items()}
    if "obra_social" in nuevos:
        _validar_obra_social(nuevos["obra_social"])

    def actualizar(db, s):
        actual = _buscar_activo(db, s, id_cliente)
        obra_social = nuevos.get("obra_social", actual["obra_social"])
        cambio = dict(nuevos)
        if obra_social == SIN_COBERTURA:
            cambio["nro_afiliado"] = None
        elif obra_social != actual["obra_social"] and "nro_afiliado" not in nuevos:
            raise ValidacionError("AFILIADO_REQUERIDO", f"pasar a {obra_social} exige el número de afiliado")
        return db.clientes.find_one_and_update({"_id": id_cliente}, {"$set": cambio},
                                               return_document=ReturnDocument.AFTER, session=s)

    return _en_transaccion(actualizar)


def baja_cliente(id_cliente):
    """Da de baja lógica a un cliente; si ya está inactivo no cambia nada.

    Parámetros:
        id_cliente: id del cliente, p. ej. "C001".
    Retorna:
        El cliente resultante, con id_cliente y sus campos.
    Motor: MongoDB (clientes).
    Errores: NoEncontrado si el cliente no existe; ValidacionError con DATO_INVALIDO si el id no es texto.
    """
    validar_id("id_cliente", id_cliente)

    def desactivar(db, s):
        actual = db.clientes.find_one({"_id": id_cliente}, session=s)
        if actual is None:
            raise NoEncontrado("CLIENTE_INEXISTENTE", f"no existe el cliente {id_cliente}")
        if not actual["activo"]:
            return actual
        return db.clientes.find_one_and_update({"_id": id_cliente}, {"$set": {"activo": False}},
                                               return_document=ReturnDocument.AFTER, session=s)

    return _en_transaccion(desactivar)
