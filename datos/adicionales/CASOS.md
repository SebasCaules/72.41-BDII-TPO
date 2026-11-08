# Registros adicionales y casos que ejercitan

Estos nueve archivos agregan registros propios a los provistos, con las mismas columnas, el mismo formato y
numeración continuada. Cada caso de abajo indica qué filas lo forman, qué consulta o servicio lo muestra y qué
resultado se espera.

## Convenciones

- Datos completos: provistos más adicionales, recién cargados con `python -m farmared carga`.
- Fecha de referencia: los resultados esperados se calculan con hoy = 2026-11-03. La excepción es q11,
  que usa la fecha real del servidor: sus ventas son del 01 y el 02/11/2026, así que aparecen durante todo
  noviembre de 2026.
- Vigencia: las ventas adicionales pensadas para "últimos 60 días" tienen fecha desde el 2026-09-26 y la
  última compra del cliente con más de un año sin comprar es del 2025-07-14, de modo que los conteos que aportan
  los registros adicionales en q05 y el resultado de q12 se mantienen al menos hasta el 24/11/2026. El resto de
  q05 sí cambia con la fecha: F001 baja a 1 desde el 10/11 y F002 baja a 1 desde el 20/11, porque las ventas
  provistas V003 (2026-09-10) y V008 (2026-09-20) salen de la ventana. Las dispensas atrasadas de q06 vencieron
  el 2026-10-26 y la futura es del 2026-12-02.
- Servicios: cada caso de q13, q14 y q15 parte de una carga nueva. Después de la carga, los contadores
  quedan en `clientes` 22, `ventas` 31 y `detalle_ventas` 39, así que la primera venta que registra q14 es
  `V032` con el ítem `D040`.
- Coherencia: todo `total` es la suma de sus ítems a precio de lista; toda venta con productos bajo receta
  usa una receta vigente del mismo cliente con fecha de emisión anterior o igual a la venta; las
  `dispensas_realizadas` coinciden con las ventas 'Completada' de cada receta. Las ventas 'Completada' se
  cargan con el stock ya descontado: las unidades de cada lote son las que quedaron después de esas ventas.
  Las 'Pendiente' y 'Anulada' no descuentan.
- Lo que no se toca: no hay lotes nuevos en S001/PRD001, S001/PRD002, S001/PRD003, S002/PRD010,
  S003/PRD008, S004/PRD004 ni S004/PRD007; ninguna venta nueva usa RC002, RC004 ni RC006, y ningún DNI empieza
  con `99`. Esos datos los usan los escenarios fijos de los servicios y las altas de clientes de prueba.

## Registros por archivo

| Archivo | Filas | Ids | Qué aportan |
| --- | ---: | --- | --- |
| `clientes.csv` | 14 | C009–C022 | clientes sin compras (C009, C010, C018), con última compra de hace más de un año (C011), inactivo (C012), con una única venta anulada (C013), con tres recetas (C014) y clientes habituales |
| `sucursales.csv` | 10 | S006–S015 | farmacias nuevas en Buenos Aires, Santa Fe y Córdoba; S011 está inactiva |
| `farmaceuticos.csv` | 11 | F008–F018 | uno por farmacia nueva; F011 sin ventas, F013 activo en la sucursal inactiva, F014 inactivo con ventas de 2025 |
| `proveedores.csv` | 10 | PRV006–PRV015 | PRV010 inactivo, con un producto activo |
| `productos.csv` | 10 | PRD014–PRD023 | PRD014 'Bajo receta archivada', PRD018 de proveedor inactivo, PRD021 inactivo |
| `stock_lotes.csv` | 20 | L019–L038 | stock bajo, un lote de exactamente 50, lotes vencidos, uno que vence en menos de 30 días y cuatro lotes de un mismo producto en una sucursal |
| `recetas.csv` | 10 | RC010–RC019 | vencida, tratamiento prolongado atrasado y al día, simple sin dispensar, archivadas, una usada por una venta pendiente |
| `ventas.csv` | 15 | V017–V031 | ventas de noviembre, pendientes, una anulada, una de exactamente $5.000 y ventas de 2025 |
| `detalle_ventas.csv` | 17 | D023–D039 | ítems de esas ventas, a precio de lista |

## Casos

