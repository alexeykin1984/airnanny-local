import json
from homeassistant.components.number import NumberEntity
from homeassistant.helpers.entity import EntityCategory
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
        entities.append(BreezerSpeedNumber(mac, name, entry.entry_id))
        entities.append(BreezerHumidityNumber(mac, name, entry.entry_id))
    # Добавляем всё одним списком
    if entities:
        async_add_entities(entities)

class BreezerSpeedNumber(NumberEntity):
    def __init__(self, mac, name, entry_id):
        self._mac = mac
        clean_mac = mac.replace(':', '').lower()
        self._attr_unique_id = f"{entry_id}_{clean_mac}_fan_speed"
        self.entity_id = f"number.fan_speed_{slugify(name)}"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_has_entity_name = True

        # Настройки ползунка
        self._attr_native_min_value = 0
        self._attr_native_max_value = 6
        self._attr_native_step = 1
        self._attr_translation_key = "fan_speed"

        self._state = 0

        # Привязка к общему устройству
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._mac)},
            "name": name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }

    @property
    def native_value(self):
        return self._state

    async def async_set_native_value(self, value: float) -> None:
        """Установка значения через ползунок."""
        speed = int(value)
        self._state = speed
        cmd = f'{{"id": "{self._mac}", "cmd": {{"set_fan_speed": {speed}}}}}\n'

        self.hass.bus.async_fire(f"{DOMAIN}_send_cmd_{self._mac}", {"cmd": cmd})
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Обновление состояния ползунка из входящих данных."""
        async def _update_state(event):
            try:
                data = event.data.get("payload")
                state = data.get("state", {})

                if state:
                    self._state = state.get("fan_speed", 0)

                self.async_write_ha_state()
            except:
                pass
        self.hass.bus.async_listen(f"{DOMAIN}_data_{self._mac}", _update_state)

class BreezerHumidityNumber(NumberEntity):
    def __init__(self, mac, name, entry_id):
        self._mac = mac
        clean_mac = mac.replace(':', '').lower()
        self._attr_unique_id = f"{entry_id}_{clean_mac}_humidity"
        self.entity_id = f"number.humidity_{slugify(name)}"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_has_entity_name = True

        # Настройки ползунка
        self._attr_native_min_value = 0
        self._attr_native_max_value = 3
        self._attr_native_step = 1
        self._attr_translation_key = "humidity"

        self._state = 0

        # Привязка к общему устройству
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._mac)},
            "name": name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }

    @property
    def native_value(self):
        return self._state

    async def async_set_native_value(self, value: float) -> None:
        """Установка значения через ползунок."""
        humidity = int(value)
        self._state = humidity
        cmd = f'{{"id": "{self._mac}", "cmd": {{"set_hum_stg": {humidity}}}}}\n'

        self.hass.bus.async_fire(f"{DOMAIN}_send_cmd_{self._mac}", {"cmd": cmd})
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Обновление состояния ползунка из входящих данных."""
        async def _update_state(event):
            try:
                data = event.data.get("payload")
                setp = data.get("setp", {})

                if setp:
                    self._state = setp.get("u_hum_stg", 0)

                self.async_write_ha_state()
            except:
                pass
        self.hass.bus.async_listen(f"{DOMAIN}_data_{self._mac}", _update_state)
