from homeassistant.components.number import NumberEntity
from homeassistant.const import EntityCategory
from .entity import AirNannyEntity

async def async_setup_entry(hass, entry, async_add_entities):
    hub = entry.runtime_data
    async_add_entities(
        BreezerHumidityNumber(hub, mac, name, entry.entry_id) for mac, name in hub.devices.items()
    )

class BreezerHumidityNumber(AirNannyEntity, NumberEntity):
    """Ступень увлажнения."""
    _attr_translation_key = "humidity"
    _entity_id_format = "number.humidity_{}"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 3
    _attr_native_step = 1
    _attr_native_value = None

    def _update(self, state, setp):
        if "u_hum_stg" not in setp:
            return False
        self._attr_native_value = setp["u_hum_stg"]
        return True

    async def async_set_native_value(self, value: float) -> None:
        """Установка значения через ползунок."""
        self._send(set_hum_stg=int(value))
        self._attr_native_value = int(value)
        self.async_write_ha_state()
