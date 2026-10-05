import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .options_flow import AirNannyOptionsFlowHandler
from .const import DOMAIN, CONF_NAME, CONF_MAC

class SocketConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        # Если интеграция уже создана, перенаправляем на добавление устройства
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(title="AirNanny", data={"devices": [user_input]})

        # Форма с предзаполненными значениями по умолчанию
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default='Саша'): str,
                vol.Required(CONF_MAC, default='1C:9D:C2:EC:2E:BC:0'): str,
            }),
            errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AirNannyOptionsFlowHandler()