| Caso | Filas | Lo muestra | Resultado esperado |
| --- | --- | --- | --- |
| Ventas 'Completada' del mes actual de tres farmacéuticos | V017 (F008, 01/11), V031 (F008, 02/11), V018 (F009, 02/11), V019 (F010, 01/11) | q11, q05 | q11 con la fecha real: salen F008 con 2 ventas y $9.100, F010 con 1 y $6.900, F009 con 1 y $5.100, en ese orden. q05: las cuatro cuentan |
| Venta 'Pendiente' reciente con receta | V023 (C019, F012, RC016, 31/10, $8.400) | q02, q05 | sale en q02 con F012 (MN-18537) y S010; cuenta 1 para F012 en q05. RC016 sigue 0/1 'Vigente': una venta pendiente no consume la dispensa |
| Venta 'Pendiente' reciente sin receta | V024 (C016, F008, 30/10, $7.500) | q02, q05 | sale en q02 con F008 y S006; cuenta para F008 en q05 |
| Venta libre menor a $5.000 'Anulada' | V026 (C013, F016, 19/10, $2.500) | q09, q05 | no sale en q09; no cuenta en q05 (F016 queda con 0) |
| Venta libre menor a $5.000 'Pendiente' | V025 (C021, F015, 28/10, $4.000) | q09, q02 | sale en q09 con estado 'Pendiente' y en q02 |
| Venta libre 'Completada' de exactamente $5.000 | V027 (C020, F017, 22/10; D034 PRD016 × 2 a $2.500) | q09 | no sale: el umbral es estricto |
| Farmacéutico activo sin ventas en una farmacia nueva | F011 (S009) | q05, q10 | sale en q05 con 0 ventas; `q10 S009` devuelve una lista vacía |
| Farmacéutico inactivo con ventas viejas | F014 (S006, inactivo), V028 (2025-07-14), V029 (2025-05-06) | q05, q10 | no sale en q05; `q10 S006` incluye a C011 y C012 por sus ventas |
| Clientes activos sin compras | C009, C010, C018 | q12, q14 | salen en q12 con `ultima_venta: null`; q14 les registra una venta (ver servicios) |
| Cliente con última compra de hace más de un año | C011, V028 (2025-07-14) | q12 | sale en q12 con `ultima_venta` V028 |
| Cliente inactivo | C012 (inactivo), V029 (2025-05-06) | q12, q13, q14 | sale en q12 con `activo: false` y última venta V029; q13 no lo modifica (`CLIENTE_INACTIVO`) ni acepta un alta con su DNI (`DNI_DUPLICADO`); q14 rechaza con `CLIENTE_INACTIVO` |
| Cliente activo cuya única venta del último año está 'Anulada' | C013, V026 | q12 | no sale: toda venta registrada cuenta, cualquiera sea su estado |
| Cliente con tres recetas | C014: RC010, RC011, RC012 | q04 | sale primero, con `cantidad_recetas` 3 |
| Receta 'Vencida' | RC010 (C014) | q14 | rechaza con `RECETA_NO_VIGENTE` |
| Tratamiento prolongado 'Vigente' con próxima dispensa pasada | RC011 (C014, 2/3, próxima 2026-10-26; ventas V020 y V021) | q06, q14 | sale en q06, último, después de RC004; q14 acepta la tercera dispensa y la deja 3/3 'Completada' |
| Tratamiento prolongado 'Vigente' con próxima dispensa futura | RC013 (C017, 1/3, próxima 2026-12-02; venta V018) | q06, q14 | no sale en q06; q14 acepta y la deja 2/3 'Vigente' con próxima dispensa hoy + 30 días |
| Receta 'Simple' 'Vigente' sin dispensar | RC014 (C016, 0/1) | q14 | acepta y la deja 1/1 'Completada' |
| Lotes con menos de 50 unidades | L020, L021, L029, L031, L032, L033, L035, L038 (y los vencidos L019 y L037) | q08 | salen |
| Lote con exactamente 50 unidades | L023 (PRD005, S003) | q08 | no sale |
| Lotes vencidos | L019 (PRD002, S002, venció el 2026-10-20), L037 (PRD009, S007, venció el 2026-09-30) | q08, q14 | salen en q08 con `vencido: true`; q14 nunca los consume |
| Lote que vence en menos de 30 días | L020 (PRD002, S002, vence el 2026-11-27, 8 unidades) | q08, q14 | sale en q08 con `vencido: false`; es el primero que consume q14 |
| Producto con varios lotes en una sucursal | PRD002 en S002: L019 (vencido), L020 (2026-11-27, 8), L021 (2027-02-28, 40), L022 (2027-09-30, 150) | q14 por línea de comandos | una venta de 50 unidades consume L020 8, L021 40 y L022 2, sin tocar L019; con 199 unidades rechaza con `STOCK_INSUFICIENTE` (hay 198 vigentes) y no cambia ningún lote |
| Producto activo de un proveedor inactivo | PRD018 (PRV010, inactivo) | q01, q14 | sale en q01 con `proveedor.activo: false`; q14 lo vende |
| Producto inactivo | PRD021 | q01, q14 | no sale en q01; q14 rechaza con `PRODUCTO_INACTIVO` |
| Producto 'Bajo receta archivada' | PRD014, RC015 (C018, 'Archivada' 0/1), RC017 y V019 (C020, 'Archivada' 1/1) | q01, q14 | sale en q01; q14 sin receta rechaza con `RECETA_REQUERIDA`; con RC015 acepta y la deja 1/1 'Completada' |
| Farmacia inactiva con un farmacéutico activo | S011 (inactiva), F013 (activo) | q14 | rechaza con `SUCURSAL_INACTIVA` |

