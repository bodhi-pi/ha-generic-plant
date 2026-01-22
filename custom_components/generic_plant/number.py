from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import PERCENTAGE

from .const import (
    DOMAIN,
    CONF_PLANT_NAME,
    OPT_THRESHOLD,
    OPT_PUMP_DURATION_S,
    OPT_COOLDOWN_MIN,
    DEFAULT_THRESHOLD,
    DEFAULT_PUMP_DURATION_S,
    DEFAULT_COOLDOWN_MIN,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [
            PlantThresholdNumber(hass, entry),
            PlantPumpDurationNumber(hass, entry),
            PlantCooldownNumber(hass, entry),
            PlantStaleAfterNumber(hass, entry),   # <-- add this
        ],
        update_before_add=True,
    )


class _BasePlantNumber(NumberEntity):
    """Base class for per-plant number entities stored in entry.options."""

    _attr_mode = NumberMode.SLIDER
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.plant_name = entry.data[CONF_PLANT_NAME]

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=self.plant_name,
            manufacturer="Generic Plant",
            model="Plant Device",
        )

    def _get_opt(self, key: str, default: float) -> float:
        return float(self.entry.options.get(key, default))

    async def _set_opt(self, key: str, value: float) -> None:
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, key: float(value)},
        )
        self.async_write_ha_state()


class PlantThresholdNumber(_BasePlantNumber):
    _attr_name = "Moisture Threshold"
    _attr_icon = "mdi:water-percent"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_threshold"

    @property
    def native_value(self) -> float:
        return self._get_opt(OPT_THRESHOLD, DEFAULT_THRESHOLD)

    async def async_set_native_value(self, value: float) -> None:
        await self._set_opt(OPT_THRESHOLD, value)


class PlantPumpDurationNumber(_BasePlantNumber):
    _attr_name = "Pump Duration"
    _attr_icon = "mdi:timer-outline"
    _attr_native_unit_of_measurement = "s"
    _attr_native_min_value = 1.0
    _attr_native_max_value = 120.0
    _attr_native_step = 1.0

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_pump_duration_s"

    @property
    def native_value(self) -> float:
        return self._get_opt(OPT_PUMP_DURATION_S, DEFAULT_PUMP_DURATION_S)

    async def async_set_native_value(self, value: float) -> None:
        await self._set_opt(OPT_PUMP_DURATION_S, value)


class PlantCooldownNumber(_BasePlantNumber):
    _attr_name = "Cooldown"
    _attr_icon = "mdi:coolant-temperature"
    _attr_native_unit_of_measurement = "min"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 1440.0
    _attr_native_step = 5.0

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_cooldown_min"

    @property
    def native_value(self) -> float:
        return self._get_opt(OPT_COOLDOWN_MIN, DEFAULT_COOLDOWN_MIN)

    async def async_set_native_value(self, value: float) -> None:
        await self._set_opt(OPT_COOLDOWN_MIN, value)

class PlantStaleAfterNumber(_BasePlantNumber):
    _attr_name = "Stale After"
    _attr_icon = "mdi:timer-alert"
    _attr_native_unit_of_measurement = "min"
    _attr_native_min_value = 1.0
    _attr_native_max_value = 1440.0
    _attr_native_step = 5.0

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_stale_after_min"

    @property
    def native_value(self) -> float:
        return self._get_opt(OPT_STALE_AFTER_MIN, DEFAULT_STALE_AFTER_MIN)

    async def async_set_native_value(self, value: float) -> None:
        await self._set_opt(OPT_STALE_AFTER_MIN, value)