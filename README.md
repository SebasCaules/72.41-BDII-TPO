# FarmaRed

FarmaRed es una red de farmacias (Buenos Aires, Santa Fe y Córdoba) con una droguería propia. Implementamos su backoffice en Python 3.12 sobre dos motores NoSQL: en MongoDB guardamos las entidades y sus relaciones, y en Redis el stock por lote. Desde la línea de comandos se cargan los datos, se corren las doce consultas (q01 a q12) y los tres servicios de escritura (q13 a q15), y se generan los resultados de ejemplo que usamos en el informe.

## Requisitos

- Una cuenta de GitHub con acceso a Codespaces.
- Nada más. El entorno trae todo y no hay que instalar nada a mano. MongoDB 8.3.13 y Redis 8.10.3 tienen la versión fijada, igual que `pymongo`, `redis` y `pytest` en `requirements.txt`; Python es la 3.12.x que trae la imagen del devcontainer al crear el Codespace.

## Levantar en Codespaces

1. Desde la página del repositorio, `Code` → `Codespaces` → `Create codespace on main`. Los pasos 2 y 3 ocurren solos al crear el codespace; los pasos 4 y 5 los corremos a mano en la terminal.
2. El devcontainer levanta tres servicios con Docker Compose: `app` (Python 3.12, donde queda la terminal), `mongo` y `redis`. MongoDB arranca como replica set `rs0` de un nodo y se inicia solo; Redis arranca con persistencia AOF.
3. Al crear el entorno se instalan las dependencias de `requirements.txt` (`pymongo`, `redis`, `pytest`). Las variables de conexión (`MONGO_URI`, `MONGO_DB`, `REDIS_URL`, `REDIS_DB`) y la zona horaria (`America/Argentina/Buenos_Aires`) ya están definidas en el servicio `app`. Esperamos a que termine esta instalación antes de usar la terminal: si el comando del paso 4 informa `ModuleNotFoundError`, la instalación todavía no terminó; si ya terminó y el error sigue, la repetimos con `pip install --user -r requirements.txt`.
4. Para comprobar que quedó arriba, desde la terminal del Codespace (en la carpeta del repositorio, donde se abre):

```
python -c "from farmared.conexiones import get_client, get_redis; print(get_client().admin.command('ping')['ok'], get_redis().ping())"
```

Si ambos motores responden, imprime `1.0 True`. Si alguno no responde, termina en unos segundos con una traza cuya última línea empieza con `pymongo.errors` (MongoDB) o `redis.exceptions` (Redis).

5. Cargamos los datos completos, como se explica en la sección siguiente:

```
python -m farmared carga
```

Todos los comandos de este archivo se corren desde la raíz del repositorio.

Si a mitad de la sesión se detiene un motor, el paso 4 deja de imprimir `1.0 True` y los comandos que lo usan informan `Error [CONEXION]` (ver Salida y errores). Los servicios no se reinician solos, y desde la terminal no se pueden levantar porque `app` no tiene Docker: detenemos el Codespace desde github.com/codespaces y lo volvemos a abrir, y al iniciarse levanta otra vez los tres servicios. Los datos quedan en volúmenes de Docker y se conservan; para volver a los datos iniciales, corremos de nuevo `python -m farmared carga`.

## Cargar datos

```
python -m farmared carga [--solo-provistos] [--validar]
```

- Sin opciones, valida los CSV de `datos/provistos/` y `datos/adicionales/` y los carga en MongoDB y Redis. Si la validación encuentra errores, no escribe nada y los informa. Sin la carpeta `datos/adicionales/` la carga se rechaza: para cargar solo los provistos está `--solo-provistos`.
- `--solo-provistos` omite `datos/adicionales/` y carga solo los nueve CSV provistos.
- `--validar` solo valida: no escribe. Sin errores imprime `[]` y sale con 0; con errores imprime uno por línea y sale con 1.

Con los datos completos, `python -m farmared carga` imprime los documentos cargados por colección (22 clientes, 15 sucursales, 18 farmacéuticos, 15 proveedores, 23 productos, 19 recetas, 31 ventas y 3 contadores) y los 38 lotes de Redis. Con `--solo-provistos` quedan 8 clientes, 5 sucursales, 7 farmacéuticos, 5 proveedores, 13 productos, 9 recetas, 16 ventas y 3 contadores, y 18 lotes. Además, cada carga borra y vuelve a crear la vista `ingresos_mes_actual` de q11, que no figura en esos conteos.

