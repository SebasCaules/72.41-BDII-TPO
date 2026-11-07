from collections import Counter, defaultdict

from farmared import dominio

CLAVES = {"clientes": "id_cliente", "sucursales": "id_sucursal", "farmaceuticos": "id_farmaceutico",
          "proveedores": "id_proveedor", "productos": "id_producto", "stock_lotes": "id_lote",
          "recetas": "id_receta", "ventas": "id_venta", "detalle_ventas": "id_detalle"}
UNICAS = {"clientes": "dni", "farmaceuticos": "matricula", "proveedores": "cuit"}
REFERENCIAS = {
    "farmaceuticos": {"id_sucursal": "sucursales"},
    "productos": {"id_proveedor": "proveedores"},
    "stock_lotes": {"id_producto": "productos", "id_sucursal": "sucursales"},
    "recetas": {"id_cliente": "clientes"},
    "ventas": {"id_cliente": "clientes", "id_farmaceutico": "farmaceuticos", "id_receta": "recetas"},
    "detalle_ventas": {"id_venta": "ventas", "id_producto": "productos"},
}
OPCIONALES = {"id_receta"}
DOMINIOS = {
    "clientes": {"obra_social": dominio.OBRAS_SOCIALES},
    "sucursales": {"tipo": dominio.TIPOS_SUCURSAL},
    "farmaceuticos": {"cargo": dominio.CARGOS},
    "proveedores": {"tipo": dominio.TIPOS_PROVEEDOR},
    "productos": {"condicion_venta": dominio.CONDICIONES_VENTA},
    "recetas": {"tipo": dominio.TIPOS_RECETA, "estado": dominio.ESTADOS_RECETA},
    "ventas": {"tipo": dominio.TIPOS_VENTA, "medio_pago": dominio.MEDIOS_DE_PAGO, "estado": dominio.ESTADOS_VENTA},
}
MAX_DISPENSAS = {"Simple": 1, "Archivada": 1, "Tratamiento prolongado": 3}


def _error(archivo, n, fila, etiqueta, detalle):
    id_ = fila.get(CLAVES[archivo])
    return f"{archivo}.csv {f'fila {n}' if id_ is None else id_}: [{etiqueta}] {detalle}"


def _primeras(archivo, numeradas):
    """Descarta las repeticiones de un id, que ya informó [id-repetido]."""
    vistos, salida = set(), []
    for n, fila in numeradas:
        id_ = fila.get(CLAVES[archivo])
        if id_ is None or id_ not in vistos:
            salida.append((n, fila))
        if id_ is not None:
            vistos.add(id_)
    return salida


class _Tablas:
    def __init__(self, filas):
        self.todas = {a: list(enumerate(filas.get(a) or [], start=1)) for a in CLAVES}
        self.primeras = {a: _primeras(a, self.todas[a]) for a in CLAVES}
        self.indice = {a: {f[CLAVES[a]]: f for _, f in self.primeras[a] if f.get(CLAVES[a]) is not None}
                       for a in CLAVES}
        self.items = defaultdict(list)
        for _, d in self.primeras["detalle_ventas"]:
            if d.get("id_venta") is not None:
                self.items[d["id_venta"]].append(d)
        # Una fila descartada pudo ser la que cerraba la cuenta: lo que dependía de ella no se puede afirmar.
        self.ventas_inciertas = ({d.get("id_venta") for d in self._descartadas("detalle_ventas")}
                                 | {v.get("id_venta") for v in self._descartadas("ventas")})
        self.recetas_inciertas = {v.get("id_receta") for v in self._descartadas("ventas")}

    def _descartadas(self, archivo):
        conservadas = {n for n, _ in self.primeras[archivo]}
        return [fila for n, fila in self.todas[archivo] if n not in conservadas]


def _encabezado(t):
    for archivo, numeradas in t.todas.items():
        for n, fila in numeradas:
            if list(fila) != list(numeradas[0][1]):
                yield _error(archivo, n, fila, "encabezado", "columnas distintas de las de la primera fila")


def _id_repetido(t):
    for archivo, numeradas in t.todas.items():
        clave, vistos = CLAVES[archivo], set()
        for n, fila in numeradas:
            if clave not in fila:
                continue
            if fila[clave] is None:
                yield _error(archivo, n, fila, "id-repetido", "id vacío")
            elif fila[clave] in vistos:
                yield _error(archivo, n, fila, "id-repetido", "id repetido")
            vistos.add(fila[clave])


