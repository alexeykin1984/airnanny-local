"""Состояния сущностей и команды."""
import pytest

from .common import MAC, state_of, until

STATE = (
    b'{"state":{"co2_ppm":612,"temp_in":235,"hum_room":41,"fan_speed":3,"no_water":true}}\n'
)
SETP = (
    b'{"setp":{"u_pwr_on":true,"u_auto":false,"u_temp_room":220,'
    b'"u_night":true,"u_damp_pos":2,"u_hum_stg":2}}\n'
)


@pytest.fixture
async def loaded(hass, breezer):
    """Бризер, уже приславший состояние и уставки."""
    await breezer.send(STATE + SETP)
    await until(hass, lambda: state_of(hass, "number.humidity_sasha") == "2", "уставки")
    return breezer


async def test_states(hass, loaded):
    assert state_of(hass, "sensor.co2_sasha") == "612"
    assert state_of(hass, "binary_sensor.no_water_sasha") == "on"
    assert state_of(hass, "switch.night_mode_sasha") == "on"
    assert state_of(hass, "switch.damper_sasha") == "on"
    assert state_of(hass, "number.humidity_sasha") == "2"

    climate = hass.states.get("climate.climate_sasha")
    assert climate.state == "fan_only"
    assert climate.attributes["current_temperature"] == 23.5
    assert climate.attributes["current_humidity"] == 41
    assert climate.attributes["temperature"] == 22
    assert climate.attributes["fan_mode"] == "3"
    assert climate.attributes["fan_modes"] == ["0", "1", "2", "3", "4", "5", "6"]


@pytest.mark.parametrize(
    ("setp", "mode"),
    [
        (b'{"setp":{"u_pwr_on":false,"u_auto":true}}\n', "off"),
        (b'{"setp":{"u_pwr_on":true,"u_auto":true}}\n', "auto"),
        (b'{"setp":{"u_pwr_on":true,"u_auto":false}}\n', "fan_only"),
    ],
)
async def test_hvac_mode_from_setp(hass, breezer, setp, mode):
    await breezer.send(setp)
    await until(hass, lambda: state_of(hass, "climate.climate_sasha") == mode, mode)


async def test_partial_packets_do_not_reset_values(hass, loaded):
    """Пакет только с уставками не трогает показания состояния, и наоборот."""
    await loaded.send(b'{"setp":{"u_pwr_on":false,"u_auto":false,"u_damp_pos":1}}\n')
    await until(hass, lambda: state_of(hass, "climate.climate_sasha") == "off", "выключение")
    assert state_of(hass, "switch.damper_sasha") == "off"
    assert state_of(hass, "binary_sensor.no_water_sasha") == "on"
    climate = hass.states.get("climate.climate_sasha")
    assert climate.attributes["current_temperature"] == 23.5
    assert climate.attributes["temperature"] == 22
    assert climate.attributes["fan_mode"] == "3"

    await loaded.send(b'{"state":{"co2_ppm":700}}\n{"ack":1}\n')
    await until(hass, lambda: state_of(hass, "sensor.co2_sasha") == "700", "co2")
    assert state_of(hass, "binary_sensor.no_water_sasha") == "on"
    assert state_of(hass, "switch.night_mode_sasha") == "on"
    assert state_of(hass, "number.humidity_sasha") == "2"
    assert hass.states.get("climate.climate_sasha").attributes["fan_mode"] == "3"


async def test_switch_commands(hass, loaded):
    call = hass.services.async_call
    await call("switch", "turn_off", {"entity_id": "switch.night_mode_sasha"}, blocking=True)
    await loaded.expect({"set_night": False})
    assert state_of(hass, "switch.night_mode_sasha") == "off"

    await call("switch", "turn_on", {"entity_id": "switch.night_mode_sasha"}, blocking=True)
    await loaded.expect({"set_night": True})

    await call("switch", "turn_off", {"entity_id": "switch.damper_sasha"}, blocking=True)
    await loaded.expect({"set_damp_pos": False})
    await call("switch", "turn_on", {"entity_id": "switch.damper_sasha"}, blocking=True)
    await loaded.expect({"set_damp_pos": True})


async def test_humidity_command(hass, loaded):
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.humidity_sasha", "value": 1}, blocking=True
    )
    await loaded.expect({"set_hum_stg": 1})
    assert state_of(hass, "number.humidity_sasha") == "1"


async def test_climate_commands(hass, loaded):
    call = hass.services.async_call
    target = {"entity_id": "climate.climate_sasha"}

    await call("climate", "set_hvac_mode", {**target, "hvac_mode": "auto"}, blocking=True)
    await loaded.expect({"set_auto": True})
    await loaded.expect({"set_pwr_on": True})

    await call("climate", "set_hvac_mode", {**target, "hvac_mode": "fan_only"}, blocking=True)
    await loaded.expect({"set_auto": False})
    await loaded.expect({"set_pwr_on": True})

    await call("climate", "set_hvac_mode", {**target, "hvac_mode": "off"}, blocking=True)
    await loaded.expect({"set_auto": False})
    await loaded.expect({"set_pwr_on": False})

    # Температура уходит в десятых долях градуса целым числом, формат команды — байт в байт
    await call("climate", "set_temperature", {**target, "temperature": 24}, blocking=True)
    raw = await loaded.expect({"set_temp_room": 240})
    assert raw == b'{"id": "%s", "cmd": {"set_temp_room": 240}}\n' % MAC.encode()


async def test_fan_mode_command(hass, loaded):
    await hass.services.async_call(
        "climate", "set_fan_mode",
        {"entity_id": "climate.climate_sasha", "fan_mode": "5"}, blocking=True,
    )
    await loaded.expect({"set_fan_speed": 5})
    assert hass.states.get("climate.climate_sasha").attributes["fan_mode"] == "5"

    # Устройство подтверждает другую скорость — показываем её
    await loaded.send(b'{"state":{"fan_speed":4}}\n')
    await until(
        hass,
        lambda: hass.states.get("climate.climate_sasha").attributes["fan_mode"] == "4",
        "скорость из состояния",
    )
