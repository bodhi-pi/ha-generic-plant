from __future__ import annotations

from datetime import datetime, timezone, timedelta

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DOMAIN,
    CONF_PLANT_NAME,
    OPT_LAST_SEEN,
    OPT_STALE_AFTER_MIN,
    DEFAULT_STALE_AFTER_MIN,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([PlantStaleBinarySensor(hass, entry)], update_before_add=True)


class PlantStaleBinarySensor(BinarySensorEntity):
    """True if last_seen is older than stale_after minutes.

    IMPORTANT: this re-evaluates on a timer so it can flip to stale even if no entity updates occur.
    """

    _attr_has_entity_name = True
    _attr_name = "Stale"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:clock-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_stale"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_PLANT_NAME],
            manufacturer="Generic Plant",
            model="Plant Device",
        )

        self._unsub_timer = None

    async def async_added_to_hass(self) -> None:
        # Re-check staleness periodically so it can transition based on time alone.
        self._unsub_timer = async_track_time_interval(
            self.hass,
            self._tick,
            timedelta(seconds=30),
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

    async def _tick(self, now) -> None:
        # Trigger HA to re-read is_on
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        # Don’t claim we can judge staleness until we’ve seen at least one timestamp
        raw = self.entry.options.get(OPT_LAST_SEEN)
        return bool(raw)

    @property
    def is_on(self) -> bool:
        raw = self.entry.options.get(OPT_LAST_SEEN)
        if not raw:
            # If we have no data yet, we’re “unavailable” (see available()) not “problem”
            return False

        try:
            last_seen = datetime.fromisoformat(raw)
        except Exception:
            return True  # malformed timestamp -> treat as stale

        stale_after = int(self.entry.options.get(OPT_STALE_AFTER_MIN, DEFAULT_STALE_AFTER_MIN))
        return (datetime.now(timezone.utc) - last_seen) > timedelta(minutes=stale_after)