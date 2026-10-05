import asyncio
from functools import partial
import json
import logging
from homeassistant.core import HomeAssistant
from homeassistant.components import persistent_notification
from homeassistant.exceptions import ConfigEntryNotReady
from .const import DOMAIN, PORT, CONF_NAME, CONF_MAC

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "climate", "switch", "number", "binary_sensor"]

_DECODER = json.JSONDecoder()
# Если в буфере накопилось больше — считаем его мусором и сбрасываем
MAX_BUFFER_SIZE = 8192

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

async def async_setup(hass: HomeAssistant, config: dict):
    """Глобальная настройка (вызывается один раз при старте HA)."""

    async def handle_reload(call):
        """Служба для перезагрузки всех экземпляров нашей интеграции."""
        _LOGGER.info("Вызвана перезагрузка интеграции socket_listener")

        # Получаем все записи (Саша, Катя и т.д.)
        entries = hass.config_entries.async_entries(DOMAIN)

        for entry in entries:
            # Перезагружаем каждую запись
            await hass.config_entries.async_reload(entry.entry_id)

    # Регистрируем службу: socket_listener.reload
    hass.services.async_register(DOMAIN, "reload", handle_reload)

    return True

async def _handle_client(hass: HomeAssistant, port, reader, writer):
    hass.data[DOMAIN]["active_connections"].setdefault(port, set()).add(writer)
    mac = "unknown"
    current_entry_id = None
    polling_task = None  # Ссылка на фоновую задачу опроса
    unsub_send = None
    buffer = ""

    async def read_messages():
        """Читает из сокета очередную порцию и возвращает целые сообщения (None — отключение)."""
        nonlocal buffer
        chunk = await reader.read(1024)
        if not chunk:
            return None
        buffer += chunk.decode("utf-8", errors="ignore")
        messages, buffer = _extract_messages(buffer)
        return messages

    try:
        # 1. Ждем первый пакет (Hello)
        messages = []
        while not messages:
            if (messages := await read_messages()) is None:
                return

        data = messages[0]
        if not isinstance(data, dict) or "hello" not in data: return

        mac = str(data["id"])
        _LOGGER.info("Device %s try connected", mac)
        # Получаем имя из нашей карты. Если нет — используем MAC.
        friendly_name = hass.data[DOMAIN].get("mac_to_name", {}).get(mac, mac)
        # Проверяем, есть ли этот MAC в списке любой из запущенных интеграций
        if mac not in hass.data[DOMAIN]["active_macs"]:
            if mac not in hass.data[DOMAIN]["notified_macs"]:
                hass.data[DOMAIN]["notified_macs"].add(mac)
                hass.data[DOMAIN]["last_discovered_mac"] = mac

                _LOGGER.info("Новое устройство %s добавлено в очередь уведомлений", mac)

                persistent_notification.async_create(
                    hass,
                    title="Обнаружен новый Бризер",
                    message=(
                        f"Устройство с MAC-адресом **{mac}** пытается подключиться.\n\n"
                        f"Перейдите в настройки интеграций, чтобы добавить его."
                    ),
                    notification_id=f"discovery_{mac.replace(':', '')}"
                )
            return

        # Получаем ID записи для этого MAC, чтобы корректно привязать фоновые задачи
        current_entry_id = hass.data[DOMAIN]["active_macs"][mac]

        time = str(data["hello"]["time"])
        _LOGGER.info("Device %s is connected", friendly_name)

        # 1. Send Hello Response
        hello_res = f'{{"hello":true, "id": "{mac}", "time":"{time}", "time_zone": "-00:00"}}\n'
        _LOGGER.info("Send Hello to %s: %s", friendly_name, hello_res)
        writer.write(hello_res.encode("utf-8"))
        await writer.drain()

        # 2. Wait a moment then send get_setp
        await asyncio.sleep(0.5)
        cmd_res = f'{{"id": "{mac}", "cmd": {{"get_setp": true}}}}\n'
        _LOGGER.info("Send get_setp to %s: %s", friendly_name, cmd_res)
        writer.write(cmd_res.encode("utf-8"))
        await writer.drain()

        # 3. Слушатель внешних команд (от климата)
        async def send_command_listener(event):
            cmd = event.data.get("cmd")
            if cmd and not writer.transport.is_closing():
                writer.write(cmd.encode("utf-8"))
                await writer.drain()
                _LOGGER.debug("[%s] Отправлена внешняя команда: %s", mac, cmd.strip())

        unsub_send = hass.bus.async_listen(f"{DOMAIN}_send_cmd_{mac}", send_command_listener)

        # --- ЗАПУСК ПЕРИОДИЧЕСКОГО ОПРОСА ---
        async def poll():
            try:
                while not writer.transport.is_closing():
                    cmd_res = f'{{"id": "{mac}", "cmd": {{"get_state": true}}}}\n'
                    writer.write(cmd_res.encode("utf-8"))
                    await writer.drain()
                    _LOGGER.debug("Sent get_state to %s", mac)
                    await asyncio.sleep(5)
            except Exception as e:
                _LOGGER.debug("Polling stopped for %s: %s", mac, e)

        # Создаем задачу, которая будет работать в фоне для этого сокета
        polling_task = asyncio.create_task(poll())
        hass.data[DOMAIN].setdefault(current_entry_id, []).append(polling_task)

        # 3. Слушаем данные
        while True:
            messages = await read_messages()
            if messages is None: break # Устройство отключилось

            for payload in messages:
                if not isinstance(payload, dict):
                    _LOGGER.debug("Пропущен невалидный пакет: %s", payload)
                    continue
                _LOGGER.debug("Received data %s", payload)
                # Прокидываем данные в сенсоры
                hass.bus.async_fire(f"{DOMAIN}_data_{mac}", {"payload": payload})

    except Exception as e:
        _LOGGER.error("Error handling socket data: %s", e)
    finally:
        if polling_task:
            polling_task.cancel()
            tasks = hass.data[DOMAIN].get(current_entry_id, [])
            if polling_task in tasks:
                tasks.remove(polling_task)
        if unsub_send: unsub_send()
        hass.data[DOMAIN]["active_connections"].get(port, set()).discard(writer)
        writer.close()
        try: await writer.wait_closed()
        except Exception: pass

