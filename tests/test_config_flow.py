"""Первичная настройка и управление списком устройств."""
import asyncio

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .common import DOMAIN, MAC, OTHER_MAC, Breezer, state_of, until


async def _open_options_step(hass, entry, step):
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] == "menu"
    return await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": step}
    )


async def _add_device(hass, entry, name, mac):
    flow = await _open_options_step(hass, entry, "add_device")
    assert set(flow["data_schema"].schema) == {"name", "mac"}
    flow = await asyncio.wait_for(
        hass.config_entries.options.async_configure(flow["flow_id"], {"name": name, "mac": mac}), 5
    )
    await hass.async_block_till_done()
    return flow


async def test_user_flow(hass):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert flow["type"] == "form"
    assert set(flow["data_schema"].schema) == {"name", "mac"}

    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"name": "Саша", "mac": MAC}
    )
    assert flow["type"] == "create_entry"
    assert flow["data"] == {"devices": [{"name": "Саша", "mac": MAC}]}
    await hass.async_block_till_done()

    # Вторая запись запрещена: остальные устройства добавляются через настройки
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert flow["type"] == "abort"
    assert flow["reason"] == "single_instance_allowed"

    for entry in hass.config_entries.async_entries(DOMAIN):
        await hass.config_entries.async_unload(entry.entry_id)


async def test_add_device(hass, entry, breezer):
    flow = await _add_device(hass, entry, "Катя", OTHER_MAC)
    assert flow["type"] == "create_entry"
    assert entry.state is ConfigEntryState.LOADED
    assert [device["mac"] for device in entry.data["devices"]] == [MAC, OTHER_MAC]
    # Перезагрузка рвёт соединение, бризер переподключится сам
    assert await breezer.closed()

    assert state_of(hass, "sensor.co2_katia") == "unavailable"
    second = await Breezer().connect(mac=OTHER_MAC)
    await second.expect({"get_state": True})
    await second.send(b'{"state":{"co2_ppm":444}}\n')
    await until(hass, lambda: state_of(hass, "sensor.co2_katia") == "444", "второе устройство")
    # Данные второго устройства не попадают первому
    assert state_of(hass, "sensor.co2_sasha") == "unavailable"
    second.close()


async def test_add_duplicate_device(hass, entry):
    flow = await _open_options_step(hass, entry, "add_device")
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"name": "Дубль", "mac": MAC}
    )
    assert flow["type"] == "form"
    assert flow["errors"] == {"base": "already_configured"}
    hass.config_entries.options.async_abort(flow["flow_id"])
    assert len(entry.data["devices"]) == 1


async def test_remove_device(hass, entry):
    await _add_device(hass, entry, "Катя", OTHER_MAC)
    second = await Breezer().connect(mac=OTHER_MAC)
    await second.expect({"get_state": True})

    flow = await _open_options_step(hass, entry, "remove_device")
    flow = await asyncio.wait_for(
        hass.config_entries.options.async_configure(flow["flow_id"], {"mac_to_remove": OTHER_MAC}), 5
    )
    assert flow["type"] == "create_entry"
    await hass.async_block_till_done()

    assert [device["mac"] for device in entry.data["devices"]] == [MAC]
    assert await second.closed()
    # Сущности и устройство убраны из реестров, первое устройство не задето
    assert hass.states.get("sensor.co2_katia") is None
    assert er.async_get(hass).async_get("sensor.co2_katia") is None
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert [device.identifiers for device in devices] == [{(DOMAIN, MAC)}]
    assert state_of(hass, "sensor.co2_sasha") == "unavailable"
