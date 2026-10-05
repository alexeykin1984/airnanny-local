from homeassistant.components.number import NumberEntity
from homeassistant.const import EntityCategory
from .entity import AirNannyEntity

async def async_setup_entry(hass, entry, async_add_entities):
    hub = entry.runtime_data
    entities = []
    for mac, name in hub.devices.items():
        entities.append(BreezerSpeedNumber(hub, mac, name, entry.entry_id))
        entities.append(BreezerHumidityNumber(hub, mac, name, entry.entry_id))
    async_add_entities(entities)

class BreezerNumber(AirNannyEntity, NumberEntity):
    """Общая логика ползунков: наследники задают диапазон, команду и разбор пакета."""
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_step = 1
    _attr_native_value = None
    _command: str

    async def async_set_native_value(self, value: float) -> None:
        """Установка значения через ползунок."""
        self._send(**{self._command: int(value)})
        self._attr_native_value = int(value)
        self.async_write_ha_state()

class BreezerSpeedNumber(BreezerNumber):
    """Скорость вентилятора."""
    _attr_translation_key = "fan_speed"
    _entity_id_format = "number.fan_speed_{}"
    _attr_native_max_value = 6
    _command = "set_fan_speed"

    def _update(self, state, setp):
        if "fan_speed" not in state:
            return False
        self._attr_native_value = state["fan_speed"]
        return True

class BreezerHumidityNumber(BreezerNumber):
    """Ступень увлажнения."""
    _attr_translation_key = "humidity"
    _entity_id_format = "number.humidity_{}"
    _attr_native_max_value = 3
    _command = "set_hum_stg"

    def _update(self, state, setp):
        if "u_hum_stg" not in setp:
            return False
        self._attr_native_value = setp["u_hum_stg"]
        return True
