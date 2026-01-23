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
    OPT_HEARTBEAT_TOPIC,
    OPT_NOTIFY_SERVICE,
    OPT_NOTIFY_ON_WATER,
    OPT_NOTIFY_ON_STALE,
    OPT_NOTIFY_ON_FAILURE,
)

# ecowitt2mqtt discovery often yields unique_id like:
#   9785F8791BBBDD8186EF62BE0B96515E_soilmoisture4
ECOWITT_UNIQUE_ID_RE = re.compile(r"^([0-9A-Fa-f]{32})_(.+)$")


def _notify_choices(hass: HomeAssistant) -> list[str]:
    """Return list of notify service strings like ['', 'notify.mobile_app_x', ...]."""
    choices = [""]
    notify_services = hass.services.async_services().get("notify", {})
    for svc_name in sorted(notify_services.keys()):
        choices.append(f"notify.{svc_name}")
    return choices


def _suggest_heartbeat_from_entity(hass: HomeAssistant, moisture_entity_id: str) -> str:
    """Best-effort: infer ecowitt2mqtt discovery topic from MQTT entity unique_id."""
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
    """Initial config flow (one plant = one entry)."""

    VERSION = 1

    def __init__(self) -> None:
        self._draft: dict = {}

    async def async_step_user(self, user_input=None):
        """Step 1: plant name + moisture entity + pump switch."""
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
                return await self.async_step_options()

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

    async def async_step_options(self, user_input=None):
        """Step 2 (optional): heartbeat topic + notifications."""
        notify_choices = _notify_choices(self.hass)
        suggested_topic = _suggest_heartbeat_from_entity(self.hass, self._draft[CONF_MOISTURE_ENTITY])

        if user_input is not None:
            topic = (user_input.get(OPT_HEARTBEAT_TOPIC) or "").strip()
            notify_service = (user_input.get(OPT_NOTIFY_SERVICE) or "").strip()

            # Default toggles:
            notify_on_water = bool(user_input.get(OPT_NOTIFY_ON_WATER, True))
            notify_on_stale = bool(user_input.get(OPT_NOTIFY_ON_STALE, False))
            notify_on_failure = bool(user_input.get(OPT_NOTIFY_ON_FAILURE, False))

            # If no notify service selected, disable all notification toggles
            if not notify_service:
                notify_on_water = False
                notify_on_stale = False
                notify_on_failure = False

            # Keep initial setup data minimal (for backward compatibility), but
            # ALSO store configurable fields in options so they can be edited later.
            return self.async_create_entry(
                title=self._draft[CONF_PLANT_NAME],
                data={
                    # Legacy/back-compat storage
                    CONF_PLANT_NAME: self._draft[CONF_PLANT_NAME],
                    CONF_MOISTURE_ENTITY: self._draft[CONF_MOISTURE_ENTITY],
                    CONF_PUMP_SWITCH: self._draft[CONF_PUMP_SWITCH],
                },
                options={
                    # ✅ Configurable-after-setup fields:
                    CONF_PLANT_NAME: self._draft[CONF_PLANT_NAME],
                    CONF_MOISTURE_ENTITY: self._draft[CONF_MOISTURE_ENTITY],
                    CONF_PUMP_SWITCH: self._draft[CONF_PUMP_SWITCH],

                    # Existing options:
                    OPT_HEARTBEAT_TOPIC: topic,
                    OPT_NOTIFY_SERVICE: notify_service,
                    OPT_NOTIFY_ON_WATER: notify_on_water,
                    OPT_NOTIFY_ON_STALE: notify_on_stale,
                    OPT_NOTIFY_ON_FAILURE: notify_on_failure,
                },
            )

        schema = vol.Schema(
            {
                vol.Optional(OPT_HEARTBEAT_TOPIC, default=suggested_topic): str,
                vol.Optional(OPT_NOTIFY_SERVICE, default=""): vol.In(notify_choices),

                # Notification toggles (only meaningful if a notify service is selected)
                vol.Optional(OPT_NOTIFY_ON_WATER, default=True): bool,
                vol.Optional(OPT_NOTIFY_ON_STALE, default=False): bool,
                vol.Optional(OPT_NOTIFY_ON_FAILURE, default=False): bool,
            }
        )

        return self.async_show_form(step_id="options", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return GenericPlantOptionsFlow(config_entry)


class GenericPlantOptionsFlow(config_entries.OptionsFlow):
    """Reconfigure entry.options in place (never delete/re-add)."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input=None):
        notify_choices = _notify_choices(self.hass)

        # Current values (prefer options, fall back to data)
        current_name = (self.entry.options.get(CONF_PLANT_NAME) or self.entry.data.get(CONF_PLANT_NAME) or "").strip()
        current_moisture = self.entry.options.get(CONF_MOISTURE_ENTITY) or self.entry.data.get(CONF_MOISTURE_ENTITY)
        current_pump = self.entry.options.get(CONF_PUMP_SWITCH) or self.entry.data.get(CONF_PUMP_SWITCH)

        current_topic = (self.entry.options.get(OPT_HEARTBEAT_TOPIC) or "").strip()
        current_notify_service = (self.entry.options.get(OPT_NOTIFY_SERVICE) or "").strip()
        current_notify_on_water = bool(self.entry.options.get(OPT_NOTIFY_ON_WATER, False))
        current_notify_on_stale = bool(self.entry.options.get(OPT_NOTIFY_ON_STALE, False))
        current_notify_on_failure = bool(self.entry.options.get(OPT_NOTIFY_ON_FAILURE, False))

        # Auto-suggest heartbeat topic only if blank
        if not current_topic and current_moisture:
            current_topic = _suggest_heartbeat_from_entity(self.hass, current_moisture)

        if user_input is not None:
            new_name = (user_input.get(CONF_PLANT_NAME) or "").strip()
            new_moisture = user_input.get(CONF_MOISTURE_ENTITY)
            new_pump = user_input.get(CONF_PUMP_SWITCH)

            topic = (user_input.get(OPT_HEARTBEAT_TOPIC) or "").strip()
            notify_service = (user_input.get(OPT_NOTIFY_SERVICE) or "").strip()

            notify_on_water = bool(user_input.get(OPT_NOTIFY_ON_WATER, True))
            notify_on_stale = bool(user_input.get(OPT_NOTIFY_ON_STALE, False))
            notify_on_failure = bool(user_input.get(OPT_NOTIFY_ON_FAILURE, False))

            if not notify_service:
                notify_on_water = False
                notify_on_stale = False
                notify_on_failure = False

            # ✅ IMPORTANT: merge (do not overwrite) so we don't wipe thresholds, last_watered, etc.
            new_options = {
                **self.entry.options,

                # ✅ Make core things editable:
                CONF_PLANT_NAME: new_name,
                CONF_MOISTURE_ENTITY: new_moisture,
                CONF_PUMP_SWITCH: new_pump,

                # Existing options:
                OPT_HEARTBEAT_TOPIC: topic,
                OPT_NOTIFY_SERVICE: notify_service,
                OPT_NOTIFY_ON_WATER: notify_on_water,
                OPT_NOTIFY_ON_STALE: notify_on_stale,
                OPT_NOTIFY_ON_FAILURE: notify_on_failure,
            }

            # Also update the config entry title so UI matches the plant name.
            # (This does not require delete/re-add.)
            if new_name and new_name != self.entry.title:
                self.hass.config_entries.async_update_entry(self.entry, title=new_name)

            return self.async_create_entry(title="", data=new_options)

        schema = vol.Schema(
            {
                # ✅ now editable after setup:
                vol.Required(CONF_PLANT_NAME, default=current_name): str,
                vol.Required(CONF_MOISTURE_ENTITY, default=current_moisture): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_PUMP_SWITCH, default=current_pump): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),

                # existing options:
                vol.Optional(OPT_HEARTBEAT_TOPIC, default=current_topic): str,
                vol.Optional(OPT_NOTIFY_SERVICE, default=current_notify_service): vol.In(notify_choices),
                vol.Optional(OPT_NOTIFY_ON_WATER, default=current_notify_on_water): bool,
                vol.Optional(OPT_NOTIFY_ON_STALE, default=current_notify_on_stale): bool,
                vol.Optional(OPT_NOTIFY_ON_FAILURE, default=current_notify_on_failure): bool,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)