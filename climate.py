import json
import logging
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import HVACMode, ClimateEntityFeature
from homeassistant.const import UnitOfTemperature
from homeassistant.util import slugify
from .const import DOMAIN, CONF_NAME, CONF_MAC, MANUFACTURER, MODEL

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    devices = entry.data.get("devices", [entry.data])
    entities = []
    for device in devices:
        mac = device[CONF_MAC]
        name = device[CONF_NAME]
        entities.append(BreezerClimate(mac, name, entry.entry_id))
    async_add_entities(entities, True)

class BreezerClimate(ClimateEntity):
    def __init__(self, mac, name, entry_id):
        self._mac = mac
        clean_mac = mac.replace(':', '').lower()
        self._attr_unique_id = f"{entry_id}_{clean_mac}_climate"
        self._attr_translation_key = "breezer"
        self.entity_id = f"climate.climate_{slugify(name)}"
        self._attr_has_entity_name = True
        # Привязка к тому же самому устройству
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._mac)},
            "name": name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }

        # Настройки климата
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.FAN_ONLY, HVACMode.AUTO]
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

        # Укажите шаг и диапазон (пример: от 5 до 30 градусов)
        self._attr_target_temperature_step = 1
        self._attr_min_temp = 5
        self._attr_max_temp = 30

        # # Текущие состояния
        self._hvac_mode = HVACMode.OFF
        self._current_temp = None
        self._current_hum = None
        self._target_temp = None

    @property
    def hvac_mode(self): return self._hvac_mode
    @property
    def current_temperature(self): return self._current_temp
    @property
    def current_humidity(self): return self._current_hum
    @property
    def target_temperature(self): return self._target_temp

    async def async_added_to_hass(self):
        async def _update_state(event):
            try:
                data = event.data.get("payload")
                state = data.get("state", {})
                setp = data.get("setp", {})

                if setp:
                    _LOGGER.debug("Received setp = %s", setp)
                    is_auto = setp.get("u_auto")
                    is_off = not setp.get("u_pwr_on")
                    if "u_temp_room" in setp:
                        self._target_temp = setp["u_temp_room"] / 10
                    if is_off:
                        self._hvac_mode = HVACMode.OFF
                    elif is_auto:
                        self._hvac_mode = HVACMode.AUTO
                    else:
                        self._hvac_mode = HVACMode.FAN_ONLY
                elif state:
                    _LOGGER.debug("Received state = %s", state)
                    if "temp_in" in state:
                        self._current_temp = state["temp_in"] / 10
                    if "hum_room" in state:
                        self._current_hum = state["hum_room"]
                else:
                    return

                self.async_write_ha_state()
            except Exception as e:
                _LOGGER.error("Ошибка парсинга климата: %s", e)

        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_data_{self._mac}", _update_state)
        )

    async def async_set_hvac_mode(self, hvac_mode):
        is_auto = "true" if hvac_mode == HVACMode.AUTO else "false"
        cmd_auto = f'{{"id": "{self._mac}", "cmd": {{"set_auto": {is_auto}}}}}\n'

        pwr = "false" if hvac_mode == HVACMode.OFF else "true"
        cmd_pwr = f'{{"id": "{self._mac}", "cmd": {{"set_pwr_on": {pwr}}}}}\n'

        self.hass.bus.async_fire(f"{DOMAIN}_send_cmd_{self._mac}", {"cmd": cmd_auto})
        self.hass.bus.async_fire(f"{DOMAIN}_send_cmd_{self._mac}", {"cmd": cmd_pwr})

    async def async_set_temperature(self, **kwargs):
        if (temp := kwargs.get("temperature")) is None:
            return
        cmd = f'{{"id": "{self._mac}", "cmd": {{"set_temp_room": {round(temp * 10)}}}}}\n'
        self.hass.bus.async_fire(f"{DOMAIN}_send_cmd_{self._mac}", {"cmd": cmd})