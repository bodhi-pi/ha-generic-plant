from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    CONF_PLANT_NAME,
    PLANT_MODE,
    MODE_AUTO,
    OPT_LAST_WATERED,
)
from .engine import PlantEngine, start_watering_event_spike


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    mode = entry.options.get(PLANT_MODE, MODE_AUTO)

    entities = [
        PlantEvaluateNowButton(hass, entry),
        PlantLogWateringButton(hass, entry),  # all modes
    ]

    if mode == MODE_AUTO:
        entities.append(PlantWaterNowButton(hass, entry))

    async_add_entities(entities, update_before_add=True)


class _BasePlantButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.plant_name = entry.data.get(CONF_PLANT_NAME, "Plant")

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=self.plant_name,
            manufacturer="Generic Plant",
            model="Plant Device",
        )

    def _engine(self) -> PlantEngine | None:
        runtime = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id)
        if isinstance(runtime, PlantEngine):
            return runtime
        if isinstance(runtime, dict):
            engine = runtime.get("engine")
            if isinstance(engine, PlantEngine):
                return engine
        return None


class PlantWaterNowButton(_BasePlantButton):
    """Immediately run the pump once (auto mode only)."""

    _attr_name = "Water Now"
    _attr_icon = "mdi:watering-can"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_water_now"

    async def async_press(self) -> None:
        engine = self._engine()
        if engine is not None:
            await engine.water_now()


class PlantLogWateringButton(_BasePlantButton):
    """Manually log a watering event — stamps last_watered and spikes watering event sensor."""

    _attr_name = "Log Watering"
    _attr_icon = "mdi:clipboard-check-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_log_watering"

    async def async_press(self) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, OPT_LAST_WATERED: now_iso},
        )
        start_watering_event_spike(self.hass, self.entry)


class PlantEvaluateNowButton(_BasePlantButton):
    """Immediately run the engine evaluation loop."""

    _attr_name = "Evaluate Now"
    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_evaluate_now"

    async def async_press(self) -> None:
        engine = self._engine()
        if engine is not None:
            await engine.evaluate_now()
