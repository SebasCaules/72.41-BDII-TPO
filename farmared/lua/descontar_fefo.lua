-- KEYS[1..n]: stock:{suc}:{prd}, sin repetir; KEYS[n+1], opcional: descuento:{id_venta}, el registro de la venta
-- ARGV[1]: hoy AAAAMMDD; ARGV[i+1]: unidades pedidas para KEYS[i], entero entre 1 y 2^31 - 1
-- Con registro: si ya existe, no descuenta y devuelve los consumos guardados; si no, lo crea junto con el descuento
-- se valida todo antes de escribir: un argumento malo no puede dejar un descuento a medias
local n = #ARGV - 1
local registro = KEYS[n + 1]
if n < 0 or #KEYS < n or #KEYS > n + 1 or (registro and string.sub(registro, 1, 10) ~= 'descuento:')
    or not string.match(ARGV[1], '^%d%d%d%d%d%d%d%d$') then
  return redis.error_reply('ARGUMENTOS_INVALIDOS se esperan la fecha AAAAMMDD y una cantidad por clave de stock')
end
local vistas = {}
for i = 1, n do
  if not string.match(ARGV[i + 1], '^[1-9]%d*$') or tonumber(ARGV[i + 1]) >= 2^31 or vistas[KEYS[i]] then
    return redis.error_reply('ARGUMENTOS_INVALIDOS cantidad inválida o clave repetida en la posición ' .. i)
  end
  vistas[KEYS[i]] = true
end
local respuesta = {'OK'}
if registro then
  local guardado = redis.call('HGET', registro, 'consumos')
  if guardado then
    -- usos cuenta las llamadas que recibieron estos consumos: con más de una, ya no se pueden reponer
    redis.call('HINCRBY', registro, 'usos', 1)
    for _, paso in ipairs(cjson.decode(guardado)) do
      table.insert(respuesta, paso[1])
      table.insert(respuesta, tostring(paso[2]))
    end
    return respuesta
  end
end
local hoy = tonumber(ARGV[1])
local plan = {}
for i = 1, n do
  local pedido = tonumber(ARGV[i + 1])
  local resto = pedido
  local lotes = redis.call('ZRANGE', KEYS[i], hoy, '+inf', 'BYSCORE')
  for _, id in ipairs(lotes) do
    if resto == 0 then break end
    local unidades = tonumber(redis.call('HGET', 'lote:' .. id, 'unidades') or '0')
    if unidades > 0 then
      local toma = math.min(unidades, resto)
      table.insert(plan, {id, toma})
      resto = resto - toma
    end
  end
  if resto > 0 then
    return {'FALTA', tostring(i), tostring(pedido - resto)}
  end
end
for _, paso in ipairs(plan) do
  redis.call('HINCRBY', 'lote:' .. paso[1], 'unidades', -paso[2])
  redis.call('ZINCRBY', 'lotes:unidades', -paso[2], paso[1])
  table.insert(respuesta, paso[1])
  table.insert(respuesta, tostring(paso[2]))
end
if registro then
  redis.call('HSET', registro, 'consumos', cjson.encode(plan), 'usos', 1)
end
return respuesta
