import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .options_flow import AirNannyOptionsFlowHandler
from .const import DOMAIN, CONF_NAME, CONF_MAC

class SocketConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        # Запись одна на все устройства (single_config_entry в manifest.json),
        # остальные устройства добавляются через настройки
        if user_input is not None:
            return self.async_create_entry(title="AirNanny", data={"devices": [user_input]})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_MAC): str,
            }),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AirNannyOptionsFlowHandler()
