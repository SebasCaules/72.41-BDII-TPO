-- KEYS[1]: descuento:{id_venta}. Repone lo que dice el registro y lo borra, en un solo paso; devuelve 1.
-- Devuelve 0 sin tocar nada si no hay registro, o si sus consumos los recibió más de una llamada (usos > 1):
-- cualquiera de ellas puede marcar la venta todavía, y la marca quedaría sin su descuento.
local guardado = redis.call('HGET', KEYS[1], 'consumos')
if not guardado or redis.call('HGET', KEYS[1], 'usos') ~= '1' then
  return 0
end
for _, paso in ipairs(cjson.decode(guardado)) do
  redis.call('HINCRBY', 'lote:' .. paso[1], 'unidades', paso[2])
  redis.call('ZINCRBY', 'lotes:unidades', paso[2], paso[1])
end
redis.call('DEL', KEYS[1])
return 1