def _clave_unica(t):
    for archivo, campo in UNICAS.items():
        vistos = set()
        for n, fila in t.todas[archivo]:
            if campo not in fila:
                continue
            valor = fila[campo]
            # El índice único de MongoDB trata los nulos como iguales: dos vacíos también chocan.
            if valor in vistos:
                detalle = f"{campo} vacío repetido" if valor is None else f"{campo} {valor} repetido"
                yield _error(archivo, n, fila, "clave-unica", detalle)
            vistos.add(valor)


def _referencia(t):
    for archivo, campos in REFERENCIAS.items():
        for n, fila in t.todas[archivo]:
            for campo, destino in campos.items():
                if campo not in fila:
                    continue
                valor = fila[campo]
                if valor is None:
                    if campo not in OPCIONALES:
                        yield _error(archivo, n, fila, "referencia", f"{campo} vacío")
                elif valor not in t.indice[destino]:
                    yield _error(archivo, n, fila, "referencia", f"{campo} {valor} inexistente")


def _dominio(t):
    for archivo, campos in DOMINIOS.items():
        for n, fila in t.todas[archivo]:
            for campo, validos in campos.items():
                if campo not in fila:
                    continue
                valor = fila[campo]
                if valor is None:
                    yield _error(archivo, n, fila, "dominio", f"{campo} vacío")
                elif valor not in validos:
                    yield _error(archivo, n, fila, "dominio", f"{campo} {valor} fuera de dominio")


def _detalle_total(venta, items):
    """Devuelve qué informar sobre el total de la venta, o None si no hay nada que informar."""
    if not items:
        return "venta sin ítems"
    if "total" not in venta or any("cantidad" not in d or "precio_unit" not in d for d in items):
        return None
    if venta["total"] is None:
        return "total vacío"
    if any(d["cantidad"] is None or d["precio_unit"] is None for d in items):
        return "ítem con cantidad o precio vacío"
    suma = sum(d["cantidad"] * d["precio_unit"] for d in items)
    return None if venta["total"] == suma else f"{venta['total']} ≠ suma de ítems {suma}"


def _total(t):
    for n, v in t.primeras["ventas"]:
        if v.get("id_venta") is not None and v["id_venta"] not in t.ventas_inciertas:
            detalle = _detalle_total(v, t.items[v["id_venta"]])
            if detalle:
                yield _error("ventas", n, v, "total", detalle)


def _tipo_venta(t):
    for n, v in t.primeras["ventas"]:
        if "id_receta" not in v or v.get("tipo") not in dominio.TIPOS_VENTA:
            continue
        if (v["tipo"] == "Con receta") != (v["id_receta"] is not None):
            detalle = "sin id_receta" if v["id_receta"] is None else f"con id_receta {v['id_receta']}"
            yield _error("ventas", n, v, "tipo-venta", f"{v['tipo']} {detalle}")


def _receta_cliente(t):
    for n, v in t.primeras["ventas"]:
        receta = t.indice["recetas"].get(v.get("id_receta"))
        if receta is None:
            continue
        cliente, titular = v.get("id_cliente"), receta.get("id_cliente")
        if cliente in t.indice["clientes"] and titular in t.indice["clientes"] and cliente != titular:
            yield _error("ventas", n, v, "receta-cliente", f"receta de {titular}, venta de {cliente}")


def _receta_requerida(t):
    for n, v in t.primeras["ventas"]:
        items = t.items[v["id_venta"]] if v.get("id_venta") is not None else []
        if not items or "id_receta" not in v:
            continue
        receta = v["id_receta"]
        if receta is not None and receta not in t.indice["recetas"]:
            continue
        productos = [t.indice["productos"].get(d.get("id_producto"), {}) for d in items]
        condiciones = [p.get("condicion_venta") for p in productos]
        requiere = any(c in dominio.CONDICIONES_CON_RECETA for c in condiciones)
        if requiere and receta is None:
            yield _error("ventas", n, v, "receta-requerida", "sin receta y con productos que la requieren")
        # Con una condición desconocida o un ítem descartado no se puede afirmar que ningún producto la requiera.
        elif (receta is not None and not requiere and v["id_venta"] not in t.ventas_inciertas
              and all(c in dominio.CONDICIONES_VENTA for c in condiciones)):
            yield _error("ventas", n, v, "receta-requerida", "con receta y ningún producto la requiere")


