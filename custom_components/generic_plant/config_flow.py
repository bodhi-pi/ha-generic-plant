from __future__ import annotations

import re
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector, entity_registry as er

from .const import (
    DOMAIN,
    CONF_PLANT_NAME,
    CONF_MOISTURE_ENTITY,
    CONF_PUMP_SWITCH,
    PLANT_MODE,
    MODE_AUTO,
    MODE_SENSOR,
    MODE_MANUAL,
    OPT_HEARTBEAT_TOPIC,
    OPT_NOTIFY_SERVICE,
    OPT_NOTIFY_ON_WATER,
    OPT_NOTIFY_ON_STALE,
    OPT_NOTIFY_ON_FAILURE,
)

ECOWITT_UNIQUE_ID_RE = re.compile(r"^([0-9A-Fa-f]{32})_(.+)$")

MODE_LABELS = {
    MODE_AUTO: "Auto (sensor + pump)",
    MODE_SENSOR: "Sensor only (notify when dry)",
    MODE_MANUAL: "Manual (no sensor, schedule-based)",
}


def _notify_choices(hass: HomeAssistant) -> list[str]:
    choices = [""]
    for svc_name in sorted(hass.services.async_services().get("notify", {}).keys()):
        choices.append(f"notify.{svc_name}")
    return choices


def _suggest_heartbeat_from_entity(hass: HomeAssistant, moisture_entity_id: str) -> str:
    ent_reg = er.async_get(hass)
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


class GenericPlantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):

    VERSION = 1

    def __init__(self) -> None:
        self._draft: dict = {}

    async def async_step_user(self, user_input=None):
        """Step 1: plant name + mode."""
        errors = {}

        if user_input is not None:
            plant_name = (user_input[CONF_PLANT_NAME] or "").strip()
            if not plant_name:
                errors["base"] = "name_required"
            else:
                self._draft = {
                    CONF_PLANT_NAME: plant_name,
                    PLANT_MODE: user_input[PLANT_MODE],
                }
                mode = user_input[PLANT_MODE]
                if mode == MODE_MANUAL:
                    return await self.async_step_notifications()
                else:
                    return await self.async_step_entities()

        schema = vol.Schema(
            {
                vol.Required(CONF_PLANT_NAME, default=""): str,
                vol.Required(PLANT_MODE, default=MODE_AUTO): vol.In(MODE_LABELS),
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_entities(self, user_input=None):
        """Step 2 (auto + sensor_only): pick moisture entity and optionally pump."""
        errors = {}
        mode = self._draft[PLANT_MODE]

        if user_input is not None:
            self._draft[CONF_MOISTURE_ENTITY] = user_input[CONF_MOISTURE_ENTITY]
            if mode == MODE_AUTO:
                self._draft[CONF_PUMP_SWITCH] = user_input.get(CONF_PUMP_SWITCH, "")
            return await self.async_step_notifications()

        if mode == MODE_AUTO:
            schema = vol.Schema(
                {
                    vol.Required(CONF_MOISTURE_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor")
                    ),
                    vol.Required(CONF_PUMP_SWITCH): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="switch")
                    ),
                }
            )
        else:
            schema = vol.Schema(
                {
                    vol.Required(CONF_MOISTURE_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor")
                    ),
                }
            )

        return self.async_show_form(step_id="entities", data_schema=schema, errors=errors)

    async def async_step_notifications(self, user_input=None):
        """Step 3: heartbeat topic + notifications."""
        notify_choices = _notify_choices(self.hass)
        mode = self._draft[PLANT_MODE]
        moisture_entity = self._draft.get(CONF_MOISTURE_ENTITY, "")
        suggested_topic = (
            _suggest_heartbeat_from_entity(self.hass, moisture_entity)
            if moisture_entity
            else ""
        )

        if user_input is not None:
            topic = (user_input.get(OPT_HEARTBEAT_TOPIC) or "").strip()
            notify_service = (user_input.get(OPT_NOTIFY_SERVICE) or "").strip()
            notify_on_water = bool(user_input.get(OPT_NOTIFY_ON_WATER, True))
            notify_on_stale = bool(user_input.get(OPT_NOTIFY_ON_STALE, False))
            notify_on_failure = bool(user_input.get(OPT_NOTIFY_ON_FAILURE, False))

            if not notify_service:
                notify_on_water = False
                notify_on_stale = False
                notify_on_failure = False

            return self.async_create_entry(
                title=self._draft[CONF_PLANT_NAME],
                data={
                    CONF_PLANT_NAME: self._draft[CONF_PLANT_NAME],
                    CONF_MOISTURE_ENTITY: self._draft.get(CONF_MOISTURE_ENTITY, ""),
                    CONF_PUMP_SWITCH: self._draft.get(CONF_PUMP_SWITCH, ""),
                },
                options={
                    PLANT_MODE: mode,
                    CONF_PLANT_NAME: self._draft[CONF_PLANT_NAME],
                    CONF_MOISTURE_ENTITY: self._draft.get(CONF_MOISTURE_ENTITY, ""),
                    CONF_PUMP_SWITCH: self._draft.get(CONF_PUMP_SWITCH, ""),
                    OPT_HEARTBEAT_TOPIC: topic,
                    OPT_NOTIFY_SERVICE: notify_service,
                    OPT_NOTIFY_ON_WATER: notify_on_water,
                    OPT_NOTIFY_ON_STALE: notify_on_stale,
                    OPT_NOTIFY_ON_FAILURE: notify_on_failure,
                },
            )

        # Heartbeat topic only relevant for sensor-based modes
        if mode == MODE_MANUAL:
            schema = vol.Schema(
                {
                    vol.Optional(OPT_NOTIFY_SERVICE, default=""): vol.In(notify_choices),
                    vol.Optional(OPT_NOTIFY_ON_WATER, default=True): bool,
                }
            )
        else:
            schema = vol.Schema(
                {
                    vol.Optional(OPT_HEARTBEAT_TOPIC, default=suggested_topic): str,
                    vol.Optional(OPT_NOTIFY_SERVICE, default=""): vol.In(notify_choices),
                    vol.Optional(OPT_NOTIFY_ON_WATER, default=True): bool,
                    vol.Optional(OPT_NOTIFY_ON_STALE, default=False): bool,
                    vol.Optional(OPT_NOTIFY_ON_FAILURE, default=False): bool,
                }
            )

        return self.async_show_form(step_id="notifications", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return GenericPlantOptionsFlow(config_entry)


class GenericPlantOptionsFlow(config_entries.OptionsFlow):

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input=None):
        notify_choices = _notify_choices(self.hass)

        mode = self.entry.options.get(PLANT_MODE, MODE_AUTO)
        current_name = (self.entry.options.get(CONF_PLANT_NAME) or self.entry.data.get(CONF_PLANT_NAME) or "").strip()
        current_moisture = self.entry.options.get(CONF_MOISTURE_ENTITY) or self.entry.data.get(CONF_MOISTURE_ENTITY)
        current_pump = self.entry.options.get(CONF_PUMP_SWITCH) or self.entry.data.get(CONF_PUMP_SWITCH)
        current_topic = (self.entry.options.get(OPT_HEARTBEAT_TOPIC) or "").strip()
        current_notify_service = (self.entry.options.get(OPT_NOTIFY_SERVICE) or "").strip()
        current_notify_on_water = bool(self.entry.options.get(OPT_NOTIFY_ON_WATER, False))
        current_notify_on_stale = bool(self.entry.options.get(OPT_NOTIFY_ON_STALE, False))
        current_notify_on_failure = bool(self.entry.options.get(OPT_NOTIFY_ON_FAILURE, False))

        if not current_topic and current_moisture:
            current_topic = _suggest_heartbeat_from_entity(self.hass, current_moisture)

        if user_input is not None:
            new_name = (user_input.get(CONF_PLANT_NAME) or "").strip()
            new_mode = user_input.get(PLANT_MODE, mode)
            topic = (user_input.get(OPT_HEARTBEAT_TOPIC) or "").strip()
            notify_service = (user_input.get(OPT_NOTIFY_SERVICE) or "").strip()
            notify_on_water = bool(user_input.get(OPT_NOTIFY_ON_WATER, True))
            notify_on_stale = bool(user_input.get(OPT_NOTIFY_ON_STALE, False))
            notify_on_failure = bool(user_input.get(OPT_NOTIFY_ON_FAILURE, False))

            if not notify_service:
                notify_on_water = False
                notify_on_stale = False
                notify_on_failure = False

            new_options = {
                **self.entry.options,
                PLANT_MODE: new_mode,
                CONF_PLANT_NAME: new_name,
                CONF_MOISTURE_ENTITY: user_input.get(CONF_MOISTURE_ENTITY, current_moisture),
                CONF_PUMP_SWITCH: user_input.get(CONF_PUMP_SWITCH, current_pump),
                OPT_HEARTBEAT_TOPIC: topic,
                OPT_NOTIFY_SERVICE: notify_service,
                OPT_NOTIFY_ON_WATER: notify_on_water,
                OPT_NOTIFY_ON_STALE: notify_on_stale,
                OPT_NOTIFY_ON_FAILURE: notify_on_failure,
            }

            if new_name and new_name != self.entry.title:
                self.hass.config_entries.async_update_entry(self.entry, title=new_name)

            return self.async_create_entry(title="", data=new_options)

        # Build schema based on current mode
        fields = {
            vol.Required(CONF_PLANT_NAME, default=current_name): str,
            vol.Required(PLANT_MODE, default=mode): vol.In(MODE_LABELS),
        }

        if mode in (MODE_AUTO, MODE_SENSOR):
            fields[vol.Required(CONF_MOISTURE_ENTITY, default=current_moisture)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )

        if mode == MODE_AUTO:
            fields[vol.Required(CONF_PUMP_SWITCH, default=current_pump)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            )

        if mode != MODE_MANUAL:
            fields[vol.Optional(OPT_HEARTBEAT_TOPIC, default=current_topic)] = str
            fields[vol.Optional(OPT_NOTIFY_ON_STALE, default=current_notify_on_stale)] = bool
            fields[vol.Optional(OPT_NOTIFY_ON_FAILURE, default=current_notify_on_failure)] = bool

        fields[vol.Optional(OPT_NOTIFY_SERVICE, default=current_notify_service)] = vol.In(notify_choices)
        fields[vol.Optional(OPT_NOTIFY_ON_WATER, default=current_notify_on_water)] = bool

        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields))
