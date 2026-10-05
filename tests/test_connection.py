"""Протокол: рукопожатие, разбор потока, подключения и отключения."""
import asyncio

import pytest

from custom_components.airnanny_local.hub import MAX_BUFFER_SIZE, _extract_messages

from .common import MAC, OTHER_MAC, PORT, Breezer, state_of, until


@pytest.mark.parametrize(
    ("buffer", "messages", "rest"),
    [
        ('{"a":1}\n', [{"a": 1}], ""),
        ('{"a":1}{"b":2}', [{"a": 1}, {"b": 2}], ""),
        ('{"a":1}\n{"b":', [{"a": 1}], '{"b":'),
        ("", [], ""),
        ("x" * (MAX_BUFFER_SIZE + 1), [], ""),  # мусор сбрасывается
    ],
)
def test_extract_messages(buffer, messages, rest):
    assert _extract_messages(buffer) == (messages, rest)


async def test_handshake(hass, entry):
    """Hello может прийти кусками; в ответ — hello, запрос уставок и опрос состояния."""
    breezer = await Breezer().connect(split=True)
    assert await breezer.line() == {"hello": True, "id": MAC, "time": "123", "time_zone": "-00:00"}
    assert await breezer.line() == {"id": MAC, "cmd": {"get_setp": True}}
    assert await breezer.line() == {"id": MAC, "cmd": {"get_state": True}}
    # Опрос повторяется
    assert await breezer.line() == {"id": MAC, "cmd": {"get_state": True}}
    breezer.close()


async def test_glued_and_split_packets(hass, breezer):
    await breezer.send(b'{"state":{"co2_ppm":612}}{"setp":{"u_night":true}}\n{"state":{"no_')
    await asyncio.sleep(0.05)
    await breezer.send(b'water":true}}')
    await until(hass, lambda: state_of(hass, "binary_sensor.no_water_sasha") == "on", "нет воды")
    assert state_of(hass, "sensor.co2_sasha") == "612"
    assert state_of(hass, "switch.night_mode_sasha") == "on"


async def test_not_json_is_ignored(hass, breezer):
    await breezer.send(b'[1,2]\n"text"\n{"state":{"co2_ppm":500}}\n')
    await until(hass, lambda: state_of(hass, "sensor.co2_sasha") == "500", "co2")


async def test_disconnect_and_reconnect(hass, breezer):
    await breezer.send(b'{"state":{"co2_ppm":700}}\n')
    await until(hass, lambda: state_of(hass, "sensor.co2_sasha") == "700", "co2")

    breezer.close()
    await until(hass, lambda: state_of(hass, "sensor.co2_sasha") == "unavailable", "отключение")

    # После переподключения последнее значение возвращается
    again = await Breezer().connect()
    await until(hass, lambda: state_of(hass, "sensor.co2_sasha") == "700", "переподключение")
    again.close()


async def test_second_connection_replaces_first(hass, breezer):
    """Бризер переподключился, не закрыв старый сокет: старый закрываем, сущности остаются доступны."""
    second = await Breezer().connect()
    assert await breezer.closed()
    await second.expect({"get_state": True})
    await hass.async_block_till_done()
    assert state_of(hass, "sensor.co2_sasha") != "unavailable"

    await second.send(b'{"state":{"co2_ppm":555}}\n')
    await until(hass, lambda: state_of(hass, "sensor.co2_sasha") == "555", "данные со второго сокета")
    second.close()


async def test_unknown_device_notification(hass, entry):
    stranger = await Breezer().connect(mac=OTHER_MAC)
    assert await stranger.closed()
    await until(
        hass,
        lambda: state_of(hass, "sensor.co2_sasha") == "unavailable"
        and any(
            OTHER_MAC in notification["message"]
            for notification in hass.data.get("persistent_notification", {}).values()
        ),
        "уведомление о новом устройстве",
    )


async def test_first_packet_is_not_hello(hass, entry):
    stranger = Breezer()
    stranger.reader, stranger.writer = await asyncio.open_connection("127.0.0.1", PORT)
    await stranger.send(b'{"state":{"co2_ppm":1}}\n')
    assert await stranger.closed()
