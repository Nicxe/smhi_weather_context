"""Offline branch-coverage tests for config, platforms, and source parsers."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import math
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult, FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smhi_weather_context.api import (
    SmhiApiConnectionError,
    SmhiApiResponseError,
)
from custom_components.smhi_weather_context.binary_sensor import (
    SmhiDataFreshBinarySensor,
)
from custom_components.smhi_weather_context.binary_sensor import (
    async_setup_entry as async_setup_binary_sensors,
)
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
    CONF_USE_HOME,
    CONF_WIND_STATION,
    CONF_WIND_STATION_NAME,
    DOMAIN,
)
from custom_components.smhi_weather_context.metobs import (
    MetObsClient,
    parse_archive_for_dates,
)
from custom_components.smhi_weather_context.models import (
    EntryOptions,
    Location,
    Station,
    WeatherContextData,
)
from custom_components.smhi_weather_context.pthbv import PthbvClient
from custom_components.smhi_weather_context.sensor import (
    CLIMATE_ANOMALY_DESCRIPTION,
    CLIMATE_DESCRIPTIONS,
    DIAGNOSTIC_DESCRIPTIONS,
    PRECIPITATION_DESCRIPTIONS,
    TEMPERATURE_DESCRIPTIONS,
    WIND_DESCRIPTIONS,
    SmhiContextSensor,
)
from custom_components.smhi_weather_context.sensor import (
    async_setup_entry as async_setup_sensors,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_smhi_network")]

LOCATION = {
    CONF_USE_HOME: False,
    CONF_NAME: "Göteborg",
    CONF_LATITUDE: 57.7089,
    CONF_LONGITUDE: 11.9746,
}
COMPARISONS = {CONF_COMPARISON_YEARS: ["1", "10"]}


def _features(
    *,
    temperature: bool,
    wind: bool,
    climate: bool,
    precipitation: bool = False,
) -> dict[str, bool]:
    """Build complete feature input for config and options flows."""
    return {
        CONF_ENABLE_TEMPERATURE: temperature,
        CONF_ENABLE_WIND: wind,
        CONF_ENABLE_CLIMATE: climate,
        CONF_ENABLE_PRECIPITATION: precipitation,
    }


def _assert_form(result: FlowResult, step_id: str) -> None:
    """Assert a Home Assistant flow result is the requested form."""
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == step_id


async def _flow_to_stations(
    hass: HomeAssistant,
    *,
    features: dict[str, bool],
    station_results: list[list[Station]] | None = None,
    location: dict[str, Any] | None = None,
    station_error: Exception | None = None,
) -> FlowResult:
    """Advance a user flow to station selection with all I/O mocked."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], location or LOCATION
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], features)
    metobs = AsyncMock(side_effect=station_error or station_results or [])
    with (
        patch.object(MetObsClient, "async_stations", metobs),
        patch.object(PthbvClient, "async_daily", AsyncMock(return_value={})),
    ):
        return await hass.config_entries.flow.async_configure(
            result["flow_id"], COMPARISONS
        )


async def test_home_location_and_wind_only_flow_cover_selection_defaults(
    hass: HomeAssistant,
    wind_station: Station,
) -> None:
    """Use HA coordinates and persist explicit empty temperature station data."""
    location = {
        CONF_USE_HOME: True,
        CONF_NAME: " Home ",
        CONF_LATITUDE: 0.0,
        CONF_LONGITUDE: 0.0,
    }
    features = _features(temperature=False, wind=True, climate=False)
    result = await _flow_to_stations(
        hass,
        features=features,
        station_results=[[wind_station], [wind_station], [wind_station]],
        location=location,
    )
    _assert_form(result, "stations")

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WIND_STATION: str(wind_station.station_id)}
    )
    _assert_form(result, "confirm")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_NAME] == "Home"
    assert result["data"][CONF_LATITUDE] == hass.config.latitude
    assert result["data"][CONF_LONGITUDE] == hass.config.longitude
    assert result["data"][CONF_TEMPERATURE_STATION] == 0
    assert result["data"][CONF_TEMPERATURE_STATION_NAME] == ""
    assert result["data"][CONF_WIND_STATION] == wind_station.station_id


