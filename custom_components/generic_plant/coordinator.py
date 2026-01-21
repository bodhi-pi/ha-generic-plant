from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .const import CONF_MOISTURE_ENTITY, CONF_PLANT_NAME, CONF_PUMP_SWITCH


@dataclass(frozen=True)
class PlantConfig:
    """Normalized per-plant configuration."""

    plant_name: str
    moisture_entity: str
    pump_switch: str

    @classmethod
    def from_entry(cls, entry: ConfigEntry) -> "PlantConfig":
        return cls(
            plant_name=entry.data[CONF_PLANT_NAME],
            moisture_entity=entry.data[CONF_MOISTURE_ENTITY],
            pump_switch=entry.data[CONF_PUMP_SWITCH],
        )
