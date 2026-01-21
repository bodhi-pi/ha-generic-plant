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
    OPT_HEARTBEAT_TOPIC,
    OPT_LAST_SEEN,
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
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, runtime: PlantRuntime) -> None:
        self.hass = hass
        self.entry = entry
        self.runtime = runtime

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=runtime.plant_name,
            manufacturer="Generic Plant",
            model="Plant Device",
        )


class PlantMoistureProxy(_BasePlantSensor):
    """Proxy moisture sensor that belongs to the plant device."""

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
        # Mirror the moisture value
        self._sync_from_source()

        # Update last_seen when the entity changes (works for non-MQTT sensors too)
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
    """Last time we received a reading event (entity change or MQTT heartbeat)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-check"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, runtime: PlantRuntime) -> None:
        super().__init__(hass, entry, runtime)
        self._attr_name = "Last Seen"
        self._attr_unique_id = f"{entry.entry_id}_last_seen"
        self._unsub_mqtt = None

    async def async_added_to_hass(self) -> None:
        # Subscribe to optional heartbeat topic (if provided)
        topic = (self.entry.options.get(OPT_HEARTBEAT_TOPIC) or "").strip()
        if topic:
            self._unsub_mqtt = await async_subscribe(self.hass, topic, self._on_mqtt)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_mqtt:
            self._unsub_mqtt()
            self._unsub_mqtt = None

    def _touch(self) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, OPT_LAST_SEEN: now_iso},
        )
        self.async_write_ha_state()

    async def _on_mqtt(self, msg) -> None:
        # Any message counts as “fresh” regardless of payload repeating
        self._touch()

    @property
    def native_value(self) -> datetime | None:
        raw = self.entry.options.get(OPT_LAST_SEEN)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            return None
