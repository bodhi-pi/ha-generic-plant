from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
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
    PLANT_MODE,
    MODE_AUTO,
    MODE_SENSOR,
    MODE_MANUAL,
    OPT_LAST_WATERED,
    OPT_LAST_SEEN,
    OPT_HEARTBEAT_TOPIC,
    OPT_LAST_STALE_NOTIFY,
    OPT_LAST_EVALUATED,
    OPT_LAST_DECISION,
    OPT_WATERING_EVENT,
    OPT_LAST_RESPONSE,
)

from .util import cfg


@dataclass
class PlantRuntime:
    plant_name: str
    moisture_entity_id: str


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    mode = entry.options.get(PLANT_MODE, MODE_AUTO)
    plant_name: str = entry.data[CONF_PLANT_NAME]

    entities = [
        PlantLastWateredSensor(hass, entry),
        PlantLastEvaluatedSensor(hass, entry),
        PlantLastDecisionSensor(hass, entry),
        PlantWateringEventSensor(hass, entry),  # NEW
    ]

    if mode in (MODE_AUTO, MODE_SENSOR):
        moisture_entity_id = cfg(entry, CONF_MOISTURE_ENTITY)
        runtime = PlantRuntime(plant_name=plant_name, moisture_entity_id=moisture_entity_id)

        moisture = PlantMoistureProxy(hass, entry, runtime)
        last_seen = PlantLastSeenSensor(hass, entry, runtime)

        entities += [moisture, last_seen]

        if mode == MODE_AUTO:
            entities.append(PlantLastWateringResultSensor(hass, entry))

        # Register sensor manager for reconfiguration on options changes
        runtime_dict = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if runtime_dict is not None:
            runtime_dict["sensors"] = PlantSensorManager(moisture, last_seen)
    else:
        # Manual mode: no moisture sensor, no reconfiguration needed
        runtime_dict = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if runtime_dict is not None:
            runtime_dict["sensors"] = None

    async_add_entities(entities, update_before_add=True)


class PlantSensorManager:
    def __init__(self, moisture: "PlantMoistureProxy", last_seen: "PlantLastSeenSensor") -> None:
        self.moisture = moisture
        self.last_seen = last_seen

    async def async_reconfigure(self) -> None:
        await self.moisture.async_rebind_source()
        await self.last_seen.async_rebind_heartbeat()


class _BasePlantSensor(SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, runtime: PlantRuntime | None = None) -> None:
        self.hass = hass
        self.entry = entry
        self.runtime = runtime

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_PLANT_NAME],
            manufacturer="Generic Plant",
            model="Plant Device",
        )


class PlantMoistureProxy(_BasePlantSensor):
    _attr_device_class = SensorDeviceClass.MOISTURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:water-percent"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, runtime: PlantRuntime) -> None:
        super().__init__(hass, entry, runtime)
        self._attr_name = "Moisture"
        self._attr_unique_id = f"{entry.entry_id}_moisture"
        self._native_value: float | None = None
        self._unsub_state = None
        self._source_entity_id = runtime.moisture_entity_id

    async def async_added_to_hass(self) -> None:
        await self.async_rebind_source(initial=True)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None

    async def async_rebind_source(self, *, initial: bool = False) -> None:
        new_source = cfg(self.entry, CONF_MOISTURE_ENTITY)
        if not new_source:
            return
        if (not initial) and new_source == self._source_entity_id:
            return
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        self._source_entity_id = new_source
        self.runtime.moisture_entity_id = new_source
        self._unsub_state = async_track_state_change_event(
            self.hass, [self._source_entity_id], self._handle_source_event,
        )
        self._sync_from_source()
        self.async_write_ha_state()

    def _sync_from_source(self) -> None:
        st = self.hass.states.get(self._source_entity_id)
        if st is None:
            self._native_value = None
            return
        try:
            self._native_value = float(st.state)
        except ValueError:
            self._native_value = None

    async def _handle_source_event(self, event) -> None:
        self._sync_from_source()
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
        return {"source_entity": self._source_entity_id}


class PlantLastSeenSensor(_BasePlantSensor):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-check"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, runtime: PlantRuntime) -> None:
        super().__init__(hass, entry, runtime)
        self._attr_name = "Last Seen"
        self._attr_unique_id = f"{entry.entry_id}_last_seen"
        self._unsub_mqtt = None
        self._topic: str = ""
        self._last_seen_dt: datetime | None = None

    async def async_added_to_hass(self) -> None:
        raw = self.entry.options.get(OPT_LAST_SEEN)
        if raw:
            try:
                self._last_seen_dt = datetime.fromisoformat(raw)
            except Exception:
                self._last_seen_dt = None
        await self.async_rebind_heartbeat(initial=True)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_mqtt:
            self._unsub_mqtt()
            self._unsub_mqtt = None

    async def async_rebind_heartbeat(self, *, initial: bool = False) -> None:
        new_topic = (self.entry.options.get(OPT_HEARTBEAT_TOPIC) or "").strip()
        if (not initial) and new_topic == self._topic:
            return
        if self._unsub_mqtt:
            self._unsub_mqtt()
            self._unsub_mqtt = None
        self._topic = new_topic
        if self._topic:
            self._unsub_mqtt = await async_subscribe(self.hass, self._topic, self._on_mqtt)

    def _touch(self) -> None:
        self._last_seen_dt = datetime.now(timezone.utc)
        now_iso = self._last_seen_dt.isoformat()
        new_options = {**self.entry.options, OPT_LAST_SEEN: now_iso}
        new_options.pop(OPT_LAST_STALE_NOTIFY, None)
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)
        self.async_write_ha_state()

    async def _on_mqtt(self, msg) -> None:
        self._touch()

    @property
    def native_value(self) -> datetime | None:
        return self._last_seen_dt


class PlantLastWateredSensor(_BasePlantSensor):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:watering-can"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
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


class PlantLastEvaluatedSensor(_BasePlantSensor):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_name = "Last Evaluated"
        self._attr_unique_id = f"{entry.entry_id}_last_evaluated"

    @property
    def native_value(self) -> datetime | None:
        raw = self.entry.options.get(OPT_LAST_EVALUATED)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            return None


class PlantLastDecisionSensor(_BasePlantSensor):
    _attr_icon = "mdi:information-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_name = "Last Decision"
        self._attr_unique_id = f"{entry.entry_id}_last_decision"

    @property
    def native_value(self) -> str | None:
        raw = self.entry.options.get(OPT_LAST_DECISION)
        return str(raw) if raw else None



class PlantWateringEventSensor(_BasePlantSensor):
    """Spikes to 100 when watering occurs then returns to 0. Renders as vertical line on graph."""

    _attr_icon = "mdi:water-plus"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_name = "Watering Event"
        self._attr_unique_id = f"{entry.entry_id}_watering_event"

    @property
    def native_value(self) -> float:
        return float(self.entry.options.get(OPT_WATERING_EVENT, 0))


class PlantLastWateringResultSensor(_BasePlantSensor):
    """Did the most recent checked pump run raise moisture? took / no_response / unknown."""

    _attr_icon = "mdi:water-check-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_name = "Last Watering Result"
        self._attr_unique_id = f"{entry.entry_id}_last_watering_result"

    @property
    def native_value(self) -> str | None:
        last = self.entry.options.get(OPT_LAST_RESPONSE)
        return last.get("result") if isinstance(last, dict) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self.entry.options.get(OPT_LAST_RESPONSE)
        return dict(last) if isinstance(last, dict) else {}
