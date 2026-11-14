from farmared import carga, conexiones

COLECCIONES = ("clientes", "sucursales", "farmaceuticos", "proveedores", "productos", "recetas", "ventas",
               "contadores")


def identidades(db):
    """El uuid de cada colección: MongoDB le da uno nuevo cada vez que la colección se crea."""
    return {c["name"]: c["info"]["uuid"] for c in db.list_collections(filter={"type": "collection"})
            if c["name"] in COLECCIONES}


def tablas_abiertas():
    estado = conexiones.get_client().admin.command("serverStatus")
    return estado["wiredTiger"]["data-handle"]["connection data handles currently active"]


def test_volver_a_cargar_conserva_las_colecciones(datos_provistos, db):
    antes = identidades(db)
    assert set(antes) == set(COLECCIONES)
    carga.cargar(solo_provistos=True)
    assert identidades(db) == antes


def test_muchas_cargas_seguidas_no_acumulan_tablas_en_el_servidor(datos_provistos):
    antes = tablas_abiertas()
    for _ in range(20):
        carga.cargar(solo_provistos=True)
    # Borrando y recreando, cada carga deja abiertas las tablas de sus ocho colecciones y de sus índices.
    assert tablas_abiertas() - antes < 20


def test_la_carga_quita_un_indice_que_no_es_del_modelo(datos_provistos, db):
    db.clientes.create_index("email")
    assert "email_1" in db.clientes.index_information()
    carga.cargar(solo_provistos=True)
    assert set(db.clientes.index_information()) == {"_id_", "dni_1"}


def test_la_carga_vacia_lo_que_agregaron_los_servicios(datos_provistos, db):
    db.clientes.insert_one({"_id": "C900", "dni": "99000111"})
    db.ventas.insert_one({"_id": "V900", "estado": "Pendiente"})
    carga.cargar(solo_provistos=True)
    assert db.clientes.find_one({"_id": "C900"}) is None
    assert db.ventas.find_one({"_id": "V900"}) is None