async def test_discovery_maps_generic_api_errors(
    hass: HomeAssistant,
) -> None:
    """Expose malformed source responses through a stable form error."""
    result = await _flow_to_stations(
        hass,
        features=_features(temperature=True, wind=False, climate=False),
        station_error=SmhiApiResponseError("malformed"),
    )

    _assert_form(result, "stations")
    assert result["errors"] == {"base": "invalid_response"}


@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        (False, "station_incompatible"),
        (SmhiApiConnectionError(), "cannot_connect"),
        (SmhiApiResponseError("bad periods"), "invalid_response"),
    ],
    ids=["incompatible", "connection", "response"],
)
async def test_station_selection_validation_errors(
    hass: HomeAssistant,
    temperature_station: Station,
    failure: bool | Exception,
    expected_error: str,
) -> None:
    """Keep selection open for incompatible stations and provider failures."""
    result = await _flow_to_stations(
        hass,
        features=_features(temperature=True, wind=False, climate=False),
        station_results=[[temperature_station]],
    )
    _assert_form(result, "stations")
    validate = AsyncMock(
        side_effect=failure if isinstance(failure, Exception) else None,
        return_value=failure if isinstance(failure, bool) else True,
    )
    with patch.object(MetObsClient, "async_validate_station", validate):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_TEMPERATURE_STATION: str(temperature_station.station_id)},
        )

    _assert_form(result, "stations")
    assert result["errors"] == {"base": expected_error}


async def test_reconfigure_falls_back_to_candidates_and_rejects_duplicate(
    hass: HomeAssistant,
    smhi_config_entry: MockConfigEntry,
    temperature_station: Station,
    wind_station: Station,
) -> None:
    """Replace obsolete defaults but never reconfigure onto another entry."""
    smhi_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        smhi_config_entry,
        data={
            **smhi_config_entry.data,
            CONF_TEMPERATURE_STATION: 1,
            CONF_WIND_STATION: 2,
        },
    )
    duplicate = MockConfigEntry(
        domain=DOMAIN,
        title="Duplicate target",
        unique_id="58.0001,12.0001",
        data={
            CONF_NAME: "Duplicate target",
            CONF_LATITUDE: 58.0001,
            CONF_LONGITUDE: 12.0001,
            CONF_LOCATION_ID: "other-location-id",
            CONF_TEMPERATURE_STATION: temperature_station.station_id,
            CONF_TEMPERATURE_STATION_NAME: temperature_station.name,
            CONF_WIND_STATION: wind_station.station_id,
            CONF_WIND_STATION_NAME: wind_station.name,
        },
        options=dict(smhi_config_entry.options),
    )
    duplicate.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": smhi_config_entry.entry_id,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USE_HOME: False,
            CONF_NAME: "Duplicate target",
            CONF_LATITUDE: 58.0001,
            CONF_LONGITUDE: 12.0001,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _features(temperature=True, wind=True, climate=False),
    )
    with patch.object(
        MetObsClient,
        "async_stations",
        AsyncMock(
            side_effect=[
                [temperature_station],
                [wind_station],
                [wind_station],
                [wind_station],
            ]
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], COMPARISONS
        )
    _assert_form(result, "stations")
    defaults = result["data_schema"]({})
    assert defaults == {
        CONF_TEMPERATURE_STATION: str(temperature_station.station_id),
        CONF_WIND_STATION: str(wind_station.station_id),
    }

    result = await hass.config_entries.flow.async_configure(result["flow_id"], defaults)
    _assert_form(result, "confirm")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert smhi_config_entry.unique_id == "57.7089,11.9746"


