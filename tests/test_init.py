"""Offline setup, unload, removal and migration tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import custom_components.smhi_weather_context as integration
from custom_components.smhi_weather_context.const import (
    CONF_COMPARISON_YEARS,
    CONF_ENABLE_CLIMATE,
    CONF_ENABLE_PRECIPITATION,
    CONF_ENABLE_TEMPERATURE,
    CONF_ENABLE_WIND,
    CONF_LOCATION_ID,
    CONF_NAME,
    CONF_TEMPERATURE_STATION,
    CONF_WIND_STATION,
    PLATFORMS,
)

pytestmark = pytest.mark.asyncio


def _entry(*, version: int = 1, minor_version: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="entry-init-qa",
        version=version,
        minor_version=minor_version,
        data={
            CONF_LOCATION_ID: "stable-location-id",
            CONF_NAME: "Test location",
            "latitude": 57.70,
            "longitude": 11.97,
            CONF_TEMPERATURE_STATION: 71420,
            CONF_WIND_STATION: 72420,
        },
        options={
            CONF_COMPARISON_YEARS: [10, 1, 1],
            CONF_ENABLE_TEMPERATURE: True,
            CONF_ENABLE_WIND: False,
            CONF_ENABLE_CLIMATE: True,
            CONF_ENABLE_PRECIPITATION: False,
        },
        runtime_data=None,
    )


async def test_setup_entry_constructs_runtime_and_forwards_platforms() -> None:
    """Setup wires one shared client/coordinator and forwards configured platforms."""
    entry = _entry()
    entry.async_create_background_task = MagicMock(
        side_effect=lambda hass, target, name: target.close()
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock())
    )
    coordinator = SimpleNamespace(
        async_config_entry_first_refresh=AsyncMock(),
        async_request_refresh=AsyncMock(),
        enable_history=MagicMock(),
    )
    api = object()
    metobs = object()
    pthbv = object()
    cache = object()

    with (
        patch.object(integration, "async_get_clientsession", return_value="session"),
        patch.object(integration, "SmhiApiClient", return_value=api),
        patch.object(integration, "MetObsClient", return_value=metobs),
        patch.object(integration, "PthbvClient", return_value=pthbv),
        patch.object(integration, "SourceCache", return_value=cache),
        patch.object(
            integration, "SmhiWeatherContextCoordinator", return_value=coordinator
        ) as coordinator_class,
    ):
        assert await integration.async_setup_entry(hass, entry)

    coordinator.async_config_entry_first_refresh.assert_awaited_once_with()
    coordinator.enable_history.assert_called_once_with()
    entry.async_create_background_task.assert_called_once()
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, PLATFORMS
    )
    coordinator_class.assert_called_once()
    assert entry.runtime_data.api is api
    assert entry.runtime_data.metobs is metobs
    assert entry.runtime_data.pthbv is pthbv
    assert entry.runtime_data.cache is cache
    assert entry.runtime_data.coordinator is coordinator
    assert entry.runtime_data.options.comparison_years == (1, 10)
    assert not entry.runtime_data.options.enable_wind


async def test_unload_entry_returns_platform_unload_result() -> None:
    """Unload delegates to every integration platform."""
    entry = _entry()
    unload = AsyncMock(return_value=True)
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_unload_platforms=unload)
    )

    assert await integration.async_unload_entry(hass, entry)
    unload.assert_awaited_once_with(entry, PLATFORMS)


async def test_remove_entry_deletes_only_its_private_cache() -> None:
    """Entry removal invokes the cache object scoped to the removed entry."""
    entry = _entry()
    hass = SimpleNamespace()
    cache = SimpleNamespace(async_remove=AsyncMock())

    with patch.object(integration, "SourceCache", return_value=cache) as cache_class:
        await integration.async_remove_entry(hass, entry)

    cache_class.assert_called_once_with(hass, "entry-init-qa")
    cache.async_remove.assert_awaited_once_with()


async def test_migration_adds_stable_location_id_without_losing_data() -> None:
    """Legacy entries gain a persistent identity while preserving all settings."""
    entry = _entry(minor_version=0)
    entry.data.pop(CONF_LOCATION_ID)
    original_data = dict(entry.data)
    update_entry = MagicMock()
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=update_entry)
    )

    with patch.object(
        integration, "uuid4", return_value=SimpleNamespace(hex="migrated-location-id")
    ):
        assert await integration.async_migrate_entry(hass, entry)

    update_entry.assert_called_once_with(
        entry,
        data={**original_data, CONF_LOCATION_ID: "migrated-location-id"},
        minor_version=1,
    )


async def test_migration_is_idempotent_and_rejects_unknown_major_version() -> None:
    """Current entries remain untouched and unsupported major versions fail closed."""
    update_entry = MagicMock()
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=update_entry)
    )

    assert await integration.async_migrate_entry(hass, _entry())
    assert not await integration.async_migrate_entry(hass, _entry(version=2))
    update_entry.assert_not_called()
