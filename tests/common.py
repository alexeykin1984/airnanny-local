"""Эмулятор бризера и вспомогательные функции для тестов."""
import asyncio
import json

DOMAIN = "airnanny_local"
MAC = "1C:9D:C2:EC:2E:BC:0"
OTHER_MAC = "AA:BB:CC"
# Тесты поднимают сервер на отдельном порту, чтобы не мешать настоящему HA
PORT = 39001

POLL_COMMANDS = ({"get_state": True}, {"get_setp": True})


class Breezer:
    """Клиент, который ведёт себя как бризер: шлёт hello и принимает команды."""

    async def connect(self, mac=MAC, split=False):
        self.mac = mac
        self.reader, self.writer = await asyncio.open_connection("127.0.0.1", PORT)
        hello = json.dumps({"hello": {"time": 123}, "id": mac}).encode()
        if split:
            # hello приходит двумя кусками
            await self.send(hello[:9])
            await asyncio.sleep(0.05)
            await self.send(hello[9:])
        else:
            await self.send(hello)
        return self

    async def send(self, raw: bytes):
        self.writer.write(raw)
        await self.writer.drain()

    async def raw_line(self) -> bytes:
        return await asyncio.wait_for(self.reader.readline(), 2)

    async def line(self):
        raw = await self.raw_line()
        return json.loads(raw) if raw else None

    async def expect(self, cmd: dict) -> bytes:
        """Читает сообщения, пропуская hello и опрос, пока не встретит команду. Возвращает её как есть."""
        for _ in range(50):
            raw = await self.raw_line()
            assert raw, f"соединение закрыто, ждали {cmd}"
            msg = json.loads(raw)
            if msg.get("cmd") == cmd:
                assert msg["id"] == self.mac
                return raw
            assert msg.get("hello") or msg.get("cmd") in POLL_COMMANDS, msg
        raise AssertionError(f"не дождались {cmd}")

    async def closed(self) -> bool:
        """Ждёт, пока сервер закроет соединение."""
        while await self.raw_line():
            pass
        return True

    def close(self):
        self.writer.close()


async def until(hass, condition, what=""):
    """Ждёт выполнения условия: данные идут через настоящий сокет, поэтому не мгновенно."""
    for _ in range(100):
        await hass.async_block_till_done()
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"не дождались: {what}")


def state_of(hass, entity_id):
    state = hass.states.get(entity_id)
    return state.state if state else None