@pytest.mark.parametrize(
    ("options", "data_update", "field", "error"),
    [
        (
            _features(temperature=False, wind=False, climate=False),
            {},
            "base",
            "select_feature",
        ),
        (
            _features(
                temperature=True,
                wind=False,
                climate=False,
                precipitation=True,
            ),
            {},
            CONF_ENABLE_PRECIPITATION,
            "precipitation_requires_climate",
        ),
        (
            _features(temperature=True, wind=False, climate=False),
            {CONF_TEMPERATURE_STATION: 0},
            "base",
            "reconfigure_required",
        ),
    ],
    ids=["no-features", "precipitation-without-climate", "missing-station"],
)
async def test_options_flow_rejects_invalid_combinations(
    hass: HomeAssistant,
    smhi_config_entry: MockConfigEntry,
    options: dict[str, bool],
    data_update: dict[str, int],
    field: str,
    error: str,
) -> None:
    """Validate option dependencies before scheduling an entry reload."""
    smhi_config_entry.add_to_hass(hass)
    if data_update:
        hass.config_entries.async_update_entry(
            smhi_config_entry, data={**smhi_config_entry.data, **data_update}
        )
    result = await hass.config_entries.options.async_init(smhi_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**options, CONF_COMPARISON_YEARS: ["1"]}
    )

    _assert_form(result, "init")
    assert result["errors"] == {field: error}


def _entry_options(
    *,
    temperature: bool,
    wind: bool,
    climate: bool,
    precipitation: bool,
    comparison_years: tuple[int, ...] = (1, 5),
) -> EntryOptions:
    """Build typed options for direct platform setup."""
    return EntryOptions(
        location=Location("Offline", 57.7, 11.9),
        temperature_station_id=71420,
        wind_station_id=72420,
        comparison_years=comparison_years,
        enable_temperature=temperature,
        enable_wind=wind,
        enable_climate=climate,
        enable_precipitation=precipitation,
    )


def _runtime_entry(
    options: EntryOptions,
    *,
    values: dict[str, Any] | None = None,
    attributes: dict[str, dict[str, Any]] | None = None,
    update_success: bool = True,
) -> SimpleNamespace:
    """Return the smallest coordinator-backed entry accepted by both platforms."""
    coordinator = SimpleNamespace(
        data=WeatherContextData(
            values=values or {},
            attributes=attributes or {},
        ),
        last_update_success=update_success,
    )
    return SimpleNamespace(
        data={CONF_LOCATION_ID: "platform-location"},
        runtime_data=SimpleNamespace(options=options, coordinator=coordinator),
    )


async def test_sensor_platform_handles_all_enabled_and_disabled_descriptions() -> None:
    """Set up every optional sensor and preserve registry default choices."""
    entities: list[SmhiContextSensor] = []
    entry = _runtime_entry(
        _entry_options(
            temperature=True,
            wind=True,
            climate=True,
            precipitation=True,
        )
    )
    await async_setup_sensors(None, entry, lambda items: entities.extend(items))

    by_key = {entity.entity_description.key: entity for entity in entities}
    static_keys = {
        description.key
        for description in (
            *TEMPERATURE_DESCRIPTIONS,
            *WIND_DESCRIPTIONS,
            *CLIMATE_DESCRIPTIONS,
            CLIMATE_ANOMALY_DESCRIPTION,
            *PRECIPITATION_DESCRIPTIONS,
            *DIAGNOSTIC_DESCRIPTIONS,
        )
    }
    assert static_keys <= by_key.keys()
    assert by_key[
        "temperature_same_hour_1_year"
    ].entity_description.entity_registry_enabled_default
    assert not by_key[
        "temperature_same_hour_5_year"
    ].entity_description.entity_registry_enabled_default
    assert by_key[
        "wind_today_mean_1_year"
    ].entity_description.entity_registry_enabled_default
    assert not by_key[
        "wind_today_mean_5_year"
    ].entity_description.entity_registry_enabled_default
    assert not by_key[
        "temperature_historical_max"
    ].entity_description.entity_registry_enabled_default
    assert not by_key[
        "smhi_last_observation"
    ].entity_description.entity_registry_enabled_default

    disabled: list[SmhiContextSensor] = []
    await async_setup_sensors(
        None,
        _runtime_entry(
            _entry_options(
                temperature=False,
                wind=False,
                climate=False,
                precipitation=False,
                comparison_years=(),
            )
        ),
        lambda items: disabled.extend(items),
    )
    assert {item.entity_description.key for item in disabled} == {
        description.key for description in DIAGNOSTIC_DESCRIPTIONS
    }