La carga es destructiva e idempotente: borramos y recreamos las colecciones, los índices y los contadores de MongoDB, y en Redis borramos por prefijo las claves del esquema (nunca vaciamos la base). Volver a cargar borra lo creado por q13 y q14 y revierte los descuentos de stock de q15: la carga reinicia el entorno de prueba y no es una operación del sistema. La regla de bajas lógicas rige para los servicios, no para la carga.

Los registros propios de `datos/adicionales/` y el caso que ejercita cada uno están descritos en `datos/adicionales/CASOS.md`.

## Ejecutar consultas

```
python -m farmared <comando> [parámetros]
```

`python -m farmared --help` lista los comandos, y `python -m farmared <comando> --help` describe los parámetros de cada uno.

Los ejemplos de esta sección y de la siguiente suponen los datos completos recién cargados (después de `demo` hay que volver a correr `carga`; ver Resultados de ejemplo). Entre las consultas, lo que devuelven q05, q06, q11 y q12 y la marca `vencido` de q08 dependen del día en que se corren; ver Fechas.

| Ejemplo | Qué devuelve |
| --- | --- |
| `python -m farmared q01` | Productos activos con todos los datos de su proveedor: 20 productos. |
| `python -m farmared q02` | Ventas 'Pendiente' con el farmacéutico (nombre y matrícula), la sucursal y el total: V012, V011, V025, V024 y V023. |
| `python -m farmared q03 C014` | Historial del cliente C014, recetas y ventas en orden cronológico: RC010, RC011, V020, V021, RC012 y V022. Un cliente inexistente da `CLIENTE_INEXISTENTE`. |
| `python -m farmared q04` | Clientes con más de una receta: C014 con 3, y C001, C002 y C006 con 2. |
| `python -m farmared q05` | Farmacéuticos activos con su cantidad de ventas no anuladas de los últimos 60 días, incluidos los que tienen cero. `--dias 30` cambia la ventana. |
| `python -m farmared q06` | Recetas de tratamiento prolongado vigentes con la próxima dispensa vencida, con los datos del cliente. |
| `python -m farmared q07 --limite 3` | Los productos más vendidos en unidades, solo ventas 'Completada': PRD005 6, PRD011 6 y PRD001 4. Sin `--limite` es el top 5. |
| `python -m farmared q08 --umbral 20` | Lotes con menos unidades que el umbral (50 si no se indica), con producto, sucursal, proveedor y la marca `vencido`: L020, L010, L037, L018, L003 y L031. |
| `python -m farmared q09 --monto 4500` | Ventas 'Venta libre' no anuladas con total menor al monto (5000 si no se indica): V013, V030, V025 y V031. |
| `python -m farmared q10 S006` | Clientes atendidos en la sucursal S006 por cualquiera de sus farmacéuticos, activos o no: C011, C012, C015 y C016. Una sucursal inexistente da `SUCURSAL_INEXISTENTE`. |
| `python -m farmared q11` | Ingresos y cantidad de ventas 'Completada' por farmacéutico en el mes actual, leídos de la vista `ingresos_mes_actual`, que crea `carga`. En noviembre de 2026: F008 9100, F010 6900 y F009 5100. Sobre una base sin cargar da `BASE_SIN_CARGA`. |
| `python -m farmared q12` | Clientes sin ventas en el último año, con su última venta si la tienen: C004, C008, C009, C010, C011, C012 y C018. |

## Ejecutar servicios

Los tres servicios escriben en las bases. Los ejemplos van en este orden, a partir de una carga nueva.

q13 es el ABM de clientes. El alta valida que el DNI no exista, aunque sea de un cliente dado de baja, y devuelve el cliente creado; tras una carga nueva su id es `C023`:

```
python -m farmared q13 alta --nombre Valeria --apellido Quiroga --dni 99300400 --email valeria.quiroga@gmail.com --telefono 1162004400 --ciudad "La Plata" --provincia "Buenos Aires" --obra-social IOMA --nro-afiliado IO-993004
python -m farmared q13 modificar C023 --email vquiroga@hotmail.com --obra-social OSDE --nro-afiliado OS-993004
python -m farmared q13 baja C023
python -m farmared q13 alta --nombre Valentina --apellido Quiroga --dni 99300400 --email valentina.quiroga@gmail.com --telefono 1162004400 --ciudad "La Plata" --provincia "Buenos Aires" --obra-social "Sin cobertura"
```

