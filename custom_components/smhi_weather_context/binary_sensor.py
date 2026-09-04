"""Binary sensor platform for SMHI Weather Context."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import SmhiWeatherContextEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up diagnostic freshness status."""
    async_add_entities([SmhiDataFreshBinarySensor(entry)])


class SmhiDataFreshBinarySensor(SmhiWeatherContextEntity, BinarySensorEntity):
    """Indicate whether every enabled current SMHI source is fresh."""

    _attr_translation_key = "smhi_data_fresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "smhi_data_fresh")

    @property
    def is_on(self) -> bool:
        """Return freshness."""
        return bool(self.coordinator.data.values.get("smhi_data_fresh"))