async def test_climate_without_temperature_and_binary_platform_setup() -> None:
    """Skip temperature anomaly while setting up wind, climate, and freshness."""
    options = _entry_options(
        temperature=False,
        wind=True,
        climate=True,
        precipitation=True,
        comparison_years=(1,),
    )
    entry = _runtime_entry(options, values={"smhi_data_fresh": False})
    sensors: list[SmhiContextSensor] = []
    binaries: list[SmhiDataFreshBinarySensor] = []

    await async_setup_sensors(None, entry, lambda items: sensors.extend(items))
    await async_setup_binary_sensors(None, entry, lambda items: binaries.extend(items))

    keys = {item.entity_description.key for item in sensors}
    assert {description.key for description in WIND_DESCRIPTIONS} <= keys
    assert {description.key for description in CLIMATE_DESCRIPTIONS} <= keys
    assert {description.key for description in PRECIPITATION_DESCRIPTIONS} <= keys
    assert CLIMATE_ANOMALY_DESCRIPTION.key not in keys
    assert len(binaries) == 1
    assert binaries[0].is_on is False
    entry.runtime_data.coordinator.data.values["smhi_data_fresh"] = 1
    assert binaries[0].is_on is True


async def test_sensor_native_value_availability_and_provenance_attributes() -> None:
    """Coerce unsupported values, honor coordinator failure, and expose attributes."""
    unsupported = object()
    entry = _runtime_entry(
        _entry_options(
            temperature=True,
            wind=False,
            climate=False,
            precipitation=False,
        ),
        values={"temperature_now": unsupported},
        attributes={"temperature_now": {"source": "SMHI", "sample_count": 3}},
        update_success=False,
    )
    entity = SmhiContextSensor(entry, TEMPERATURE_DESCRIPTIONS[0])

    assert entity.native_value is unsupported
    assert entity.available is False
    assert entity.extra_state_attributes == {"source": "SMHI", "sample_count": 3}
    entity.entity_key = "missing"
    assert entity.extra_state_attributes == {}


def _daily_payload(start_year: int = 2023, end_year: int = 2023) -> dict[str, Any]:
    """Create a complete PTHBV daily payload for a compact test period."""
    current = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    dates: list[str] = []
    while current <= end:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return {
        "dates": dates,
        "coord_sys_info": {"EPSG": 4326},
        "point_values": [{"t": [1.0] * len(dates)}],
    }


