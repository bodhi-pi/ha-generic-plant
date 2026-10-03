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
    PLANT_MODE,
    MODE_MANUAL,
    OPT_LAST_SEEN,
    OPT_STALE_AFTER_MIN,
    DEFAULT_STALE_AFTER_MIN,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    mode = entry.options.get(PLANT_MODE, "auto")

    # Stale sensor only meaningful for sensor-based modes
    if mode == MODE_MANUAL:
        return

    async_add_entities([PlantStaleBinarySensor(hass, entry)], update_before_add=True)


class PlantStaleBinarySensor(BinarySensorEntity):
    """True if last_seen is older than stale_after minutes.

    Boot-aware: unavailable until a fresh reading arrives during this runtime.
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

        self._started_at = datetime.now(timezone.utc)
        self._unsub_timer = None

    async def async_added_to_hass(self) -> None:
        self._unsub_timer = async_track_time_interval(
            self.hass, self._tick, timedelta(seconds=30),
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
        last_seen = self._parse_last_seen()
        if last_seen is None:
            return False
        return last_seen >= self._started_at

    @property
    def is_on(self) -> bool:
        last_seen = self._parse_last_seen()
        if last_seen is None:
            return False
        if last_seen < self._started_at:
            return False
        stale_after = int(self.entry.options.get(OPT_STALE_AFTER_MIN, DEFAULT_STALE_AFTER_MIN))
        return (datetime.now(timezone.utc) - last_seen) > timedelta(minutes=stale_after)
