from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_PLANT_NAME, OPT_AUTO_WATER


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([PlantAutoWaterSwitch(entry)])


class PlantAutoWaterSwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_name = "Auto Water"
    _attr_icon = "mdi:water-sync"

    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_auto_water"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_PLANT_NAME],
            manufacturer="Generic Plant",
            model="Plant Device",
        )

    @property
    def is_on(self) -> bool:
        return self.entry.options.get(OPT_AUTO_WATER, False)

    async def async_turn_on(self, **kwargs) -> None:
        self._update(True)

    async def async_turn_off(self, **kwargs) -> None:
        self._update(False)

    def _update(self, value: bool) -> None:
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, OPT_AUTO_WATER: value},
        )
        self.async_write_ha_state()
