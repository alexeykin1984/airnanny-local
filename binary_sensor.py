from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass
)
from homeassistant.const import EntityCategory
from .entity import AirNannyEntity

async def async_setup_entry(hass, entry, async_add_entities):
    hub = entry.runtime_data
    async_add_entities(
        NoWaterSensor(hub, mac, name, entry.entry_id) for mac, name in hub.devices.items()
    )

class NoWaterSensor(AirNannyEntity, BinarySensorEntity):
    """Сенсор отсутствия воды."""
    _attr_translation_key = "no_water"
    _entity_id_format = "binary_sensor.no_water_{}"
    # Размещаем в диагностике
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # Используем класс "problem": ON если проблема (нет воды), OFF если все ок
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def _update(self, state, setp):
        # В JSON 'no_water': True означает, что воды НЕТ
        if "no_water" not in state:
            return False
        self._attr_is_on = state["no_water"]
        return True