async def _async_start_server(hass: HomeAssistant, port):
    """Запускает один сервер для всех устройств."""
    _LOGGER.info("Попытка запуска сервера на порту %s", port)
    server = await asyncio.start_server(partial(_handle_client, hass, port), "0.0.0.0", port)
    hass.data[DOMAIN]["servers"][port] = server

    # Создаем задачу сервера и сохраняем, чтобы потом ее можно было отменить
    hass.data[DOMAIN]["server_tasks"][port] = asyncio.create_task(server.serve_forever())

    # ГЛАВНОЕ: Слушатель на остановку Home Assistant
    async def stop_server(event):
        # Слушатель одноразовый и уже сработал — отписываться от него не нужно
        hass.data[DOMAIN]["stop_unsubs"].pop(port, None)
        await _async_stop_server(hass, port)

    hass.data[DOMAIN]["stop_unsubs"][port] = hass.bus.async_listen_once(
        "homeassistant_stop", stop_server
    )

async def _async_stop_server(hass: HomeAssistant, port):
    _LOGGER.info("Остановка сервера на порту %s", port)
    data = hass.data[DOMAIN]

    if unsub := data["stop_unsubs"].pop(port, None):
        unsub()

    # 1. ПРИНУДИТЕЛЬНО закрываем все активные сокеты клиентов
    # Это разорвет циклы 'while True' и 'reader.read()'
    for writer in list(data["active_connections"].get(port, ())):
        writer.close()

    # 2. Теперь закрываем сам сервер — wait_closed() не будет висеть, так как соединений нет
    if server := data["servers"].pop(port, None):
        server.close()
        await server.wait_closed()

    # 3. Отменяем задачу самого сервера
    if task := data["server_tasks"].pop(port, None):
        task.cancel()

async def _async_release_devices(hass: HomeAssistant, devices):
    """Снимает регистрацию устройств и останавливает сервер."""
    data = hass.data[DOMAIN]
    for device in devices:
        data["active_macs"].pop(device[CONF_MAC], None)
        data["mac_to_name"].pop(device[CONF_MAC], None)

    if PORT in data["servers"]:
        await _async_stop_server(hass, PORT)

async def async_setup_entry(hass: HomeAssistant, entry):
    """Настройка экземпляра интеграции."""

    # Инициализируем структуру данных
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("mac_to_name", {})
    hass.data[DOMAIN].setdefault("servers", {})
    hass.data[DOMAIN].setdefault("server_tasks", {})
    hass.data[DOMAIN].setdefault("stop_unsubs", {})
    hass.data[DOMAIN].setdefault("active_macs", {}) # Здесь храним список разрешенных MAC
    hass.data[DOMAIN].setdefault("notified_macs", set())
    hass.data[DOMAIN].setdefault("active_connections", {})
    hass.data[DOMAIN].setdefault("entry_devices", {})
    hass.data[DOMAIN].setdefault(entry.entry_id, [])

    # Очищаем старые задачи этой записи, если они были (при обновлении через настройки)
    if tasks := hass.data[DOMAIN].get(entry.entry_id):
        for t in tasks:
            if not t.done(): t.cancel()
        hass.data[DOMAIN][entry.entry_id] = [] # Сбрасываем список задач

    active_macs = hass.data[DOMAIN]["active_macs"]
    keys_to_remove = [k for k, v in active_macs.items() if v == entry.entry_id]
    for k in keys_to_remove:
        active_macs.pop(k)

    # Получаем список устройств (поддержка как старого формата, так и нового списка)
    devices = list(entry.data.get("devices", [entry.data]))
    # Запоминаем, что именно зарегистрировали: к моменту выгрузки entry.data может уже измениться
    hass.data[DOMAIN]["entry_devices"][entry.entry_id] = devices

    for device in devices:
        mac = device[CONF_MAC]
        name = device[CONF_NAME]

        # Регистрируем MAC текущей интеграции в глобальном списке разрешенных
        hass.data[DOMAIN]["active_macs"][mac] = entry.entry_id
        # Запоминаем соответствие MAC -> Имя
        hass.data[DOMAIN]["mac_to_name"][mac] = name

    # Запускаем один сервер для всех устройств
    try:
        if PORT not in hass.data[DOMAIN]["servers"]:
            await _async_start_server(hass, PORT)
    except OSError as e:
        # Откатываем регистрацию, чтобы повторная попытка началась с чистого листа
        await _async_release_devices(hass, hass.data[DOMAIN]["entry_devices"].pop(entry.entry_id))
        raise ConfigEntryNotReady(f"Не удалось запустить сервер на порту {PORT}: {e}") from e

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry):
    # 1. Сначала отменяем все фоновые задачи (опросы) этой интеграции
    if tasks := hass.data[DOMAIN].get(entry.entry_id):
        for task in tasks:
            if not task.done():
                task.cancel()
        _LOGGER.debug("Cancelled all polling tasks for %s", entry.entry_id)

    # Выгружаем сенсоры
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        await _async_release_devices(hass, hass.data[DOMAIN]["entry_devices"].pop(entry.entry_id, []))

        # Очищаем данные интеграции
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
