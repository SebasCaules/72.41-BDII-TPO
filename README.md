# FarmaRed

FarmaRed es una red de farmacias (Buenos Aires, Santa Fe y Córdoba) con una droguería propia. Implementamos su backoffice en Python 3.12 sobre dos motores NoSQL: en MongoDB guardamos las entidades y sus relaciones, y en Redis el stock por lote. La implementación está en curso: lo que aún no existe devuelve un error explícito al ejecutarse (ver Ejecutar consultas).

## Requisitos

- Una cuenta de GitHub con acceso a Codespaces.
- Nada más. Las versiones vienen fijadas en el entorno y no hay que instalar nada a mano: MongoDB 8.3.13, Redis 8.10.3 y Python 3.12.

## Levantar en Codespaces

1. Desde la página del repositorio, `Code` → `Codespaces` → `Create codespace`. Es lo único que hacemos a mano; los pasos 2 y 3 ocurren solos.
2. El devcontainer levanta tres servicios con Docker Compose: `app` (Python 3.12, donde queda la terminal), `mongo` y `redis`. MongoDB arranca como replica set `rs0` de un nodo y se inicia solo; Redis arranca con persistencia AOF.
3. Al crear el entorno se instalan las dependencias de `requirements.txt` (`pymongo`, `redis`, `pytest`). Las variables de conexión (`MONGO_URI`, `MONGO_DB`, `REDIS_URL`, `REDIS_DB`) y la zona horaria ya están definidas en el servicio `app`. Esperamos a que termine esta instalación antes de usar la terminal: si el comando del paso 4 informa `ModuleNotFoundError`, la instalación todavía no terminó.
4. Para comprobar que quedó arriba, desde la terminal del Codespace:

```
python -c "from farmared.conexiones import get_client, get_redis; print(get_client().admin.command('ping')['ok'], get_redis().ping())"
```

Si ambos motores responden, imprime `1.0 True`.

## Cargar datos

```
python -m farmared carga [--solo-provistos] [--validar]
```

- Sin opciones, valida los CSV de `datos/provistos/` y `datos/adicionales/` y los carga en MongoDB y Redis. Si la validación encuentra errores, no escribe nada y los informa.
- `--solo-provistos` omite `datos/adicionales/` y carga solo los nueve CSV provistos.
- `--validar` solo valida: no escribe. Sin errores imprime `[]` y sale con 0; con errores imprime uno por línea y sale con 1.

La carga es destructiva e idempotente: borramos y recreamos las colecciones, los índices y los contadores de MongoDB, y en Redis borramos por prefijo las claves del esquema (nunca vaciamos la base). Volver a cargar borra lo creado por q13 y q14 y revierte los descuentos de stock de q15: la carga reinicia el entorno de prueba y no es una operación del sistema. La regla de bajas lógicas rige para los servicios, no para la carga.

## Ejecutar consultas

```
python -m farmared <comando> [parámetros]
```

| Comando | Parámetros |
| --- | --- |
| `q01`, `q02`, `q04`, `q06`, `q11`, `q12` | ninguno |
| `q03` | `<id_cliente>` |
| `q05` | `[--dias 60]` |
| `q07` | `[--limite 5]` |
| `q08` | `[--umbral 50]` |
| `q09` | `[--monto 5000]` |
| `q10` | `<id_sucursal>` |
| `q13 alta` | `--nombre N --apellido A --dni D --email E --telefono T --ciudad C --provincia P --obra-social O [--nro-afiliado X]` |
| `q13 modificar` | `<id_cliente> [--email E] [--telefono T] [--ciudad C] [--provincia P] [--obra-social O] [--nro-afiliado X]` |
| `q13 baja` | `<id_cliente>` |
| `q14` | `--cliente C --farmaceutico F --item PRD001:2 [--item …] --medio-pago M [--receta RC]` |
| `q15` | `<id_venta>` |
| `demo` | ninguno |

`demo` recarga los datos completos, corre las quince consultas con parámetros de ejemplo y escribe un JSON por consulta en `docs/resultados/`. Es destructivo, igual que `carga`.

La salida es JSON con sangría de dos espacios y sin escapar caracteres no ASCII, por stdout. Los errores van por stderr:

- Un error de validación o de negocio se informa como `Error [CODIGO]: mensaje` y el proceso sale con 1.
- Un comando cuya implementación todavía no existe informa `Error: <comando> todavía no está implementado` y sale con 2.
- Un parámetro faltante o mal formado lo informa argparse con el uso del comando y también sale con 2.

## Tests

```
python -m pytest -q
```

Corremos los tests sobre la base `farmared_test` de MongoDB y la base 1 de Redis, nunca sobre las de trabajo. La suite se niega a empezar si la base de MongoDB configurada no termina en `_test`. Cada test que necesita datos los recarga.

## Estructura

Este es el árbol previsto; `datos/`, `docs/`, `farmared/stock.py`, `farmared/lua/` y los módulos de `farmared/carga/` todavía no están.

```
.
├── .devcontainer/                devcontainer.json  docker-compose.yml
├── datos/
│   ├── provistos/*.csv           los nueve CSV del enunciado, sin modificar
│   └── adicionales/              *.csv propios, mismas columnas, y CASOS.md
├── docs/
│   ├── resultados/qNN.json       salida de `demo`
│   └── diagramas/
├── farmared/
│   ├── __main__.py               línea de comandos
│   ├── config.py  conexiones.py
│   ├── fechas.py  errores.py  formato.py  dominio.py  claves.py  ids.py
│   ├── stock.py                  descuento de stock por lote
│   ├── lua/descontar_fefo.lua
│   ├── carga/                    lector, validación y carga en MongoDB y Redis
│   ├── consultas/                q01 a q15, un módulo por consulta
│   ├── demo.py  demo_servicios.py
│   └── __init__.py
├── tests/
├── .gitignore  pytest.ini  requirements.txt
└── README.md
```
