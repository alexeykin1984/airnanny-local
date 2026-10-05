import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN, CONF_PORT, CONF_MAC, CONF_NAME

class AirNannyOptionsFlowHandler(config_entries.OptionsFlow):
    # __init__ больше не нужен, если мы только сохраняли config_entry

    async def async_step_init(self, user_input=None):
        """Меню настроек."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_device", "remove_device"]
        )

    async def async_step_add_device(self, user_input=None):
        """Шаг добавления нового устройства."""
        errors = {}
        if user_input is not None:
            # Используем встроенный self.config_entry
            devices = list(self.config_entry.data.get("devices", [])).copy()
            if any(d[CONF_MAC] == user_input[CONF_MAC] for d in devices):
                errors["base"] = "already_configured"
            else:
                devices.append(user_input)

                # 1. Обновляем данные записи
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, "devices": devices}
                )

                # 2. ПРИНУДИТЕЛЬНО перезагружаем, чтобы HA увидел новый список устройств
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                # 3. Закрываем окно настроек
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="add_device",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_MAC): str,
                vol.Required(CONF_PORT, default=3001): int,
            }),
            errors=errors
        )

    async def async_step_remove_device(self, user_input=None):
        """Шаг удаления устройства."""
        devices = self.config_entry.data.get("devices", [])

        if user_input is not None:
            new_devices = [d for d in devices if d[CONF_MAC] != user_input["mac_to_remove"]]
            self.hass.config_entries.async_update_entry(
                self.config_entry, data={**self.config_entry.data, "devices": new_devices}
            )
            return self.async_create_entry(title="", data={})

        device_options = {d[CONF_MAC]: f"{d[CONF_NAME]} [{d[CONF_MAC]}]" for d in devices}

        return self.async_show_form(
            step_id="remove_device",
            data_schema=vol.Schema({
                vol.Required("mac_to_remove"): vol.In(device_options)
            })
        )
