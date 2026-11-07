from collections import Counter, defaultdict

from farmared import dominio

COLUMNAS = {
    "clientes": ("id_cliente", "nombre", "apellido", "dni", "email", "telefono", "ciudad", "provincia", "obra_social",
                 "nro_afiliado", "activo"),
    "sucursales": ("id_sucursal", "nombre", "tipo", "direccion", "ciudad", "provincia", "telefono", "activo"),
    "farmaceuticos": ("id_farmaceutico", "nombre", "apellido", "matricula", "cargo", "id_sucursal", "activo"),
    "proveedores": ("id_proveedor", "razon_social", "cuit", "tipo", "ciudad", "provincia", "telefono", "activo"),
    "productos": ("id_producto", "nombre", "principio_activo", "categoria", "presentacion", "condicion_venta",
                  "precio_unit", "id_proveedor", "activo"),
    "stock_lotes": ("id_lote", "id_producto", "id_sucursal", "nro_lote", "unidades", "vencimiento"),
    "recetas": ("id_receta", "id_cliente", "medico", "matricula_medico", "fecha_emision", "tipo",
                "dispensas_autorizadas", "dispensas_realizadas", "proxima_dispensa", "estado"),
    "ventas": ("id_venta", "id_cliente", "id_farmaceutico", "id_receta", "fecha", "tipo", "medio_pago", "total",
               "estado"),
    "detalle_ventas": ("id_detalle", "id_venta", "id_producto", "cantidad", "precio_unit"),
}
CLAVES = {archivo: columnas[0] for archivo, columnas in COLUMNAS.items()}
UNICAS = {"clientes": "dni", "farmaceuticos": "matricula", "proveedores": "cuit"}
REFERENCIAS = {
    "farmaceuticos": {"id_sucursal": "sucursales"},
    "productos": {"id_proveedor": "proveedores"},
    "stock_lotes": {"id_producto": "productos", "id_sucursal": "sucursales"},
    "recetas": {"id_cliente": "clientes"},
    "ventas": {"id_cliente": "clientes", "id_farmaceutico": "farmaceuticos", "id_receta": "recetas"},
    "detalle_ventas": {"id_venta": "ventas", "id_producto": "productos"},
}
OPCIONALES = {"clientes": {"nro_afiliado"}, "ventas": {"id_receta"}, "recetas": {"proxima_dispensa"}}
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
            if tuple(fila) != COLUMNAS[archivo]:
                yield _error(archivo, n, fila, "encabezado", "columnas distintas de las esperadas")


def _obligatorio(t):
    for archivo, numeradas in t.todas.items():
        opcionales = OPCIONALES.get(archivo, set())
        for n, fila in numeradas:
            for campo, valor in fila.items():
                # Una columna que no es del archivo la informa [encabezado], como la que falta.
                if valor is None and campo in COLUMNAS[archivo] and campo not in opcionales:
                    yield _error(archivo, n, fila, "obligatorio", f"{campo} vacío")


def _id_repetido(t):
    for archivo, numeradas in t.todas.items():
        clave, vistos = CLAVES[archivo], set()
        for n, fila in numeradas:
            if fila.get(clave) is None:
                continue
            if fila[clave] in vistos:
                yield _error(archivo, n, fila, "id-repetido", "id repetido")
            vistos.add(fila[clave])


def _clave_unica(t):
    for archivo, campo in UNICAS.items():
        vistos = set()
        for n, fila in t.todas[archivo]:
            valor = fila.get(campo)
            if valor is None:
                continue
            if valor in vistos:
                yield _error(archivo, n, fila, "clave-unica", f"{campo} {valor} repetido")
            vistos.add(valor)


def _referencia(t):
    for archivo, campos in REFERENCIAS.items():
        for n, fila in t.todas[archivo]:
            for campo, destino in campos.items():
                valor = fila.get(campo)
                if valor is not None and valor not in t.indice[destino]:
                    yield _error(archivo, n, fila, "referencia", f"{campo} {valor} inexistente")


def _dominio(t):
    for archivo, campos in DOMINIOS.items():
        for n, fila in t.todas[archivo]:
            for campo, validos in campos.items():
                valor = fila.get(campo)
                if valor is not None and valor not in validos:
                    yield _error(archivo, n, fila, "dominio", f"{campo} {valor} fuera de dominio")


def _afiliado(t):
    for n, c in t.todas["clientes"]:
        if c.get("obra_social") not in dominio.OBRAS_SOCIALES or "nro_afiliado" not in c:
            continue
        if (c["obra_social"] == "Sin cobertura") != (c["nro_afiliado"] is None):
            detalle = "sin nro_afiliado" if c["nro_afiliado"] is None else f"con nro_afiliado {c['nro_afiliado']}"
            yield _error("clientes", n, c, "afiliado", f"{c['obra_social']} {detalle}")


def _detalle_total(venta, items):
    """Devuelve qué informar sobre el total de la venta, o None si no hay nada que informar."""
    if not items:
        return "venta sin ítems"
    if venta.get("total") is None or any(d.get("cantidad") is None or d.get("precio_unit") is None for d in items):
        return None
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
        # Con el estado vacío o inválido no se sabe si la venta cuenta; ya lo informó [obligatorio] o [dominio].
        if estado not in dominio.ESTADOS_VENTA:
            inciertas.add(v["id_receta"])
        elif estado == "Completada":
            completadas[v["id_receta"]] += 1
    for n, r in t.primeras["recetas"]:
        realizadas, autorizadas = r.get("dispensas_realizadas"), r.get("dispensas_autorizadas")
        if realizadas is None:
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
        if autorizadas is not None and tipo in MAX_DISPENSAS:
            if not 1 <= autorizadas <= MAX_DISPENSAS[tipo]:
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
        receta = t.indice["recetas"].get(v.get("id_receta"), {})
        fecha, emision = v.get("fecha"), receta.get("fecha_emision")
        if fecha is not None and emision is not None and fecha < emision:
            yield _error("ventas", n, v, "receta-fecha",
                         f"{fecha:%Y-%m-%d} anterior a la receta {emision:%Y-%m-%d}")


REGLAS = (_encabezado, _obligatorio, _id_repetido, _clave_unica, _referencia, _dominio, _afiliado, _total, _tipo_venta,
          _receta_cliente, _receta_requerida, _venta_en_farmacia, _dispensas, _receta_coherente, _receta_fecha)


def errores(filas):
    """Devuelve todos los errores de los datos leídos; lista vacía si son válidos.

    Parámetros:
        filas: lo que devuelve lector.leer_todo().
    Retorna:
        Lista de "<archivo>.csv <id>: [etiqueta] detalle", ordenada por regla y fila.
    """
    tablas = _Tablas(filas)
    return [error for regla in REGLAS for error in regla(tablas)]