La modificación acepta solo `--email`, `--telefono`, `--ciudad`, `--provincia`, `--obra-social` y `--nro-afiliado`; pasar a otra obra social con cobertura exige el número de afiliado (`AFILIADO_REQUERIDO`). La baja es lógica: el cliente queda con `activo: false`. El último comando se rechaza con `DNI_DUPLICADO`. El DNI se compara y se guarda como número, solo con sus dígitos: `31.245.678` y `031245678` son el mismo DNI que `31245678`, y lo que no es un número de hasta 8 cifras se rechaza con `DATO_INVALIDO`.

q14 registra una venta 'Completada' y, dentro de la misma transacción, descuenta el stock invocando a q15:

```
python -m farmared q14 --cliente C003 --farmaceutico F006 --item PRD004:1 --medio-pago "Obra social" --receta RC002
python -m farmared q14 --cliente C007 --farmaceutico F003 --item PRD010:1 --medio-pago Débito --receta RC006
```

El primero crea la venta `V032` con total 6200 y la fecha del día, deja la receta RC002 en 3 de 3 dispensas y 'Completada', y descuenta una unidad del lote L007 (22 → 21; se ve con `q08`). El segundo se rechaza con `STOCK_INSUFICIENTE`: el único lote de PRD010 en la sucursal de F003 venció el 31/10/2026, y no queda ni la venta ni la receta modificada. `--item` es `PRODUCTO:CANTIDAD`, con la cantidad en dígitos, y se repite para vender varios productos (`--item PRD001:2 --item PRD002:1`); `--receta` solo hace falta si alguno es bajo receta.

q15 descuenta el stock de una venta ya registrada, por orden de vencimiento y sin lotes vencidos:

```
python -m farmared q15 V003
```

Se rechaza con `STOCK_YA_DESCONTADO`. Toda venta 'Completada' de la carga entra con el stock ya descontado, y q14 llama a q15 al registrar cada venta, así que desde la línea de comandos q15 siempre rechaza: con `STOCK_YA_DESCONTADO` sobre una venta completada (también la `V032` de q14) y con `VENTA_NO_COMPLETADA` sobre una pendiente (`q15 V024`). El descuento exitoso se ve en q14 y en el resultado de ejemplo de q15 que genera `demo`.

## Resultados de ejemplo

```
python -m farmared demo
```

Recarga los datos completos, corre q01 a q12 con parámetros de ejemplo (q03 con `C001`, q10 con `S001`) y escribe `docs/resultados/q01.json` a `q12.json`. Después vuelve a cargar los datos y corre los escenarios de los servicios, con el estado antes y después de las entidades que toca cada uno, y escribe `q13.json`, `q14.json` y `q15.json`. q13 hace un alta, una modificación, una baja y un alta rechazada por DNI repetido; q14, la venta de RC002 de arriba, una dispensa intermedia de RC004 y dos rechazos (cliente inactivo y lote vencido); q15 descuenta una venta insertada sin descuento, como si viniera de una importación, y muestra los dos rechazos. Cada archivo tiene la forma `{"generado": "AAAA-MM-DD", "parametros": {...}, "resultado": ...}`, y el comando imprime la lista de rutas escritas. `demo` ordena las claves de cada elemento para facilitar la lectura; el contenido es el mismo que imprime la línea de comandos, que puede traerlas en otro orden.

`demo` es destructivo igual que `carga`: borra lo que hayan creado los servicios y reemplaza los archivos de `docs/resultados/`, que quedan con la fecha del día en que se corre (campo `generado`). De esa fecha dependen los resultados de q05, q06, q11 y q12 y las fechas de las ventas nuevas de los servicios (ver Fechas), así que dos corridas en días distintos pueden dar archivos distintos. Para volver a los archivos versionados en el repositorio:

```
git restore docs/resultados
```

Al terminar, las bases quedan con los cambios de los escenarios de los servicios: el cliente `C023` dado de baja con el DNI 99300400, las ventas nuevas `V032`, `V033` y `V034`, y los lotes L007 en 21, L005 en 39 y L004 en 89 unidades. L005 vence el 30/11/2026: desde el día siguiente la dispensa de RC004 descuenta de L015 (100 → 99) y L005 queda en 40. Antes de repetir los ejemplos de consultas o de servicios hay que volver a cargar los datos; si no, el alta de q13 se rechaza con `DNI_DUPLICADO` y las consultas que cuentan ventas o stock devuelven otros valores:

