from __future__ import annotations

import asyncio
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .engine import PlantEngine

PLATFORMS: list[str] = ["sensor", "number", "button", "switch"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    engine = PlantEngine(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = engine

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Start periodic loop (every 10 minutes, same cadence you used before)
    engine.start(interval=timedelta(minutes=10))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    engine: PlantEngine | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if engine:
        engine.stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return unload_ok
