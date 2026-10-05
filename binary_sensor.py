import json
import logging
from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass
)
from homeassistant.util import slugify
from homeassistant.helpers.entity import EntityCategory
from .const import DOMAIN, CONF_NAME, CONF_MAC, MANUFACTURER, MODEL

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    devices = entry.data.get("devices", [entry.data])
    entities = []
    for device in devices:
        mac = device[CONF_MAC]
        name = device[CONF_NAME]
        entities.append(NoWaterSensor(mac, name, entry.entry_id))
    async_add_entities(entities, True)

class NoWaterSensor(BinarySensorEntity):
    """Сенсор отсутствия воды."""
    def __init__(self, mac, name, entry_id):
        self._mac = mac
        clean_mac = mac.replace(':', '').lower()
        self._attr_unique_id = f"{entry_id}_{clean_mac}_no_water"
        self._attr_translation_key = "no_water"
        self.entity_id = f"binary_sensor.no_water_{slugify(name)}"
        self._attr_has_entity_name = True

        # Размещаем в диагностике
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        # Используем класс "problem": ON если проблема (нет воды), OFF если все ок
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

        self._is_on = False
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._mac)},
            "name": name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }

    @property
    def is_on(self):
        return self._is_on

    async def async_added_to_hass(self):
        """Обновление состояния из JSON."""
        async def _update_state(event):
            try:
                data = event.data.get("payload")
                state = data.get("state", {})
                # В JSON 'no_water': True означает, что воды НЕТ
                self._is_on = state.get("no_water", False)
                self.async_write_ha_state()
            except Exception as e:
                _LOGGER.error("Error No Water data: %s", e)
                pass
        self.hass.bus.async_listen(f"{DOMAIN}_data_{self._mac}", _update_state)
