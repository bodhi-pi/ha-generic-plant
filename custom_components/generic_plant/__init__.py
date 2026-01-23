from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .engine import PlantEngine

# Platforms we provide for each plant entry
PLATFORMS: list[str] = ["sensor", "number", "button", "switch", "binary_sensor"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up from YAML (not used)."""
    return True


@callback
def _get_runtime(hass: HomeAssistant, entry_id: str) -> dict[str, Any] | None:
    return hass.data.get(DOMAIN, {}).get(entry_id)


async def _entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Called whenever entry.options changes (Options Flow save)."""
    runtime = _get_runtime(hass, entry.entry_id)
    if not runtime:
        return

    # Reconfigure sensors (moisture listener + MQTT heartbeat)
    sensors = runtime.get("sensors")
    if sensors:
        await sensors.async_reconfigure()

    # Engine reads cfg() at runtime so it usually doesn't need action here.
    # If you add cached things later, add engine.async_reconfigure() here.


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a single plant (one device per config entry)."""
    hass.data.setdefault(DOMAIN, {})

    # Store per-entry runtime so options changes can reconfigure in place
    runtime: dict[str, Any] = {}

    # Engine owns periodic evaluation
    engine = PlantEngine(hass, entry)
    runtime["engine"] = engine

    # Sensor manager will be registered by sensor.py during async_setup_entry
    runtime["sensors"] = None

    hass.data[DOMAIN][entry.entry_id] = runtime

    # Create entities (sensors/numbers/buttons/etc.)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Periodic loop (every 10 minutes)
    engine.start(interval=timedelta(minutes=10))

    # Register update listener (unsub is automatically called on unload)
    entry.async_on_unload(entry.add_update_listener(_entry_updated))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a single plant entry."""
    runtime = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if runtime and runtime.get("engine"):
        runtime["engine"].stop()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)