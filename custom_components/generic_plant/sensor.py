from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import PERCENTAGE

from .const import DOMAIN, CONF_PLANT_NAME, CONF_MOISTURE_ENTITY


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
    entity = PlantMoistureProxy(hass, entry, runtime)
    async_add_entities([entity], update_before_add=True)


class PlantMoistureProxy(SensorEntity):
    """Proxy moisture sensor that belongs to the plant device.

    It mirrors the selected moisture sensor entity, but lives under the Generic Plant device.
    """

    _attr_device_class = SensorDeviceClass.MOISTURE
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-percent"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, runtime: PlantRuntime) -> None:
        self.hass = hass
        self.entry = entry
        self.runtime = runtime

        # One device per plant (stable identifier per config entry)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=runtime.plant_name,
            manufacturer="Generic Plant",
            model="Plant Device",
        )

        self._attr_name = f"{runtime.plant_name} Moisture"
        self._attr_unique_id = f"{entry.entry_id}_moisture"

        self._native_value: float | None = None
        self._last_seen: datetime | None = None
        self._unsub = None

    async def async_added_to_hass(self) -> None:
        """Start listening to the source moisture entity."""
        # Initialize once
        self._sync_from_source()

        # Subscribe to source entity changes
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
            self._last_seen = datetime.utcnow()
        except ValueError:
            self._native_value = None

    async def _handle_source_event(self, event) -> None:
        self._sync_from_source()
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        return self._native_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "source_entity": self.runtime.moisture_entity_id,
            "last_seen_utc": self._last_seen.isoformat() if self._last_seen else None,
        }