## Resultados de las consultas con datos completos

Con hoy = 2026-11-03, salvo q11.

| Consulta | Resultado esperado |
| --- | --- |
| q01 | 20 productos: PRD001 a PRD011 y PRD014 a PRD020, PRD022 y PRD023. No salen PRD012, PRD013 ni PRD021 |
| q02 | V012 (2026-10-11), V011 (2026-10-12), V025 (2026-10-28), V024 (2026-10-30), V023 (2026-10-31) |
| `q03 C014` | RC010 (04-10), RC011 (08-25), V020 (08-26), V021 (09-26), RC012 (10-14), V022 (10-14) |
| `q03 C001` | igual que con los provistos: RC001, V003, V015, V013, RC008, V010 |
| q04 | C014 3, C001 2, C002 2, C006 2 |
| q05 | F005 3, F008 3, F010 3, F001 2, F002 2, F003 1, F006 1, F009 1, F012 1, F015 1, F017 1, F018 1, F007 0, F011 0, F013 0, F016 0 (F004 y F014, inactivos, no salen) |
| q06 | RC002 (C003, 2026-09-15), RC003 (C006, 2026-10-01), RC004 (C006, 2026-10-20), RC011 (C014, 2026-10-26) |
| q07 | PRD005 6, PRD011 6, PRD001 4, PRD004 3, PRD009 3 (PRD016 y PRD017 también suman 3 y quedan fuera por id) |
| q08 | L020 8, L010 12, L037 12 (vencido), L018 15 (vencido), L003 18, L031 18, L007 22, L019 25 (vencido), L035 25, L012 30 (vencido), L029 30, L002 35, L033 36, L005 40, L021 40, L038 40, L032 44, L014 45, L011 48. L038 es de S011, que está inactiva: q08 lista los lotes cualquiera sea el estado de la sucursal |
| q09 | V013 4400, V014 4600, V030 4200, V025 4000 (Pendiente), V031 2600, ordenadas por fecha. No salen V026 (Anulada) ni V027 ($5.000) |
| `q10 S001` | igual que con los provistos: C001 (3 ventas), C006 (4) |
| `q10 S006` | C011 (1), C012 (1, inactivo), C015 (2), C016 (1) |
| `q10 S009` | lista vacía |
| q11 (fecha real, noviembre de 2026) | F008 2 ventas $9.100, F010 1 venta $6.900, F009 1 venta $5.100 |
| q12 | C004 (V001, 2025-09-18), C008 (sin ventas, inactivo), C009, C010 y C018 (sin ventas), C011 (V028, 2025-07-14), C012 (V029, 2025-05-06, inactivo) |

## Servicios con datos completos

Cada fila parte de una carga nueva, con hoy = 2026-11-03. Una venta aceptada queda como `V032`, con fecha de hoy
y el stock descontado; un rechazo no cambia ninguna venta, receta, contador ni lote.

