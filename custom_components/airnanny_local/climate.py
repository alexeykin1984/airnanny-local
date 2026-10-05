from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from .entity import AirNannyEntity

async def async_setup_entry(hass, entry, async_add_entities):
    hub = entry.runtime_data
    async_add_entities(
        BreezerClimate(hub, mac, name, entry.entry_id) for mac, name in hub.devices.items()
    )

class BreezerClimate(AirNannyEntity, ClimateEntity):
    _attr_translation_key = "breezer"
    _unique_id_suffix = "climate"
    _entity_id_format = "climate.climate_{}"

    # Настройки климата
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.FAN_ONLY, HVACMode.AUTO]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE
    )
    # Скорости вентилятора: 0-6
    _attr_fan_modes = [str(speed) for speed in range(7)]
    _attr_fan_mode = None
    # Режим неизвестен, пока устройство не пришлёт уставки
    _attr_hvac_mode = None

    # Шаг и диапазон целевой температуры
    _attr_target_temperature_step = 1
    _attr_min_temp = 5
    _attr_max_temp = 30

    def _update(self, state, setp):
        changed = False

        if "u_temp_room" in setp:
            self._attr_target_temperature = setp["u_temp_room"] / 10
            changed = True
        if "u_pwr_on" in setp or "u_auto" in setp:
            if not setp.get("u_pwr_on"):
                self._attr_hvac_mode = HVACMode.OFF
            elif setp.get("u_auto"):
                self._attr_hvac_mode = HVACMode.AUTO
            else:
                self._attr_hvac_mode = HVACMode.FAN_ONLY
            changed = True

        if "temp_in" in state:
            self._attr_current_temperature = state["temp_in"] / 10
            changed = True
        if "hum_room" in state:
            self._attr_current_humidity = state["hum_room"]
            changed = True
        if "fan_speed" in state:
            self._attr_fan_mode = str(state["fan_speed"])
            changed = True

        return changed

    async def async_set_hvac_mode(self, hvac_mode):
        self._send(set_auto=hvac_mode == HVACMode.AUTO)
        self._send(set_pwr_on=hvac_mode != HVACMode.OFF)

    async def async_set_fan_mode(self, fan_mode):
        self._send(set_fan_speed=int(fan_mode))
        self._attr_fan_mode = fan_mode
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs):
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        self._send(set_temp_room=round(temp * 10))
