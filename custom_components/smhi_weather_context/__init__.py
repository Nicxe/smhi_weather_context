"""SMHI Weather Context integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .api import SmhiApiClient
from .const import (
    CONF_COMPARISON_YEARS,
    CONF_ENABLE_CLIMATE,
    CONF_ENABLE_PRECIPITATION,
    CONF_ENABLE_TEMPERATURE,
    CONF_ENABLE_WIND,
    CONF_LOCATION_ID,
    CONF_NAME,
    CONF_TEMPERATURE_STATION,
    CONF_TEMPERATURE_STATION_DISTANCE,
    CONF_TEMPERATURE_STATION_NAME,
    CONF_WIND_STATION,
    CONF_WIND_STATION_DISTANCE,
    CONF_WIND_STATION_NAME,
    DEFAULT_COMPARISON_YEARS,
    DEFAULT_NAME,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import SmhiWeatherContextCoordinator
from .metobs import MetObsClient
from .models import EntryOptions, Location
from .pthbv import PthbvClient
from .storage import SourceCache

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(slots=True)
class SmhiWeatherContextRuntimeData:
    """Runtime data for one config entry."""

    api: SmhiApiClient
    metobs: MetObsClient
    pthbv: PthbvClient
    cache: SourceCache
    coordinator: SmhiWeatherContextCoordinator
    options: EntryOptions


if TYPE_CHECKING:
    type SmhiWeatherContextConfigEntry = ConfigEntry[SmhiWeatherContextRuntimeData]
else:
    SmhiWeatherContextConfigEntry = ConfigEntry


def options_from_entry(entry: ConfigEntry) -> EntryOptions:
    """Normalize immutable entry data and user-editable options."""
    values = {**entry.data, **entry.options}
    return EntryOptions(
        location=Location(
            name=str(values.get(CONF_NAME, DEFAULT_NAME)),
            latitude=float(values[CONF_LATITUDE]),
            longitude=float(values[CONF_LONGITUDE]),
        ),
        temperature_station_id=int(values.get(CONF_TEMPERATURE_STATION, 0)),
        wind_station_id=int(values.get(CONF_WIND_STATION, 0)),
        comparison_years=tuple(
            sorted(
                {
                    int(value)
                    for value in values.get(
                        CONF_COMPARISON_YEARS, DEFAULT_COMPARISON_YEARS
                    )
                }
            )
        ),
        enable_temperature=bool(values.get(CONF_ENABLE_TEMPERATURE, True)),
        enable_wind=bool(values.get(CONF_ENABLE_WIND, True)),
        enable_climate=bool(values.get(CONF_ENABLE_CLIMATE, True)),
        enable_precipitation=bool(values.get(CONF_ENABLE_PRECIPITATION, False)),
        temperature_station_name=str(values.get(CONF_TEMPERATURE_STATION_NAME, "")),
        wind_station_name=str(values.get(CONF_WIND_STATION_NAME, "")),
        temperature_station_distance_km=(
            float(values[CONF_TEMPERATURE_STATION_DISTANCE])
            if values.get(CONF_TEMPERATURE_STATION_DISTANCE) is not None
            else None
        ),
        wind_station_distance_km=(
            float(values[CONF_WIND_STATION_DISTANCE])
            if values.get(CONF_WIND_STATION_DISTANCE) is not None
            else None
        ),
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: SmhiWeatherContextConfigEntry
) -> bool:
    """Set up SMHI Weather Context from a config entry."""
    options = options_from_entry(entry)
    api = SmhiApiClient(async_get_clientsession(hass))
    metobs = MetObsClient(api)
    pthbv = PthbvClient(api)
    cache = SourceCache(hass, entry.entry_id)
    coordinator = SmhiWeatherContextCoordinator(
        hass,
        config_entry=entry,
        options=options,
        metobs=metobs,
        pthbv=pthbv,
        cache=cache,
        history_enabled=False,
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = SmhiWeatherContextRuntimeData(
        api=api,
        metobs=metobs,
        pthbv=pthbv,
        cache=cache,
        coordinator=coordinator,
        options=options,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.enable_history()
    entry.async_create_background_task(
        hass,
        coordinator.async_request_refresh(),
        f"{DOMAIN} history initialization",
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SmhiWeatherContextConfigEntry
) -> bool:
    """Unload an entry and all platforms."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: SmhiWeatherContextConfigEntry
) -> None:
    """Remove only the deleted entry's private source cache."""
    cache = SourceCache(hass, entry.entry_id)
    await cache.async_remove()


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Add stable identity to entries created before schema minor version 1."""
    if entry.version != 1:
        return False
    if entry.minor_version < 1:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_LOCATION_ID: uuid4().hex},
            minor_version=1,
        )
    return True