def _venta_en_farmacia(t):
    for n, v in t.primeras["ventas"]:
        farmaceutico = t.indice["farmaceuticos"].get(v.get("id_farmaceutico"), {})
        sucursal = t.indice["sucursales"].get(farmaceutico.get("id_sucursal"), {})
        tipo = sucursal.get("tipo")
        if tipo in dominio.TIPOS_SUCURSAL and tipo != "Farmacia":
            yield _error("ventas", n, v, "venta-en-farmacia",
                         f"{v['id_farmaceutico']} es de {farmaceutico['id_sucursal']}, que es {tipo}")


def _dispensas(t):
    completadas, inciertas = Counter(), set(t.recetas_inciertas)
    for _, v in t.primeras["ventas"]:
        estado = v.get("estado")
        if v.get("id_receta") is None:
            continue
        # Con el estado inválido no se sabe si la venta cuenta; ya lo informó [dominio].
        if estado not in dominio.ESTADOS_VENTA:
            inciertas.add(v["id_receta"])
        elif estado == "Completada":
            completadas[v["id_receta"]] += 1
    for n, r in t.primeras["recetas"]:
        if "dispensas_realizadas" not in r:
            continue
        realizadas, autorizadas = r["dispensas_realizadas"], r.get("dispensas_autorizadas")
        if realizadas is None:
            yield _error("recetas", n, r, "dispensas", "dispensas_realizadas vacío")
            continue
        id_ = r.get("id_receta")
        if id_ is not None and id_ not in inciertas and realizadas != completadas[id_]:
            yield _error("recetas", n, r, "dispensas",
                         f"{realizadas} realizadas ≠ {completadas[id_]} ventas completadas")
        if autorizadas is not None and realizadas > autorizadas:
            yield _error("recetas", n, r, "dispensas", f"{realizadas} realizadas > {autorizadas} autorizadas")


def _receta_coherente(t):
    for n, r in t.primeras["recetas"]:
        tipo, estado = r.get("tipo"), r.get("estado")
        autorizadas, realizadas = r.get("dispensas_autorizadas"), r.get("dispensas_realizadas")
        if "dispensas_autorizadas" in r and tipo in MAX_DISPENSAS:
            if autorizadas is None or not 1 <= autorizadas <= MAX_DISPENSAS[tipo]:
                yield _error("recetas", n, r, "receta-coherente", f"{tipo} con {autorizadas} dispensas autorizadas")
        if estado in dominio.ESTADOS_RECETA and autorizadas is not None and realizadas is not None:
            if (estado == "Completada") != (realizadas == autorizadas):
                yield _error("recetas", n, r, "receta-coherente",
                             f"{estado} con {realizadas} de {autorizadas} dispensas")
        if ("proxima_dispensa" in r and tipo in dominio.TIPOS_RECETA and estado in dominio.ESTADOS_RECETA
                and realizadas is not None):
            corresponde = tipo == "Tratamiento prolongado" and estado == "Vigente" and realizadas >= 1
            if corresponde != (r["proxima_dispensa"] is not None):
                detalle = "falta proxima_dispensa" if corresponde else "proxima_dispensa no corresponde"
                yield _error("recetas", n, r, "receta-coherente", detalle)


def _receta_fecha(t):
    for n, v in t.primeras["ventas"]:
        receta = t.indice["recetas"].get(v.get("id_receta"))
        if receta is None or "fecha" not in v or "fecha_emision" not in receta:
            continue
        fecha, emision = v["fecha"], receta["fecha_emision"]
        if fecha is None or emision is None:
            detalle = "fecha vacía" if fecha is None else f"receta {v['id_receta']} sin fecha_emision"
            yield _error("ventas", n, v, "receta-fecha", detalle)
        elif fecha < emision:
            yield _error("ventas", n, v, "receta-fecha",
                         f"{fecha:%Y-%m-%d} anterior a la receta {emision:%Y-%m-%d}")


REGLAS = (_encabezado, _id_repetido, _clave_unica, _referencia, _dominio, _total, _tipo_venta, _receta_cliente,
          _receta_requerida, _venta_en_farmacia, _dispensas, _receta_coherente, _receta_fecha)


def errores(filas):
    """Devuelve todos los errores de los datos leídos; lista vacía si son válidos.

    Parámetros:
        filas: lo que devuelve lector.leer_todo().
    Retorna:
        Lista de "<archivo>.csv <id>: [etiqueta] detalle", ordenada por regla y fila.
    """
    tablas = _Tablas(filas)
    return [error for regla in REGLAS for error in regla(tablas)]
