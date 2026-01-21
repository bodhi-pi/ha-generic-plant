from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector

from .const import DOMAIN, CONF_MOISTURE_ENTITY, CONF_PLANT_NAME, CONF_PUMP_SWITCH


class GenericPlantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Generic Plant."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            # Basic validation: ensure entities look like entity IDs
            plant_name = user_input[CONF_PLANT_NAME].strip()
            moisture_entity = user_input[CONF_MOISTURE_ENTITY]
            pump_switch = user_input[CONF_PUMP_SWITCH]

            if not plant_name:
                errors["base"] = "name_required"
            else:
                return self.async_create_entry(
                    title=plant_name,
                    data={
                        CONF_PLANT_NAME: plant_name,
                        CONF_MOISTURE_ENTITY: moisture_entity,
                        CONF_PUMP_SWITCH: pump_switch,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_PLANT_NAME, default=""): str,
                vol.Required(CONF_MOISTURE_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_PUMP_SWITCH): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
