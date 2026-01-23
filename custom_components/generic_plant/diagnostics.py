from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_PLANT_NAME,
    CONF_MOISTURE_ENTITY,
    CONF_PUMP_SWITCH,
    OPT_HEARTBEAT_TOPIC,
    OPT_LAST_SEEN,
    OPT_LAST_WATERED,
    OPT_LAST_EVALUATED,
    OPT_LAST_DECISION,
    OPT_THRESHOLD,
    OPT_PUMP_DURATION_S,
    OPT_COOLDOWN_MIN,
    OPT_STALE_AFTER_MIN,
    OPT_NOTIFY_SERVICE,
    OPT_NOTIFY_ON_WATER,
    OPT_NOTIFY_ON_STALE,
    OPT_NOTIFY_ON_FAILURE,
)
from .util import cfg


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    # Resolve current configurable entities (options override data)
    moisture_entity = cfg(entry, CONF_MOISTURE_ENTITY)
    pump_switch = cfg(entry, CONF_PUMP_SWITCH)

    # Capture current HA states (helpful for debugging)
    moisture_state = hass.states.get(moisture_entity) if moisture_entity else None
    pump_state = hass.states.get(pump_switch) if pump_switch else None

    return {
        "plant_name": entry.data.get(CONF_PLANT_NAME),
        "resolved": {
            "moisture_entity": moisture_entity,
            "pump_switch": pump_switch,
        },
        "options": {
            # Core settings
            "threshold": entry.options.get(OPT_THRESHOLD),
            "pump_duration_s": entry.options.get(OPT_PUMP_DURATION_S),
            "cooldown_min": entry.options.get(OPT_COOLDOWN_MIN),
            "stale_after_min": entry.options.get(OPT_STALE_AFTER_MIN),
            # Freshness/telemetry
            "heartbeat_topic": entry.options.get(OPT_HEARTBEAT_TOPIC),
            "last_seen": entry.options.get(OPT_LAST_SEEN),
            "last_watered": entry.options.get(OPT_LAST_WATERED),
            "last_evaluated": entry.options.get(OPT_LAST_EVALUATED),
            "last_decision": entry.options.get(OPT_LAST_DECISION),
            # Notifications
            "notify_service": entry.options.get(OPT_NOTIFY_SERVICE),
            "notify_on_water": entry.options.get(OPT_NOTIFY_ON_WATER),
            "notify_on_stale": entry.options.get(OPT_NOTIFY_ON_STALE),
            "notify_on_failure": entry.options.get(OPT_NOTIFY_ON_FAILURE),
        },
        "current_state": {
            "moisture": {
                "entity_id": moisture_entity,
                "state": moisture_state.state if moisture_state else None,
                "attributes": dict(moisture_state.attributes) if moisture_state else None,
            },
            "pump": {
                "entity_id": pump_switch,
                "state": pump_state.state if pump_state else None,
                "attributes": dict(pump_state.attributes) if pump_state else None,
            },
        },
    }
