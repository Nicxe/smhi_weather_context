"""Offline sensor entity and description contract tests."""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfSpeed, UnitOfTemperature
import pytest

from custom_components.smhi_weather_context.const import CONF_LOCATION_ID
from custom_components.smhi_weather_context.models import (
    EntryOptions,
    Location,
    WeatherContextData,
)
from custom_components.smhi_weather_context.sensor import (
    CLIMATE_ANOMALY_DESCRIPTION,
    CLIMATE_DESCRIPTIONS,
    DIAGNOSTIC_DESCRIPTIONS,
    PRECIPITATION_DESCRIPTIONS,
    TEMPERATURE_DESCRIPTIONS,
    WIND_DESCRIPTIONS,
    SmhiContextSensor,
    _comparison_description,
    async_setup_entry,
)

pytestmark = pytest.mark.asyncio


def _options(*, name: str = "Test location", station: int = 71420) -> EntryOptions:
    return EntryOptions(
        location=Location(name, 57.70, 11.97),
        temperature_station_id=station,
        wind_station_id=station,
        comparison_years=(1, 10),
        enable_temperature=True,
        enable_wind=False,
        enable_climate=True,
        enable_precipitation=False,
    )


def _entry(
    *,
    location_id: str = "stable-location-id",
    name: str = "Test location",
    station: int = 71420,
    values: dict[str, object] | None = None,
):
    coordinator = SimpleNamespace(
        data=WeatherContextData(values=values or {}), last_update_success=True
    )
    return SimpleNamespace(
        data={CONF_LOCATION_ID: location_id},
        runtime_data=SimpleNamespace(
            coordinator=coordinator, options=_options(name=name, station=station)
        ),
    )


async def test_missing_value_is_unavailable_while_real_zero_remains_valid() -> None:
    """Unknown values must not appear as zero, but an observed zero is legitimate."""
    entry = _entry(values={"temperature_now": None})
    entity = SmhiContextSensor(entry, TEMPERATURE_DESCRIPTIONS[0])

    assert entity.native_value is None
    assert entity.available is False

    entry.runtime_data.coordinator.data.values["temperature_now"] = 0.0
    assert entity.native_value == 0.0
    assert entity.available is True


async def test_unique_id_is_stable_across_rename_and_station_change() -> None:
    """User-editable labels and station choices must not change entity identity."""
    first = SmhiContextSensor(
        _entry(name="Old name", station=71420), TEMPERATURE_DESCRIPTIONS[0]
    )
    second = SmhiContextSensor(
        _entry(name="New name", station=99999), TEMPERATURE_DESCRIPTIONS[0]
    )

    assert first.unique_id == "stable-location-id_temperature_now"
    assert second.unique_id == first.unique_id
    assert first.device_info["identifiers"] == {
        ("smhi_weather_context", "stable-location-id")
    }


async def test_setup_exposes_only_enabled_feature_descriptions() -> None:
    """Entity creation follows feature options without producing hidden wind data."""
    entry = _entry()
    entities: list[SmhiContextSensor] = []

    await async_setup_entry(None, entry, lambda generated: entities.extend(generated))

    keys = {entity.entity_description.key for entity in entities}
    assert {description.key for description in DIAGNOSTIC_DESCRIPTIONS} <= keys
    assert {description.key for description in TEMPERATURE_DESCRIPTIONS} <= keys
    assert {description.key for description in CLIMATE_DESCRIPTIONS} <= keys
    assert CLIMATE_ANOMALY_DESCRIPTION.key in keys
    assert "temperature_same_hour_1_year" in keys
    assert "temperature_today_mean_10_year" in keys
    assert not keys & {description.key for description in WIND_DESCRIPTIONS}
    assert not keys & {description.key for description in PRECIPITATION_DESCRIPTIONS}
    assert len(keys) == len(entities)


async def test_static_entity_descriptions_have_unique_keys_and_expected_units() -> None:
    """The registry contract must remain deterministic and semantically typed."""
    descriptions = (
        *TEMPERATURE_DESCRIPTIONS,
        *CLIMATE_DESCRIPTIONS,
        CLIMATE_ANOMALY_DESCRIPTION,
        *PRECIPITATION_DESCRIPTIONS,
        *WIND_DESCRIPTIONS,
        *DIAGNOSTIC_DESCRIPTIONS,
    )
    keys = [description.key for description in descriptions]

    assert len(keys) == len(set(keys))
    assert all(description.translation_key for description in descriptions)
    assert TEMPERATURE_DESCRIPTIONS[0].device_class is SensorDeviceClass.TEMPERATURE
    assert (
        TEMPERATURE_DESCRIPTIONS[0].native_unit_of_measurement
        == UnitOfTemperature.CELSIUS
    )
    assert TEMPERATURE_DESCRIPTIONS[0].state_class is SensorStateClass.MEASUREMENT
    assert WIND_DESCRIPTIONS[0].device_class is SensorDeviceClass.WIND_SPEED
    assert (
        WIND_DESCRIPTIONS[0].native_unit_of_measurement == UnitOfSpeed.METERS_PER_SECOND
    )


@pytest.mark.parametrize(
    ("prefix", "same_hour", "translation_key", "unit"),
    [
        (
            "temperature_same_hour",
            True,
            "temperature_same_hour_year",
            UnitOfTemperature.CELSIUS,
        ),
        (
            "temperature_today_mean",
            False,
            "temperature_today_mean_year",
            UnitOfTemperature.CELSIUS,
        ),
        (
            "wind_same_hour",
            True,
            "wind_same_hour_year",
            UnitOfSpeed.METERS_PER_SECOND,
        ),
        (
            "wind_today_mean",
            False,
            "wind_today_mean_year",
            UnitOfSpeed.METERS_PER_SECOND,
        ),
    ],
)
async def test_dynamic_description_contract(
    prefix: str, same_hour: bool, translation_key: str, unit: str
) -> None:
    """Comparison sensors retain stable keys, names, units and default visibility."""
    description = _comparison_description(prefix, 10, same_hour)

    assert description.key == f"{prefix}_10_year"
    assert description.data_key == description.key
    assert description.translation_key == translation_key
    assert description.translation_placeholders == {"years": "10"}
    assert description.native_unit_of_measurement == unit
    assert description.state_class is SensorStateClass.MEASUREMENT
    assert description.entity_registry_enabled_default is False
