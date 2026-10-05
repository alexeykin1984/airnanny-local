from homeassistant.helpers.dispatcher import async_dispatcher_send
import asyncio
import json
import logging
from homeassistant.core import HomeAssistant
from homeassistant.components import persistent_notification
from homeassistant.helpers import entity_registry as er
from .const import DOMAIN, CONF_PORT, CONF_NAME, CONF_MAC

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "climate", "switch", "number", "binary_sensor"]

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

async def async_setup_entry(hass: HomeAssistant, entry):
    """Настройка экземпляра интеграции."""

    # Инициализируем структуру данных
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("mac_to_name", {})
    hass.data[DOMAIN].setdefault("servers", {})
    hass.data[DOMAIN].setdefault("entry_counts", {})
    hass.data[DOMAIN].setdefault("active_macs", {}) # Здесь храним список разрешенных MAC
    hass.data[DOMAIN].setdefault("notified_macs", set())
    hass.data[DOMAIN].setdefault("active_connections", {})
    hass.data[DOMAIN].setdefault(entry.entry_id, [])

    # Очищаем старые задачи этой записи, если они были (при обновлении через настройки)
    if entry.entry_id in hass.data.get(DOMAIN, {}):
        if tasks := hass.data[DOMAIN].get(entry.entry_id):
            for t in tasks:
                if not t.done(): t.cancel()
            hass.data[DOMAIN][entry.entry_id] = [] # Сбрасываем список задач

    if DOMAIN in hass.data:
        active_macs = hass.data[DOMAIN].get("active_macs", {})
        keys_to_remove = [k for k, v in active_macs.items() if v == entry.entry_id]
        for k in keys_to_remove:
            active_macs.pop(k)

    # Получаем список устройств (поддержка как старого формата, так и нового списка)
    devices = entry.data.get("devices", [entry.data])

    for device in devices:
        mac = device[CONF_MAC]
        name = device[CONF_NAME]
        port = device[CONF_PORT]

        # Регистрируем MAC текущей интеграции в глобальном списке разрешенных
        hass.data[DOMAIN]["active_macs"][mac] = entry.entry_id
        hass.data[DOMAIN]["entry_counts"][port] = hass.data[DOMAIN]["entry_counts"].get(port, 0) + 1
        # Запоминаем соответствие MAC -> Имя
        hass.data[DOMAIN]["mac_to_name"][mac] = name
        if port not in hass.data[DOMAIN]["active_connections"]:
            hass.data[DOMAIN]["active_connections"][port] = set()

    async def handle_client(reader, writer):
        hass.data[DOMAIN]["active_connections"][port].add(writer)
        mac = "unknown"
        polling_task = None  # Ссылка на фоновую задачу опроса
        unsub_send = None
        try:
            # 1. Ждем первый пакет (Hello)
            raw_data = await reader.read(1024)
            if not raw_data: return

            # Parse JSON
            data = json.loads(raw_data)
            _LOGGER.info("Device try connected", mac)

            if "hello" not in data: return

            mac = str(data["id"])
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
            hass.data[DOMAIN][current_entry_id].append(polling_task)

            # 3. Слушаем данные
            while True:
                cont_data = await reader.read(1024)
                if not cont_data: break # Устройство отключилось

                try:
                    payload = json.loads(cont_data)
                    _LOGGER.debug("Received data %s", data)
                    # Прокидываем данные в сенсоры
                    hass.bus.async_fire(f"{DOMAIN}_data_{mac}", {"payload": payload})
                except json.JSONDecodeError:
                    _LOGGER.debug("Пропущен невалидный пакет: %s", cont_data)

        except Exception as e:
            _LOGGER.error("Error handling socket data: %s", e)
        finally:
            if polling_task: polling_task.cancel()
            if unsub_send: unsub_send()
            if port in hass.data[DOMAIN]["active_connections"]:
                hass.data[DOMAIN]["active_connections"][port].discard(writer)
            writer.close()
            try: await writer.wait_closed()
            except: pass

    # Запускаем один сервер на порт для всех экземпляров
    if port not in hass.data[DOMAIN]["servers"]:
        try:
            _LOGGER.info("Попытка запуска сервера на порту %s", port)
            server = await asyncio.start_server(handle_client, "0.0.0.0", port)
            hass.data[DOMAIN]["servers"][port] = server

            # Создаем задачу сервера
            server_task = asyncio.create_task(server.serve_forever())

            # Сохраняем задачу, чтобы потом ее можно было отменить
            hass.data[DOMAIN].setdefault("server_tasks", {})
            hass.data[DOMAIN]["server_tasks"][port] = server_task

            # ГЛАВНОЕ: Слушатель на остановку Home Assistant
            async def stop_server(event):
                _LOGGER.info("Остановка сервера на порту %s", port)
                # Отменяем опрос для всех
                for eid in list(hass.data[DOMAIN].keys()):
                    if isinstance(hass.data[DOMAIN].get(eid), list):
                        for task in hass.data[DOMAIN][eid]:
                            if not task.done(): task.cancel()

                # 2. ПРИНУДИТЕЛЬНО закрываем все активные сокеты клиентов
                # Это разорвет циклы 'while True' и 'reader.read()'
                if port in hass.data[DOMAIN]["active_connections"]:
                    for writer in list(hass.data[DOMAIN]["active_connections"][port]):
                        writer.close()
                    hass.data[DOMAIN]["active_connections"][port].clear()

                # 3. Теперь закрываем сам сервер (теперь он закроется мгновенно)
                if port in hass.data[DOMAIN]["servers"]:
                    srv = hass.data[DOMAIN]["servers"].pop(port)
                    srv.close()
                    # Теперь wait_closed() не будет висеть, так как соединений нет
                    await srv.wait_closed()

                # Отменяем задачу самого сервера
                if port in hass.data[DOMAIN]["server_tasks"]:
                    task = hass.data[DOMAIN]["server_tasks"].pop(port)
                    task.cancel()

            # Регистрируем событие один раз для сервера
            hass.bus.async_listen_once("homeassistant_stop", stop_server)
        
        except OSError as e:
            if e.errno == 98:
                _LOGGER.warning("Порт %s уже занят. Возможно, сервер уже запущен другим процессом.", port)
                # Не вызываем исключение, чтобы интеграция "Катя" могла продолжить работу,
                # используя сервер, запущенный "Сашей"
            else:
                raise e
    else:
        _LOGGER.debug("Сервер на порту %s уже запущен, используем существующий", port)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry):
    devices = entry.data.get("devices", [entry.data])

    # 1. Сначала отменяем все фоновые задачи (опросы) этой интеграции
    if tasks := hass.data[DOMAIN].get(entry.entry_id):
        for task in tasks:
            if not task.done():
                task.cancel()
        _LOGGER.debug("Cancelled all polling tasks for %s", entry.entry_id)

    # Выгружаем сенсоры
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        for device in devices:
            mac = device[CONF_MAC]
            port = device[CONF_PORT]
            hass.data[DOMAIN]["active_macs"].pop(mac, None)
            hass.data[DOMAIN]["entry_counts"][port] -= 1

            # 3. Если это последняя интеграция на порту — закрываем сервер
            if hass.data[DOMAIN]["entry_counts"][port] <= 0:
                server = hass.data[DOMAIN]["servers"].pop(port, None)
                if server:
                    server.close()
                    await server.wait_closed()
                    _LOGGER.info("Server on port %s stopped", port)

        # Очищаем данные интеграции
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok