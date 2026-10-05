from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
import json
from homeassistant.util import slugify
import logging
from .const import DOMAIN, CONF_NAME, CONF_MAC, MANUFACTURER, MODEL

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    devices = entry.data.get("devices", [entry.data])
    entities = []
    for device in devices:
        mac = device[CONF_MAC]
        name = device[CONF_NAME]
        entities.append(CO2Sensor(mac, name, entry.entry_id))
    async_add_entities(entities, True)

class CO2Sensor(SensorEntity):
    """New sensor specifically for CO2 PPM."""
    def __init__(self, mac, name, entry_id):
        self._mac = mac
        clean_mac = mac.replace(':', '').lower()
        self._attr_unique_id = f"{entry_id}_{clean_mac}_co2_ppm"
        self.entity_id = f"sensor.co2_{slugify(name)}"
        self._attr_native_unit_of_measurement = "ppm"
        self._attr_device_class = SensorDeviceClass.CO2
        self._attr_translation_key = "co2"
        self._attr_has_entity_name = True
        self._state = None
        # Привязка к устройству
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._mac)},
            "name": name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }

    @property
    def native_value(self):
        return self._state

    async def async_added_to_hass(self):
        async def _update_state(event):
            try:
                data = event.data.get("payload")
                state = data.get("state", {})
                if "state" in data and "co2_ppm" in data["state"]:
                    self._state = state.get("co2_ppm")
                    self.async_write_ha_state()
            except Exception as e:
                _LOGGER.error("Error CO2Sensor data: %s", e)
                pass
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_data_{self._mac}", _update_state)
        )
