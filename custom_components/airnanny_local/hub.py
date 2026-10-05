"""TCP-сервер, к которому подключаются бризеры."""
import asyncio
import json
import logging
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .const import DOMAIN, PORT, POLL_INTERVAL

_LOGGER = logging.getLogger(__name__)

_DECODER = json.JSONDecoder()
# Если в буфере накопилось больше — считаем его мусором и сбрасываем
MAX_BUFFER_SIZE = 8192

def signal_data(mac: str) -> str:
    """Сигнал диспетчера: от устройства пришёл пакет."""
    return f"{DOMAIN}_data_{mac}"

def signal_available(mac: str) -> str:
    """Сигнал диспетчера: устройство подключилось или отключилось."""
    return f"{DOMAIN}_available_{mac}"

def _extract_messages(buffer: str):
    """Достаёт из буфера все целые JSON-сообщения. Возвращает (сообщения, остаток)."""
    messages = []
    while True:
        buffer = buffer.lstrip()
        if not buffer:
            break
        try:
            message, end = _DECODER.raw_decode(buffer)
        except json.JSONDecodeError:
            # Либо сообщение пришло не целиком (ждём продолжения), либо это мусор
            if len(buffer) > MAX_BUFFER_SIZE:
                _LOGGER.debug("Пропущен невалидный пакет: %s", buffer)
                buffer = ""
            break
        messages.append(message)
        buffer = buffer[end:]
    return messages, buffer

async def _read_messages(reader: asyncio.StreamReader):
    """Выдаёт JSON-сообщения из сокета, пока устройство не отключится."""
    buffer = ""
    while chunk := await reader.read(1024):
        buffer += chunk.decode("utf-8", errors="ignore")
        messages, buffer = _extract_messages(buffer)
        for message in messages:
            if isinstance(message, dict):
                yield message
            else:
                _LOGGER.debug("Пропущен невалидный пакет: %s", message)

def _write(writer: asyncio.StreamWriter, message: dict) -> None:
    writer.write((json.dumps(message) + "\n").encode("utf-8"))

class AirNannyHub:
    """Один сервер на все устройства записи."""

    def __init__(self, hass: HomeAssistant, devices: dict[str, str]) -> None:
        self.hass = hass
        self.devices = devices  # MAC -> имя
        self._server: asyncio.Server | None = None
        # Все открытые сокеты, включая ещё не представившиеся
        self._writers: set[asyncio.StreamWriter] = set()
        # Сокеты опознанных устройств: MAC -> writer
        self._connections: dict[str, asyncio.StreamWriter] = {}
        self._notified_macs: set[str] = set()

    async def async_start(self) -> None:
        _LOGGER.info("Попытка запуска сервера на порту %s", PORT)
        self._server = await asyncio.start_server(self._handle_client, "0.0.0.0", PORT)

    async def async_stop(self, event=None) -> None:
        _LOGGER.info("Остановка сервера на порту %s", PORT)
        # Сначала закрываем сокеты клиентов, иначе wait_closed() будет их ждать
        for writer in list(self._writers):
            writer.close()
        if server := self._server:
            self._server = None
            server.close()
            await server.wait_closed()

    def is_connected(self, mac: str) -> bool:
        return mac in self._connections

    @callback
    def async_send(self, mac: str, cmd: dict) -> None:
        """Отправляет устройству команду, например {"set_night": True}."""
        writer = self._connections.get(mac)
        if writer is None or writer.transport.is_closing():
            raise HomeAssistantError(f"Бризер {self.devices.get(mac, mac)} не подключён")
        _write(writer, {"id": mac, "cmd": cmd})
        _LOGGER.debug("[%s] Отправлена команда: %s", mac, cmd)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        messages = _read_messages(reader)
        try:
            # Ждем первый пакет (Hello)
            hello = await anext(messages, None)
            if hello is None or "hello" not in hello:
                return

            mac = str(hello["id"])
            if mac not in self.devices:
                self._notify_unknown_device(mac)
                return

            await self._run_session(mac, hello, messages, writer)
        except (OSError, KeyError, TypeError) as e:
            _LOGGER.error("Error handling socket data: %s", e)
        finally:
            await messages.aclose()
            self._writers.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def _run_session(self, mac: str, hello: dict, messages, writer: asyncio.StreamWriter) -> None:
        """Обслуживает подключение опознанного устройства до его отключения."""
        name = self.devices[mac]
        _LOGGER.info("Device %s is connected", name)

        _write(writer, {
            "hello": True,
            "id": mac,
            "time": str(hello["hello"]["time"]),
            "time_zone": "-00:00",
        })
        await writer.drain()

        # Устройство переподключилось, не закрыв старый сокет — закрываем его сами
        if old_writer := self._connections.get(mac):
            old_writer.close()
        self._connections[mac] = writer
        async_dispatcher_send(self.hass, signal_available(mac))

        polling_task = self.hass.async_create_background_task(
            self._poll(mac, writer), f"{DOMAIN}_poll_{mac}"
        )
        try:
            async for payload in messages:
                _LOGGER.debug("Received data from %s: %s", name, payload)
                # Прокидываем данные в сущности
                async_dispatcher_send(self.hass, signal_data(mac), payload)
        finally:
            polling_task.cancel()
            if self._connections.get(mac) is writer:
                del self._connections[mac]
                async_dispatcher_send(self.hass, signal_available(mac))
            _LOGGER.info("Device %s is disconnected", name)

    async def _poll(self, mac: str, writer: asyncio.StreamWriter) -> None:
        """Один раз запрашивает уставки, затем периодически — состояние."""
        try:
            await asyncio.sleep(0.5)
            _write(writer, {"id": mac, "cmd": {"get_setp": True}})
            while not writer.transport.is_closing():
                _write(writer, {"id": mac, "cmd": {"get_state": True}})
                await writer.drain()
                await asyncio.sleep(POLL_INTERVAL)
        except OSError as e:
            _LOGGER.debug("Polling stopped for %s: %s", mac, e)
            # Закрываем сокет, чтобы завершился и цикл чтения
            writer.close()

    def _notify_unknown_device(self, mac: str) -> None:
        if mac in self._notified_macs:
            return
        self._notified_macs.add(mac)
        _LOGGER.info("Новое устройство %s добавлено в очередь уведомлений", mac)

        persistent_notification.async_create(
            self.hass,
            title="Обнаружен новый Бризер",
            message=(
                f"Устройство с MAC-адресом **{mac}** пытается подключиться.\n\n"
                f"Перейдите в настройки интеграций, чтобы добавить его."
            ),
            notification_id=f"discovery_{mac.replace(':', '')}"
        )
