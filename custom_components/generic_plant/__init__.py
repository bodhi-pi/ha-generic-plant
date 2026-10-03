from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, PLANT_MODE, MODE_AUTO, OPT_WATERING_EVENT

from .engine import PlantEngine

PLATFORMS: list[str] = ["sensor", "number", "button", "switch", "binary_sensor"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


@callback
def _get_runtime(hass: HomeAssistant, entry_id: str) -> dict[str, Any] | None:
    return hass.data.get(DOMAIN, {}).get(entry_id)


async def _entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    runtime = _get_runtime(hass, entry.entry_id)
    if not runtime:
        return
    sensors = runtime.get("sensors")
    if sensors:
        await sensors.async_reconfigure()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    # Backfill: existing entries pre-dating plant modes get MODE_AUTO silently
    if PLANT_MODE not in entry.options:
        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, PLANT_MODE: MODE_AUTO},
        )

    runtime: dict[str, Any] = {}
    engine = PlantEngine(hass, entry)
    runtime["engine"] = engine
    runtime["sensors"] = None
    hass.data[DOMAIN][entry.entry_id] = runtime
    
    # Reset any stuck watering event spikes from previous run
    if entry.options.get(OPT_WATERING_EVENT, 0) != 0:
        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, OPT_WATERING_EVENT: 0},
        )


    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    engine.start(interval=timedelta(minutes=10))
    entry.async_on_unload(entry.add_update_listener(_entry_updated))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    runtime = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if runtime and runtime.get("engine"):
        runtime["engine"].stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