| Caso | Llamada | Resultado esperado |
| --- | --- | --- |
| Cliente sin compras, producto de proveedor inactivo | `q14 --cliente C009 --farmaceutico F008 --item PRD018:1 --medio-pago Efectivo` | acepta: V032 'Venta libre', total 2600; L025 60 → 59 |
| Cliente inactivo | `q14 --cliente C012 --farmaceutico F008 --item PRD016:1 --medio-pago Efectivo` | rechaza con `CLIENTE_INACTIVO` |
| Receta vencida | `q14 --cliente C014 --farmaceutico F010 --item PRD015:1 --medio-pago "Obra social" --receta RC010` | rechaza con `RECETA_NO_VIGENTE` |
| Simple vigente sin dispensar | `q14 --cliente C016 --farmaceutico F008 --item PRD015:1 --medio-pago "Obra social" --receta RC014` | acepta: total 4300; RC014 1/1 'Completada', sin próxima dispensa; L024 120 → 119 |
| Tratamiento prolongado con próxima dispensa futura | `q14 --cliente C017 --farmaceutico F009 --item PRD020:1 --medio-pago "Obra social" --receta RC013` | acepta: total 5100; RC013 2/3 'Vigente', próxima dispensa hoy + 30 días (2026-12-03 con la fecha de referencia); L028 70 → 69 |
| Tratamiento prolongado con próxima dispensa pasada | `q14 --cliente C014 --farmaceutico F010 --item PRD015:1 --medio-pago "Obra social" --receta RC011` | acepta: total 4300; RC011 3/3 'Completada', sin próxima dispensa; L030 64 → 63 |
| Bajo receta archivada sin receta | `q14 --cliente C018 --farmaceutico F010 --item PRD014:1 --medio-pago Efectivo` | rechaza con `RECETA_REQUERIDA` |
| Bajo receta archivada con receta | `q14 --cliente C018 --farmaceutico F010 --item PRD014:1 --medio-pago "Obra social" --receta RC015` | acepta: total 6900; RC015 1/1 'Completada'; L029 30 → 29 |
| Receta de una venta pendiente | `q14 --cliente C019 --farmaceutico F012 --item PRD019:1 --medio-pago "Obra social" --receta RC016` | acepta: RC016 1/1 'Completada'; L035 25 → 24 |
| Producto inactivo | `q14 --cliente C015 --farmaceutico F008 --item PRD021:1 --medio-pago Efectivo` | rechaza con `PRODUCTO_INACTIVO` |
| Farmacia inactiva | `q14 --cliente C015 --farmaceutico F013 --item PRD016:1 --medio-pago Efectivo` | rechaza con `SUCURSAL_INACTIVA` |
| Farmacéutico inactivo | `q14 --cliente C015 --farmaceutico F014 --item PRD016:1 --medio-pago Efectivo` | rechaza con `FARMACEUTICO_INACTIVO` |
| Orden por vencimiento | `q14 --cliente C015 --farmaceutico F003 --item PRD002:50 --medio-pago Efectivo` | acepta: total 175000; consume L020 8, L021 40 y L022 2; L019 (vencido) queda en 25 |
| Stock vigente insuficiente | `q14 --cliente C015 --farmaceutico F003 --item PRD002:199 --medio-pago Efectivo` | rechaza con `STOCK_INSUFICIENTE` (se piden 199, hay 198 vigentes); los cuatro lotes quedan igual |
| Venta cargada como 'Completada' | `q15 V017` | rechaza con `STOCK_YA_DESCONTADO` |
| Venta 'Pendiente' | `q15 V024` | rechaza con `VENTA_NO_COMPLETADA` |
| Venta 'Anulada' | `q15 V026` | rechaza con `VENTA_NO_COMPLETADA` |
| Modificar un cliente inactivo | `q13 modificar C012 --email raul.d@gmail.com` | rechaza con `CLIENTE_INACTIVO` |
| Alta con el DNI de un cliente inactivo | `q13 alta --nombre Raúl --apellido Domínguez --dni 20456789 --email r.dominguez@gmail.com --telefono 1157456704 --ciudad "Buenos Aires" --provincia "Buenos Aires" --obra-social IOMA --nro-afiliado IO-338841` | rechaza con `DNI_DUPLICADO` |

Las ventas aceptadas por línea de comandos toman la fecha real del sistema en lugar de la de referencia; los
consumos son los mismos mientras L020 no venza (2026-11-27), y la próxima dispensa de una receta de tratamiento
prolongado queda a 30 días de la fecha real.
