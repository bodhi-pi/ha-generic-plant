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
    OPT_PUMP_DURATION_S,
    OPT_LAST_WATERED,
    DEFAULT_PUMP_DURATION_S,
    OPT_NOTIFY_SERVICE,
    OPT_NOTIFY_ON_WATER,
)
from .engine import PlantEngine

from .notify_util import send_notify


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [
            PlantWaterNowButton(hass, entry),
            PlantEvaluateNowButton(hass, entry),
        ],
        update_before_add=True,
    )


class _BasePlantButton(ButtonEntity):
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


class PlantWaterNowButton(_BasePlantButton):
    """Manual watering trigger (always runs pump for duration; confirms ON before stamping last_watered)."""

    _attr_name = "Water Now"
    _attr_icon = "mdi:watering-can"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self.pump_switch = entry.data[CONF_PUMP_SWITCH]
        self._attr_unique_id = f"{entry.entry_id}_water_now"

    async def async_press(self) -> None:
        duration_s = int(self.entry.options.get(OPT_PUMP_DURATION_S, DEFAULT_PUMP_DURATION_S))

        # 1) Turn pump on
        await self.hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": self.pump_switch},
            blocking=True,
        )

        # 2) Confirm ON (up to 5s)
        confirmed = await self._wait_for_state(self.pump_switch, "on", timeout_s=5)

        # 3) If confirmed, record last watered
        if confirmed:
            now_iso = datetime.now(timezone.utc).isoformat()
            self.hass.config_entries.async_update_entry(
                self.entry,
                options={**self.entry.options, OPT_LAST_WATERED: now_iso},
            )

            await send_notify(
                self.hass,
                self.entry,
                title=f"🌱 {self.plant_name} watered",
                message=f"Manual watering ran for {duration_s}s.",
                option_notify_service_key=OPT_NOTIFY_SERVICE,
                option_notify_enabled_key=OPT_NOTIFY_ON_WATER,
            )


        # 4) Run for duration, then OFF
        await asyncio.sleep(max(1, int(duration_s)))

        await self.hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": self.pump_switch},
            blocking=True,
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


class PlantEvaluateNowButton(_BasePlantButton):
    """Runs the engine evaluation immediately (no waiting for the timer)."""

    _attr_name = "Evaluate Now"
    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_evaluate_now"

    async def async_press(self) -> None:
        # Engine is stored in hass.data by __init__.py
        engine = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id)

        if isinstance(engine, PlantEngine):
            await engine.evaluate_and_water()
        else:
            # If engine isn't found (shouldn't happen), do nothing gracefully.
            return