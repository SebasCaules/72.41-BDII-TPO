-- KEYS[i]: stock:{suc}:{prd}; ARGV[1]: hoy AAAAMMDD; ARGV[i+1]: unidades pedidas para KEYS[i]
local hoy = tonumber(ARGV[1])
local plan = {}
for i, clave in ipairs(KEYS) do
  local pedido = tonumber(ARGV[i + 1])
  local resto = pedido
  local lotes = redis.call('ZRANGE', clave, hoy, '+inf', 'BYSCORE')
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
local respuesta = {'OK'}
for _, paso in ipairs(plan) do
  redis.call('HINCRBY', 'lote:' .. paso[1], 'unidades', -paso[2])
  redis.call('ZINCRBY', 'lotes:unidades', -paso[2], paso[1])
  table.insert(respuesta, paso[1])
  table.insert(respuesta, tostring(paso[2]))
end
return respuesta
