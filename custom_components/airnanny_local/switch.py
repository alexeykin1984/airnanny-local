from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from .entity import AirNannyEntity

async def async_setup_entry(hass, entry, async_add_entities):
    hub = entry.runtime_data
    entities = []
    for mac, name in hub.devices.items():
        entities.append(BreezerNightSwitch(hub, mac, name, entry.entry_id))
        entities.append(DamperSwitch(hub, mac, name, entry.entry_id))
    async_add_entities(entities)

class BreezerSwitch(AirNannyEntity, SwitchEntity):
    """Общая логика выключателей: наследники задают команду и разбор уставки."""
    _attr_entity_category = EntityCategory.CONFIG
    _command: str

    async def async_turn_on(self, **kwargs):
        self._set(True)

    async def async_turn_off(self, **kwargs):
        self._set(False)

    def _set(self, is_on: bool) -> None:
        self._send(**{self._command: is_on})
        self._attr_is_on = is_on
        self.async_write_ha_state()

class BreezerNightSwitch(BreezerSwitch):
    """Ночной режим."""
    _attr_translation_key = "night_mode"
    _entity_id_format = "switch.night_mode_{}"
    _command = "set_night"

    def _update(self, state, setp):
        if "u_night" not in setp:
            return False
        self._attr_is_on = setp["u_night"]
        return True

class DamperSwitch(BreezerSwitch):
    """Заслонка."""
    _attr_translation_key = "damper"
    _entity_id_format = "switch.damper_{}"
    _command = "set_damp_pos"

    def _update(self, state, setp):
        if "u_damp_pos" not in setp:
            return False
        self._attr_is_on = setp["u_damp_pos"] == 2
        return True
