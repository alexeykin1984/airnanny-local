import json
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import slugify
from .const import DOMAIN, CONF_NAME, CONF_MAC, MANUFACTURER, MODEL

async def async_setup_entry(hass, entry, async_add_entities):
    devices = entry.data.get("devices", [entry.data])
    entities = []
    for device in devices:
        mac = device[CONF_MAC]
        name = device[CONF_NAME]
        entities.append(BreezerNightSwitch(mac, name, entry.entry_id))
        entities.append(DamperSwitch(mac, name, entry.entry_id))
    # Добавляем всё одним списком
    if entities:
        async_add_entities(entities)

class BreezerNightSwitch(SwitchEntity):
    def __init__(self, mac, name, entry_id):
        self._mac = mac
        clean_mac = mac.replace(':', '').lower()
        self._attr_unique_id = f"{entry_id}_{clean_mac}_night_mode"
        self.entity_id = f"switch.night_mode_{slugify(name)}"
        self._attr_translation_key = "night_mode"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_has_entity_name = True
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

    async def async_turn_on(self, **kwargs):
        """Включение ночного режима."""
        cmd = f'{{"id": "{self._mac}", "cmd": {{"set_night": true}}}}\n'
        self.hass.bus.async_fire(f"{DOMAIN}_send_cmd_{self._mac}", {"cmd": cmd})
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Выключение ночного режима."""
        cmd = f'{{"id": "{self._mac}", "cmd": {{"set_night": false}}}}\n'
        self.hass.bus.async_fire(f"{DOMAIN}_send_cmd_{self._mac}", {"cmd": cmd})
        self._is_on = False
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Обновление состояния из JSON."""
        async def _update_state(event):
            try:
                data = event.data.get("payload")
                setp = data.get("setp", {})
                if setp:
                    self._is_on = setp.get("u_night")
                    self.async_write_ha_state()
            except:
                pass
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_data_{self._mac}", _update_state)
        )

class DamperSwitch(SwitchEntity):
    def __init__(self, mac, name, entry_id):
        self._mac = mac
        clean_mac = mac.replace(':', '').lower()
        self._attr_unique_id = f"{entry_id}_{clean_mac}_damper"
        self.entity_id = f"switch.damper_{slugify(name)}"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_has_entity_name = True
        self._attr_translation_key = "damper"
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

    async def async_turn_on(self, **kwargs):
        """Открыть заслонку"""
        cmd = f'{{"id": "{self._mac}", "cmd": {{"set_damp_pos": true}}}}\n'
        self.hass.bus.async_fire(f"{DOMAIN}_send_cmd_{self._mac}", {"cmd": cmd})
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Закрыть заслонку"""
        cmd = f'{{"id": "{self._mac}", "cmd": {{"set_damp_pos": false}}}}\n'
        self.hass.bus.async_fire(f"{DOMAIN}_send_cmd_{self._mac}", {"cmd": cmd})
        self._is_on = False
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Обновление состояния из JSON."""
        async def _update_state(event):
            try:
                data = event.data.get("payload")
                setp = data.get("setp", {})
                if setp:
                    self._is_on = True if setp.get("u_damp_pos") == 2 else False
                    self.async_write_ha_state()
            except:
                pass
        self.async_on_remove(
            self.hass.bus.async_listen(f"{DOMAIN}_data_{self._mac}", _update_state)
        )
