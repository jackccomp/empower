"""UI setup for a single electricity meter supplied by the Mac reader."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util
from .const import DOMAIN, NAME


class EmpowerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            if await dt_util.async_get_time_zone(user_input["time_zone"]) is None:
                errors["time_zone"] = "invalid_timezone"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=NAME, data=user_input)
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Required("time_zone", default="America/Chicago"): str,
            vol.Required("timestamp_label"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=["start", "end"], mode=selector.SelectSelectorMode.DROPDOWN)),
        }), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return EmpowerOptionsFlow()


class EmpowerOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Required("import_statistics", default=self.config_entry.options.get("import_statistics", False)): bool,
        }))
