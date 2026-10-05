import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from .const import PORT, CONF_NAME, CONF_MAC
from .hub import AirNannyHub

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [
    Platform.SENSOR,
    Platform.CLIMATE,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.BINARY_SENSOR,
]

type AirNannyConfigEntry = ConfigEntry[AirNannyHub]

async def async_setup_entry(hass: HomeAssistant, entry: AirNannyConfigEntry) -> bool:
    """Настройка экземпляра интеграции."""
    # Получаем список устройств (поддержка как старого формата, так и нового списка)
    devices = entry.data.get("devices", [entry.data])
    hub = AirNannyHub(hass, {device[CONF_MAC]: device[CONF_NAME] for device in devices})

    try:
        await hub.async_start()
    except OSError as e:
        raise ConfigEntryNotReady(f"Не удалось запустить сервер на порту {PORT}: {e}") from e

    entry.runtime_data = hub
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, hub.async_stop))

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await hub.async_stop()
        raise
    return True

async def async_unload_entry(hass: HomeAssistant, entry: AirNannyConfigEntry) -> bool:
    # Сначала выгружаем сущности, затем останавливаем сервер
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_stop()
    return unload_ok
