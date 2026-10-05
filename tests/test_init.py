"""Настройка и выгрузка записи."""
import asyncio

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .common import DOMAIN, MAC, PORT, Breezer, state_of

# entity_id -> суффикс unique_id; менять нельзя, иначе у пользователей потеряется история
ENTITIES = {
    "climate.climate_sasha": "climate",
    "sensor.co2_sasha": "co2_ppm",
    "number.humidity_sasha": "humidity",
    "switch.night_mode_sasha": "night_mode",
    "switch.damper_sasha": "damper",
    "binary_sensor.no_water_sasha": "no_water",
}


async def test_entities_created(hass, entry):
    registry = er.async_get(hass)
    for entity_id, suffix in ENTITIES.items():
        # До подключения бризера всё недоступно
        assert state_of(hass, entity_id) == "unavailable", entity_id
        assert registry.async_get(entity_id).unique_id == f"entry1_1c9dc2ec2ebc0_{suffix}"
    assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == len(ENTITIES)


async def test_old_fan_speed_number_removed(hass):
    """Ползунок скорости переехал в climate — старая сущность убирается из реестра."""
    entry = MockConfigEntry(
        domain=DOMAIN, entry_id="entry1", data={"devices": [{"name": "Саша", "mac": MAC}]}
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "number", DOMAIN, "entry1_1c9dc2ec2ebc0_fan_speed",
        config_entry=entry, suggested_object_id="fan_speed_sasha",
    )
    assert registry.async_get("number.fan_speed_sasha")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get("number.fan_speed_sasha") is None
    assert registry.async_get("number.humidity_sasha")
    await hass.config_entries.async_unload(entry.entry_id)


async def test_unload_with_live_connection(hass, entry, breezer):
    """Выгрузка не зависает, даже если бризер подключён."""
    assert await asyncio.wait_for(hass.config_entries.async_unload(entry.entry_id), 5)
    assert await breezer.closed()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_reload(hass, entry, breezer):
    assert await asyncio.wait_for(hass.config_entries.async_reload(entry.entry_id), 5)
    assert entry.state is ConfigEntryState.LOADED
    assert await breezer.closed()
    # Сервер снова принимает подключения
    again = await Breezer().connect()
    assert (await again.line())["hello"] is True
    again.close()


async def test_port_busy(hass):
    """Занятый порт: запись уходит на повтор, а не грузится без сервера."""
    blocker = await asyncio.start_server(lambda r, w: None, "0.0.0.0", PORT)
    entry = MockConfigEntry(domain=DOMAIN, data={"devices": [{"name": "Саша", "mac": MAC}]})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    blocker.close()
    await blocker.wait_closed()
    await hass.config_entries.async_unload(entry.entry_id)
