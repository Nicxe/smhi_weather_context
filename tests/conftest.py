"""Shared fixtures for SMHI Weather Context tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smhi_weather_context.api import SmhiApiClient
from custom_components.smhi_weather_context.const import (
    CONF_COMPARISON_YEARS,
    CONF_ENABLE_CLIMATE,
    CONF_ENABLE_PRECIPITATION,
    CONF_ENABLE_TEMPERATURE,
    CONF_ENABLE_WIND,
    CONF_LOCATION_ID,
    CONF_NAME,
    CONF_TEMPERATURE_STATION,
    CONF_TEMPERATURE_STATION_NAME,
    CONF_WIND_STATION,
    CONF_WIND_STATION_NAME,
    DOMAIN,
)
from custom_components.smhi_weather_context.metobs import MetObsClient
from custom_components.smhi_weather_context.models import Station


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading the integration from custom_components."""


@pytest.fixture
def no_smhi_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail immediately if a config-flow test reaches the HTTP client."""

    async def _unexpected_request(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Config-flow tests must not access the network")

    monkeypatch.setattr(SmhiApiClient, "async_get_json", _unexpected_request)
    monkeypatch.setattr(SmhiApiClient, "async_get_text", _unexpected_request)

    async def _compatible_station(*args: Any, **kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(MetObsClient, "async_validate_station", _compatible_station)


@pytest.fixture
def temperature_station() -> Station:
    """Return a compatible temperature station."""
    return Station(
        station_id=71420,
        name="Göteborg A",
        latitude=57.7157,
        longitude=11.9924,
        height=5.0,
        active=True,
        from_time=datetime(1961, 1, 1, tzinfo=UTC),
        to_time=datetime(2026, 9, 3, tzinfo=UTC),
        distance_km=1.8,
        has_current=True,
        has_archive=True,
    )


@pytest.fixture
def wind_station() -> Station:
    """Return a compatible station shared by all wind parameters."""
    return Station(
        station_id=72420,
        name="Vinga A",
        latitude=57.632,
        longitude=11.604,
        height=10.0,
        active=True,
        from_time=datetime(1995, 1, 1, tzinfo=UTC),
        to_time=datetime(2026, 9, 3, tzinfo=UTC),
        distance_km=24.6,
        has_current=True,
        has_archive=True,
    )


@pytest.fixture
def smhi_config_entry() -> MockConfigEntry:
    """Return a configured entry suitable for options and reconfigure tests."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        unique_id="57.7089,11.9746",
        data={
            CONF_NAME: "Home",
            "latitude": 57.7089,
            "longitude": 11.9746,
            CONF_LOCATION_ID: "stable-location-id",
            CONF_TEMPERATURE_STATION: 71420,
            CONF_TEMPERATURE_STATION_NAME: "Göteborg A",
            CONF_WIND_STATION: 72420,
            CONF_WIND_STATION_NAME: "Vinga A",
        },
        options={
            CONF_ENABLE_TEMPERATURE: True,
            CONF_ENABLE_WIND: True,
            CONF_ENABLE_CLIMATE: True,
            CONF_ENABLE_PRECIPITATION: False,
            CONF_COMPARISON_YEARS: [1, 2, 3, 10],
        },
        entry_id="smhi-weather-context-test-entry",
        version=1,
        minor_version=1,
    )
