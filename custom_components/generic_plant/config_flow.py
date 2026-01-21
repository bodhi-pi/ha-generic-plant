from __future__ import annotations

import re
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector, entity_registry as er

from .const import (
    DOMAIN,
    CONF_PLANT_NAME,
    CONF_MOISTURE_ENTITY,
    CONF_PUMP_SWITCH,
    OPT_HEARTBEAT_TOPIC,
    OPT_NOTIFY_SERVICE,
    OPT_NOTIFY_ON_WATER,
)

ECOWITT_UNIQUE_ID_RE = re.compile(r"^([0-9A-Fa-f]{32})_(.+)$")


class GenericPlantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Generic Plant."""

    VERSION = 1

    def __init__(self) -> None:
        self._draft: dict = {}

    async def async_step_user(self, user_input=None):
        """Initial setup (one-time): name + moisture entity + pump switch."""
        errors = {}

        if user_input is not None:
            plant_name = (user_input[CONF_PLANT_NAME] or "").strip()
            if not plant_name:
                errors["base"] = "name_required"
            else:
                self._draft = {
                    CONF_PLANT_NAME: plant_name,
                    CONF_MOISTURE_ENTITY: user_input[CONF_MOISTURE_ENTITY],
                    CONF_PUMP_SWITCH: user_input[CONF_PUMP_SWITCH],
                }
                # Optional step for heartbeat/notify on initial setup
                return await self.async_step_heartbeat()

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

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_heartbeat(self, user_input=None):
        """Initial-setup optional step: heartbeat + notify."""
        errors = {}

        suggested_topic = await self._suggest_heartbeat_topic(self._draft[CONF_MOISTURE_ENTITY])

        notify_choices = [""]  # blank means "no notifications"
        notify_services = self.hass.services.async_services().get("notify", {})
        for svc_name in sorted(notify_services.keys()):
            notify_choices.append(f"notify.{svc_name}")

        if user_input is not None:
            topic = (user_input.get(OPT_HEARTBEAT_TOPIC) or "").strip()
            notify_service = (user_input.get(OPT_NOTIFY_SERVICE) or "").strip()
            notify_on_water = bool(user_input.get(OPT_NOTIFY_ON_WATER, True))
            if not notify_service:
                notify_on_water = False

            return self.async_create_entry(
                title=self._draft[CONF_PLANT_NAME],
                data={
                    CONF_PLANT_NAME: self._draft[CONF_PLANT_NAME],
                    CONF_MOISTURE_ENTITY: self._draft[CONF_MOISTURE_ENTITY],
                    CONF_PUMP_SWITCH: self._draft[CONF_PUMP_SWITCH],
                },
                options={
                    OPT_HEARTBEAT_TOPIC: topic,
                    OPT_NOTIFY_SERVICE: notify_service,
                    OPT_NOTIFY_ON_WATER: notify_on_water,
                },
            )

        schema = vol.Schema(
            {
                vol.Optional(OPT_HEARTBEAT_TOPIC, default=suggested_topic): str,
                vol.Optional(OPT_NOTIFY_SERVICE, default=""): vol.In(notify_choices),
                vol.Optional(OPT_NOTIFY_ON_WATER, default=True): bool,
            }
        )

        return self.async_show_form(
            step_id="heartbeat",
            data_schema=schema,
            errors=errors,
        )

    async def _suggest_heartbeat_topic(self, moisture_entity_id: str) -> str:
        """Best-effort: infer ecowitt2mqtt discovery topic from MQTT entity unique_id."""
        ent_reg = er.async_get(self.hass)
        ent = ent_reg.async_get(moisture_entity_id)
        if not ent:
            return ""

        unique_id = ent.unique_id or ""
        m = ECOWITT_UNIQUE_ID_RE.match(unique_id)
        if not m:
            return ""

        device_id = m.group(1)
        object_id = m.group(2)
        return f"homeassistant/sensor/{device_id}/{object_id}/state"

    @staticmethod
    async def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Return the options flow handler."""
        return GenericPlantOptionsFlow(config_entry)


class GenericPlantOptionsFlow(config_entries.OptionsFlow):
    """Options flow: edits entry.options in place."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input=None):
        errors = {}

        # Existing values (what we'll edit in place)
        current_topic = (self.entry.options.get(OPT_HEARTBEAT_TOPIC) or "").strip()
        current_notify_service = (self.entry.options.get(OPT_NOTIFY_SERVICE) or "").strip()
        current_notify_on_water = bool(self.entry.options.get(OPT_NOTIFY_ON_WATER, False))

        # Populate notify service choices dynamically
        notify_choices = [""]  # blank means "no notifications"
        notify_services = self.hass.services.async_services().get("notify", {})
        for svc_name in sorted(notify_services.keys()):
            notify_choices.append(f"notify.{svc_name}")

        if user_input is not None:
            topic = (user_input.get(OPT_HEARTBEAT_TOPIC) or "").strip()
            notify_service = (user_input.get(OPT_NOTIFY_SERVICE) or "").strip()
            notify_on_water = bool(user_input.get(OPT_NOTIFY_ON_WATER, True))
            if not notify_service:
                notify_on_water = False

            return self.async_create_entry(
                title="",
                data={
                    OPT_HEARTBEAT_TOPIC: topic,
                    OPT_NOTIFY_SERVICE: notify_service,
                    OPT_NOTIFY_ON_WATER: notify_on_water,
                },
            )

        schema = vol.Schema(
            {
                vol.Optional(OPT_HEARTBEAT_TOPIC, default=current_topic): str,
                vol.Optional(OPT_NOTIFY_SERVICE, default=current_notify_service): vol.In(notify_choices),
                vol.Optional(OPT_NOTIFY_ON_WATER, default=current_notify_on_water): bool,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
