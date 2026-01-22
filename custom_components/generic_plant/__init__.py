from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .engine import PlantEngine

# Platforms we provide for each plant entry
PLATFORMS: list[str] = ["sensor", "number", "button", "switch", "binary_sensor"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up from YAML (not used)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a single plant (one device per config entry)."""
    hass.data.setdefault(DOMAIN, {})

    # Engine owns periodic evaluation (auto-water) and any per-entry runtime state
    engine = PlantEngine(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = engine

    # Create entities (sensors/numbers/buttons/etc.)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Periodic loop (every 10 minutes)
    engine.start(interval=timedelta(minutes=10))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a single plant entry."""
    engine: PlantEngine | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if engine:
        engine.stop()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)