def _mutate_pthbv(payload: dict[str, Any], case: str) -> None:
    """Apply one isolated PTHBV schema violation."""
    dates = payload["dates"]
    point = payload["point_values"][0]
    if case == "dates-not-list":
        payload["dates"] = "2023-01-01"
    elif case == "points-not-list":
        payload["point_values"] = {}
    elif case == "point-count":
        payload["point_values"].append(deepcopy(point))
    elif case == "point-not-object":
        payload["point_values"] = [None]
    elif case == "coord-not-object":
        payload["coord_sys_info"] = "EPSG:4326"
    elif case == "wrong-epsg":
        payload["coord_sys_info"] = {"EPSG": 3006}
    elif case == "bad-date":
        dates[0] = "not-a-date"
    elif case == "empty-dates":
        payload["dates"] = []
        point["t"] = []
    elif case == "duplicate-dates":
        dates[1] = dates[0]
    elif case == "wrong-start":
        dates[0] = "2022-12-31"
    elif case == "wrong-end":
        dates[-1] = "2024-01-01"
    elif case == "date-gap":
        del dates[100]
        del point["t"][100]
    elif case == "missing-values":
        point.pop("t")
    elif case == "values-not-list":
        point["t"] = "1.0"
    elif case == "length-mismatch":
        point["t"].pop()
    elif case == "invalid-value":
        point["t"][0] = {"value": 1}
    elif case == "infinite-value":
        point["t"][0] = math.inf


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("dates-not-list", "structure is invalid"),
        ("points-not-list", "structure is invalid"),
        ("point-count", "structure is invalid"),
        ("point-not-object", "point data is invalid"),
        ("coord-not-object", "coordinate system is invalid"),
        ("wrong-epsg", "coordinate system is invalid"),
        ("bad-date", "dates are invalid"),
        ("empty-dates", "period is incomplete or unordered"),
        ("duplicate-dates", "period is incomplete or unordered"),
        ("wrong-start", "period is incomplete or unordered"),
        ("wrong-end", "period is incomplete or unordered"),
        ("date-gap", "period is incomplete or unordered"),
        ("missing-values", "values do not match dates"),
        ("values-not-list", "values do not match dates"),
        ("length-mismatch", "values do not match dates"),
        ("invalid-value", "contains invalid values"),
        ("infinite-value", "contains invalid values"),
    ],
)
async def test_pthbv_rejects_every_schema_branch(case: str, message: str) -> None:
    """Reject malformed top-level, point, period, and value structures."""
    payload = _daily_payload()
    _mutate_pthbv(payload, case)
    api = SimpleNamespace(async_get_json=AsyncMock(return_value=payload))

    with pytest.raises(SmhiApiResponseError, match=message):
        await PthbvClient(api).async_daily(Location("Offline", 57.7, 11.9), 2023, 2023)


async def test_pthbv_allows_explicit_missing_values() -> None:
    """Treat documented null samples as missing data instead of schema failure."""
    payload = _daily_payload()
    payload["point_values"][0]["t"][0] = None
    api = SimpleNamespace(async_get_json=AsyncMock(return_value=payload))

    result = await PthbvClient(api).async_daily(
        Location("Offline", 57.7, 11.9), 2023, 2023
    )

    assert result["point_values"][0]["t"][0] is None


async def test_metobs_rejects_missing_station_array() -> None:
    """Require the documented station collection before ranking candidates."""
    api = SimpleNamespace(async_get_json=AsyncMock(return_value={"station": {}}))

    with pytest.raises(SmhiApiResponseError, match="station list is missing"):
        await MetObsClient(api).async_stations(1, Location("Offline", 57.7, 11.9), 2000)


async def test_metobs_skips_non_object_latest_values() -> None:
    """Ignore non-object samples while preserving valid observations."""
    api = SimpleNamespace(
        async_get_json=AsyncMock(
            return_value={
                "value": [
                    "invalid",
                    {
                        "date": 1_788_447_600_000,
                        "value": "15.9",
                        "quality": "g",
                    },
                ]
            }
        )
    )

    observations, _ = await MetObsClient(api).async_latest_day(1, 71420)

    assert [(item.value, item.quality) for item in observations] == [(15.9, "G")]


async def test_metobs_archive_parser_skips_every_invalid_row_branch() -> None:
    """Keep only valid matching finite samples from variable MetObs CSV rows."""
    text = "\n".join(
        [
            "Datum;Tid;Lufttemperatur;Kvalitet",
            "short;row",
            "bad-date;00:00:00;1.0;G",
            "2022-09-03;00:00:00;2.0;G",
            "2023-08-03;00:00:00;3.0;G",
            "2023-09-02;00:00:00;4.0;G",
            "2023-09-03;bad-time;5.0;G",
            "2023-09-03;00:00:00;bad-value;G",
            "2023-09-03;01:00:00;NaN;G",
            "2023-09-03;02:00:00;6.0;R",
            "2023-09-03;03:00:00;7.0;Y",
        ]
    )

    result = parse_archive_for_dates(text, month=9, day=3, years={2023})

    assert [(item.time, item.value, item.quality) for item in result] == [
        (datetime(2023, 9, 3, 3, tzinfo=UTC), 7.0, "Y")
    ]
