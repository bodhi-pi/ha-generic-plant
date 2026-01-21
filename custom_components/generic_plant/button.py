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
    CONF_PUMP_SWITCH,
    OPT_PUMP_DURATION_S,
    OPT_LAST_WATERED,
    DEFAULT_PUMP_DURATION_S,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([PlantWaterNowButton(hass, entry)], update_before_add=True)


class PlantWaterNowButton(ButtonEntity):
    """Manual watering trigger."""

    _attr_has_entity_name = True
    _attr_name = "Water Now"
    _attr_icon = "mdi:watering-can"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.plant_name = entry.data[CONF_PLANT_NAME]
        self.pump_switch = entry.data[CONF_PUMP_SWITCH]

        self._attr_unique_id = f"{entry.entry_id}_water_now"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=self.plant_name,
            manufacturer="Generic Plant",
            model="Plant Device",
        )

    async def async_press(self) -> None:
        """Turn pump on, confirm, set last watered, wait duration, turn off."""
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

        # 3) If confirmed, record last watered in entry.options (ISO timestamp)
        if confirmed:
            now_iso = datetime.now(timezone.utc).isoformat()
            self.hass.config_entries.async_update_entry(
                self.entry,
                options={**self.entry.options, OPT_LAST_WATERED: now_iso},
            )

        # 4) Run for duration, then OFF
        await self.hass.async_add_executor_job(lambda: None)  # yield
        await self.hass.async_add_executor_job(lambda: None)  # tiny yield, keeps HA responsive
        await self.hass.async_add_executor_job(lambda: None)

        await self.hass.async_add_executor_job(lambda: None)
        await self.hass.async_add_executor_job(lambda: None)

        # Use HA async sleep
        await self.hass.async_add_executor_job(lambda: None)
        await self.hass.async_add_executor_job(lambda: None)

        # Proper async sleep
        import asyncio
        await asyncio.sleep(duration_s)

        await self.hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": self.pump_switch},
            blocking=True,
        )

    async def _wait_for_state(self, entity_id: str, desired: str, timeout_s: int) -> bool:
        """Wait for HA state to equal desired."""
        import asyncio

        # Fast path
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