```
python -m farmared carga
```

## Salida y errores

La salida es JSON con sangría de dos espacios y sin escapar caracteres no ASCII, por stdout. Los errores van por stderr:

- Un error de validación o de negocio se informa como `Error [CODIGO]: mensaje` y el proceso sale con 1. Por ejemplo, `--limite`, `--umbral` y `--monto` tienen que ser al menos 1 y `--dias` no puede ser negativo: si no, el error es `DATO_INVALIDO`. Sobre una base sin cargar, q11 y el alta de q13 informan `BASE_SIN_CARGA`.
- Si un comando necesita MongoDB o Redis y ese motor no responde (detenido o colgado), lo informa después de esperarlo hasta 3 segundos, como `Error [CONEXION]: MongoDB no responde` o `Error [CONEXION]: Redis no responde`, y sale con 1. `carga` y `demo` comprueban los dos motores antes de escribir: si uno no responde, no tocan ninguno.
- Cualquier otro error de un motor también se informa con un código y sale con 1: `CONFLICTO` cuando una escritura simultánea canceló la operación después de los reintentos (se puede volver a correr) y `MOTOR`, con el mensaje del motor, en los demás casos.
- Un parámetro faltante o mal formado lo informa argparse con el uso del comando y sale con 2. Las opciones no se abrevian (`--lim` no reemplaza a `--limite`), y un `--item` que no tiene la forma `PRODUCTO:CANTIDAD` con la cantidad en dígitos también es un error de uso.

## Fechas

"Hoy" es la fecha local del contenedor, nunca una fecha fija, así que varias salidas cambian según el día en que se corren: q05 cuenta los últimos 60 días, q06 compara la próxima dispensa con hoy, q11 toma el mes actual del servidor de MongoDB, q12 mira el último año, q08 marca como vencidos los lotes cuyo vencimiento ya pasó, q14 fecha la venta hoy y calcula la próxima dispensa a 30 días, y q15 (también cuando la invoca q14) omite los lotes vencidos. La carga, además, rechaza las fechas posteriores a hoy. Los registros adicionales están pensados para noviembre de 2026; `datos/adicionales/CASOS.md` detalla qué resultado da cada consulta y hasta cuándo se mantiene.

## Tests

```
python -m pytest -q
```

Corremos los tests sobre la base `farmared_test` de MongoDB y la base 1 de Redis, nunca sobre las de trabajo. La suite se niega a empezar si la base de MongoDB configurada no termina en `_test`. Cada test que necesita datos los recarga. Por defecto fijan hoy en el 3 de noviembre de 2026, y algunos fijan otro día para probar un borde. Los que corren la línea de comandos en un proceso aparte no reciben esa fecha, así que usan la fecha real; cuando el resultado depende del día, comparan su salida con la de la función evaluada en la fecha real. Los de q11 que leen la vista también usan la fecha real, porque el mes lo calcula el servidor de MongoDB; el que revisa los datos completos corre la definición de la vista con instantes fijos en lugar de la fecha del servidor, así que vale en cualquier mes.

## Estructura

```
.
├── .devcontainer/                devcontainer.json  docker-compose.yml
├── datos/
│   ├── provistos/*.csv           los nueve CSV del enunciado, sin modificar
│   └── adicionales/              filas propias, mismos nombres y columnas que provistos, y CASOS.md
├── docs/
│   ├── resultados/qNN.json       salida de demo
│   └── diagramas/                fuentes SVG y PNG de los diagramas del informe
├── farmared/
│   ├── __main__.py               línea de comandos
│   ├── config.py  conexiones.py  configuración y conexiones a MongoDB y Redis
│   ├── fechas.py  errores.py  formato.py  dominio.py  claves.py  ids.py
│   ├── stock.py                  descuento de stock por lote y su compensación
│   ├── lua/descontar_fefo.lua    script que descuenta todos los ítems o ninguno
│   ├── lua/reponer_venta.lua     script que deshace el descuento registrado de una venta
│   ├── carga/                    lector, validación y carga en MongoDB y Redis
│   ├── consultas/                q01 a q15, un módulo por consulta
│   ├── demo.py  demo_servicios.py   resultados de ejemplo
│   └── __init__.py
├── tests/                        conftest.py, snapshots.py y los test_*.py
├── .gitignore  pytest.ini  requirements.txt
└── README.md
```
