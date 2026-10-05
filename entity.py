"""Базовый класс для всех сущностей бризера."""
import logging
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.util import slugify
from .const import DOMAIN, MANUFACTURER, MODEL
from .hub import AirNannyHub, signal_available, signal_data

_LOGGER = logging.getLogger(__name__)

class AirNannyEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    # Наследники задают шаблон entity_id и, если он отличается от translation_key, суффикс unique_id
    _entity_id_format: str
    _unique_id_suffix: str | None = None

    def __init__(self, hub: AirNannyHub, mac: str, name: str, entry_id: str) -> None:
        self._hub = hub
        self._mac = mac
        clean_mac = mac.replace(':', '').lower()
        suffix = self._unique_id_suffix or self._attr_translation_key
        self._attr_unique_id = f"{entry_id}_{clean_mac}_{suffix}"
        self.entity_id = self._entity_id_format.format(slugify(name))
        # Привязка к общему устройству
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            name=name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def available(self) -> bool:
        return self._hub.is_connected(self._mac)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_data(self._mac), self._handle_payload)
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_available(self._mac), self.async_write_ha_state)
        )

    @callback
    def _handle_payload(self, payload: dict) -> None:
        state = payload.get("state")
        setp = payload.get("setp")
        try:
            changed = self._update(
                state if isinstance(state, dict) else {},
                setp if isinstance(setp, dict) else {},
            )
        except (TypeError, ValueError) as e:
            _LOGGER.error("Ошибка разбора данных для %s: %s", self.entity_id, e)
            return
        if changed:
            self.async_write_ha_state()

    def _update(self, state: dict, setp: dict) -> bool:
        """Обновляет атрибуты из пакета. Возвращает True, если в пакете были данные для сущности."""
        raise NotImplementedError

    def _send(self, **cmd) -> None:
        self._hub.async_send(self._mac, cmd)
