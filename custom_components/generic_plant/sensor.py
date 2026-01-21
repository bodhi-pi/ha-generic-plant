from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import PERCENTAGE
from homeassistant.components.mqtt import async_subscribe

from .const import (
    DOMAIN,
    CONF_PLANT_NAME,
    CONF_MOISTURE_ENTITY,
    OPT_LAST_WATERED,
    OPT_LAST_SEEN,
    OPT_HEARTBEAT_TOPIC,
)


@dataclass(frozen=True)
class PlantRuntime:
    plant_name: str
    moisture_entity_id: str


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up plant sensors for a config entry."""
    plant_name: str = entry.data[CONF_PLANT_NAME]
    moisture_entity_id: str = entry.data[CONF_MOISTURE_ENTITY]

    runtime = PlantRuntime(plant_name=plant_name, moisture_entity_id=moisture_entity_id)

    async_add_entities(
        [
            PlantMoistureProxy(hass, entry, runtime),
            PlantLastSeenSensor(hass, entry, runtime),
            PlantLastWateredSensor(hass, entry, runtime),
        ],
        update_before_add=True,
    )


class _BasePlantSensor(SensorEntity):
    """Base entity that attaches to the per-plant device."""

    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, runtime: PlantRuntime) -> None:
        self.hass = hass
        self.entry = entry
        self.runtime = runtime

        # One device per plant (stable device identity per config entry)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=runtime.plant_name,
            manufacturer="Generic Plant",
            model="Plant Device",
        )


class PlantMoistureProxy(_BasePlantSensor):
    """Proxy moisture sensor that belongs to the plant device.

    Mirrors the selected HA sensor entity, but groups it under the plant device.
    """

    _attr_device_class = SensorDeviceClass.MOISTURE
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:water-percent"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, runtime: PlantRuntime) -> None:
        super().__init__(hass, entry, runtime)
        self._attr_name = "Moisture"
        self._attr_unique_id = f"{entry.entry_id}_moisture"

        self._native_value: float | None = None
        self._unsub = None

    async def async_added_to_hass(self) -> None:
        self._sync_from_source()

        # Subscribe to *entity* changes (works for any sensor integration)
        self._unsub = async_track_state_change_event(
            self.hass,
            [self.runtime.moisture_entity_id],
            self._handle_source_event,
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    def _sync_from_source(self) -> None:
        st = self.hass.states.get(self.runtime.moisture_entity_id)
        if st is None:
            self._native_value = None
            return
        try:
            self._native_value = float(st.state)
        except ValueError:
            self._native_value = None

    async def _handle_source_event(self, event) -> None:
        """Update moisture proxy and stamp last_seen when the *entity* changes."""
        self._sync_from_source()

        # This will only fire when HA sees a state-change event for the entity
        now_iso = datetime.now(timezone.utc).isoformat()
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, OPT_LAST_SEEN: now_iso},
        )

        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        return self._native_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"source_entity": self.runtime.moisture_entity_id}


class PlantLastWateredSensor(_BasePlantSensor):
    """Last watered timestamp for the plant (stored in entry.options)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:watering-can"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, runtime: PlantRuntime) -> None:
        super().__init__(hass, entry, runtime)
        self._attr_name = "Last Watered"
        self._attr_unique_id = f"{entry.entry_id}_last_watered"

    @property
    def native_value(self) -> datetime | None:
        raw = self.entry.options.get(OPT_LAST_WATERED)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            return None


class PlantLastSeenSensor(_BasePlantSensor):
    """Last time we received a reading event.

    - Updates on entity change events (generic)
    - If heartbeat_topic is configured, also updates on every MQTT message (works for repeated values)
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-check"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, runtime: PlantRuntime) -> None:
        super().__init__(hass, entry, runtime)
        self._attr_name = "Last Seen"
        self._attr_unique_id = f"{entry.entry_id}_last_seen"
        self._unsub_mqtt = None
        self._last_seen_dt: datetime | None = None

    async def async_added_to_hass(self) -> None:
        # Load persisted value (if any)
        raw = self.entry.options.get(OPT_LAST_SEEN)
        if raw:
            try:
                self._last_seen_dt = datetime.fromisoformat(raw)
            except Exception:
                self._last_seen_dt = None

        # Subscribe to optional MQTT heartbeat topic (if provided)
        topic = (self.entry.options.get(OPT_HEARTBEAT_TOPIC) or "").strip()
        if topic:
            self._unsub_mqtt = await async_subscribe(self.hass, topic, self._on_mqtt)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_mqtt:
            self._unsub_mqtt()
            self._unsub_mqtt = None

    def _touch(self) -> None:
        """Update runtime + persist to options + publish state."""
        self._last_seen_dt = datetime.now(timezone.utc)
        now_iso = self._last_seen_dt.isoformat()

        # Persist so it survives restarts
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, OPT_LAST_SEEN: now_iso},
        )

        # Update entity immediately
        self.async_write_ha_state()

    async def _on_mqtt(self, msg) -> None:
        # Any message counts as fresh, even if payload repeats
        self._touch()

    @property
    def native_value(self) -> datetime | None:
        # Prefer runtime value; fallback to stored option if runtime not set yet
        return self._last_seen_dt