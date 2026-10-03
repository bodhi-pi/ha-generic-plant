from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    CONF_PLANT_NAME,
    CONF_PUMP_SWITCH,
    PLANT_MODE,
    MODE_AUTO,
    OPT_PUMP_DURATION_S,
    DEFAULT_PUMP_DURATION_S,
    OPT_LAST_WATERED,
    OPT_WATERING_EVENT,
)
from .engine import PlantEngine
from .util import cfg


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

    async def _wait_for_state(self, entity_id: str, desired: str, timeout_s: int) -> bool:
        st = self.hass.states.get(entity_id)
        if st and st.state == desired:
            return True
        end = self.hass.loop.time() + timeout_s
        while self.hass.loop.time() < end:
            await asyncio.sleep(0.2)
            st = self.hass.states.get(entity_id)
            if st and st.state == desired:
                return True
        return False

    async def _spike_watering_event(self) -> None:
        """Write 100 then 0 with a short delay so recorder captures both states."""
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, OPT_WATERING_EVENT: 100},
        )
        await asyncio.sleep(5400)  # 90 minutes — ensures capture at 2 points/hour sampling
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, OPT_WATERING_EVENT: 0},
        )


class PlantWaterNowButton(_BasePlantButton):
    """Immediately run the pump once (auto mode only)."""

    _attr_name = "Water Now"
    _attr_icon = "mdi:watering-can"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_water_now"

    async def async_press(self) -> None:
        pump_switch = cfg(self.entry, CONF_PUMP_SWITCH)
        if not pump_switch:
            return

        duration_s = int(self.entry.options.get(OPT_PUMP_DURATION_S, DEFAULT_PUMP_DURATION_S))

        try:
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": pump_switch}, blocking=True,
            )

            confirmed = await self._wait_for_state(pump_switch, "on", timeout_s=5)

            if confirmed:
                now_iso = datetime.now(timezone.utc).isoformat()
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    options={**self.entry.options, OPT_LAST_WATERED: now_iso},
                )
                await self._spike_watering_event()

            await asyncio.sleep(max(1, int(duration_s)))

        finally:
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": pump_switch}, blocking=True,
            )


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
        await self._spike_watering_event()


class PlantEvaluateNowButton(_BasePlantButton):
    """Immediately run the engine evaluation loop."""

    _attr_name = "Evaluate Now"
    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_evaluate_now"

    async def async_press(self) -> None:
        runtime = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id)

        if isinstance(runtime, PlantEngine):
            await runtime.evaluate_and_water()
            return

        if isinstance(runtime, dict):
            engine = runtime.get("engine")
            if isinstance(engine, PlantEngine):
                await engine.evaluate_and_water()
