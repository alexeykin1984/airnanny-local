import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .common import DOMAIN, MAC, PORT, Breezer, state_of, until


@pytest.fixture(autouse=True)
def _environment(enable_custom_integrations, socket_enabled, monkeypatch):
    monkeypatch.setattr("custom_components.airnanny_local.hub.PORT", PORT)
    monkeypatch.setattr("custom_components.airnanny_local.hub.POLL_INTERVAL", 0.2)


@pytest.fixture
async def entry(hass):
    """Настроенная запись с одним бризером «Саша»."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="AirNanny",
        entry_id="entry1",
        # Старый формат: у устройства ещё сохранён порт
        data={"devices": [{"name": "Саша", "mac": MAC, "port": 3001}]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    yield entry
    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)


@pytest.fixture
async def breezer(hass, entry):
    """Подключённый бризер."""
    breezer = await Breezer().connect()
    await until(hass, lambda: state_of(hass, "sensor.co2_sasha") != "unavailable", "подключение")
    yield breezer
    breezer.close()
