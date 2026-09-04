"""Base entity for SMHI Weather Context."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SmhiWeatherContextConfigEntry
from .const import CONF_LOCATION_ID, DOMAIN
from .coordinator import SmhiWeatherContextCoordinator


class SmhiWeatherContextEntity(CoordinatorEntity[SmhiWeatherContextCoordinator]):
    """Base coordinator entity."""

    _attr_has_entity_name = True

    def __init__(self, entry: SmhiWeatherContextConfigEntry, key: str) -> None:
        super().__init__(entry.runtime_data.coordinator)
        self._entry = entry
        self.entity_key = key
        location_id = entry.data[CONF_LOCATION_ID]
        self._attr_unique_id = f"{location_id}_{key}"
        location = entry.runtime_data.options.location
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, location_id)},
            name=location.name,
            manufacturer="SMHI open data",
            model="Weather Context",
            configuration_url="https://www.smhi.se/data",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return compact provenance attributes."""
        return self.coordinator.data.attributes.get(self.entity_key, {})
