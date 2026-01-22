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

    Boot-aware behavior:
    - If last_seen is missing OR from before this entity started -> entity is unavailable (not "problem")
    - Once a new reading arrives during this HA runtime -> entity becomes available and evaluates staleness
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

        # Timestamp when this entity started (used to avoid "Problem" immediately after restart)
        self._started_at = datetime.now(timezone.utc)

        self._unsub_timer = None

    async def async_added_to_hass(self) -> None:
        # Re-check periodically so stale state can change based on time alone.
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
        self.async_write_ha_state()

    def _parse_last_seen(self) -> datetime | None:
        raw = self.entry.options.get(OPT_LAST_SEEN)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            return None

    @property
    def available(self) -> bool:
        """Only become available once we have seen a reading during this runtime."""
        last_seen = self._parse_last_seen()
        if last_seen is None:
            return False

        # Only consider valid once updated after we started (prevents startup false "Problem")
        return last_seen >= self._started_at

    @property
    def is_on(self) -> bool:
        """Stale = True when last_seen age exceeds stale_after minutes."""
        last_seen = self._parse_last_seen()
        if last_seen is None:
            return False  # unavailable() covers the "no data" case

        # If last_seen is from before this runtime, don't declare stale yet.
        if last_seen < self._started_at:
            return False

        stale_after = int(self.entry.options.get(OPT_STALE_AFTER_MIN, DEFAULT_STALE_AFTER_MIN))
        return (datetime.now(timezone.utc) - last_seen) > timedelta(minutes=stale_after)