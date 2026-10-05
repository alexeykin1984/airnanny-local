from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from .entity import AirNannyEntity

async def async_setup_entry(hass, entry, async_add_entities):
    hub = entry.runtime_data
    async_add_entities(
        CO2Sensor(hub, mac, name, entry.entry_id) for mac, name in hub.devices.items()
    )

class CO2Sensor(AirNannyEntity, SensorEntity):
    """New sensor specifically for CO2 PPM."""
    _attr_translation_key = "co2"
    _unique_id_suffix = "co2_ppm"
    _entity_id_format = "sensor.co2_{}"
    _attr_device_class = SensorDeviceClass.CO2
    _attr_native_unit_of_measurement = "ppm"

    def _update(self, state, setp):
        if "co2_ppm" not in state:
            return False
        self._attr_native_value = state["co2_ppm"]
        return True
