from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import PERCENTAGE

from .const import DOMAIN, CONF_PLANT_NAME, OPT_THRESHOLD, DEFAULT_THRESHOLD


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([PlantThresholdNumber(hass, entry)], update_before_add=True)


class PlantThresholdNumber(NumberEntity):
    """Threshold (%) for the plant."""

    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:water-percent"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.plant_name = entry.data[CONF_PLANT_NAME]

        # Attach to the same "one device per plant" identity
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=self.plant_name,
            manufacturer="Generic Plant",
            model="Plant Device",
        )

        self._attr_name = f"{self.plant_name} Threshold"
        self._attr_unique_id = f"{entry.entry_id}_threshold"

    @property
    def native_value(self) -> float:
        return float(self.entry.options.get(OPT_THRESHOLD, DEFAULT_THRESHOLD))

    async def async_set_native_value(self, value: float) -> None:
        # Persist to the config entry options (no helpers needed)
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, OPT_THRESHOLD: float(value)},
        )
        self.async_write_ha_state()
