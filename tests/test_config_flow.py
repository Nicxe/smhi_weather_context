"""Offline QA tests for the SMHI Weather Context config flow."""

from __future__ import annotations

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
    SmhiApiUnavailableError,
    SmhiCoverageError,
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
from custom_components.smhi_weather_context.metobs import MetObsClient
from custom_components.smhi_weather_context.models import Station
from custom_components.smhi_weather_context.pthbv import PthbvClient

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_smhi_network")]

LOCATION_INPUT = {
    CONF_USE_HOME: False,
    CONF_NAME: "Göteborg",
    CONF_LATITUDE: 57.7089,
    CONF_LONGITUDE: 11.9746,
}
FEATURE_INPUT = {
    CONF_ENABLE_TEMPERATURE: True,
    CONF_ENABLE_WIND: True,
    CONF_ENABLE_CLIMATE: True,
    CONF_ENABLE_PRECIPITATION: False,
}
COMPARISON_INPUT = {CONF_COMPARISON_YEARS: ["1", "3", "10"]}


def _schema_keys(result: FlowResult) -> set[str]:
    """Return field names from a flow form schema."""
    return {marker.schema for marker in result["data_schema"].schema}


def _assert_form(result: FlowResult, step_id: str) -> None:
    """Assert a flow result is the expected form."""
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == step_id


async def _start_flow(hass: HomeAssistant) -> FlowResult:
    """Start a user flow and submit its location step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    _assert_form(result, "user")
    assert _schema_keys(result) == {
        CONF_USE_HOME,
        CONF_NAME,
        CONF_LATITUDE,
        CONF_LONGITUDE,
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], LOCATION_INPUT
    )
    _assert_form(result, "content")
    return result


async def _submit_content_and_comparisons(
    hass: HomeAssistant,
    result: FlowResult,
    *,
    features: dict[str, bool] | None = None,
    station_result: list[Station] | None = None,
    station_error: Exception | None = None,
    pthbv_error: Exception | None = None,
) -> tuple[FlowResult, AsyncMock, AsyncMock]:
    """Advance through content/comparison and mock all provider calls."""
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], features or FEATURE_INPUT
    )
    _assert_form(result, "comparisons")
    assert _schema_keys(result) == {CONF_COMPARISON_YEARS}

    metobs = AsyncMock(return_value=station_result)
    pthbv = AsyncMock(return_value={})
    if station_error is not None:
        metobs.side_effect = station_error
    if pthbv_error is not None:
        pthbv.side_effect = pthbv_error

    with (
        patch.object(MetObsClient, "async_stations", metobs),
        patch.object(PthbvClient, "async_daily", pthbv),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], COMPARISON_INPUT
        )
    return result, metobs, pthbv


@pytest.mark.parametrize(
    "error", [SmhiApiUnavailableError("HTTP 503"), SmhiApiConnectionError("offline")]
)
@pytest.mark.parametrize("temperature", [True, False])
async def test_climate_outage_allows_explicit_confirmation(
    hass: HomeAssistant,
    temperature_station: Station,
    error: Exception,
    temperature: bool,
) -> None:
    """Optional climate outages retain climate and never block working stations."""
    result = await _start_flow(hass)
    result, metobs, pthbv = await _submit_content_and_comparisons(
        hass,
        result,
        features={
            **FEATURE_INPUT,
            CONF_ENABLE_WIND: False,
            CONF_ENABLE_TEMPERATURE: temperature,
        },
        station_result=[temperature_station],
        pthbv_error=error,
    )
    _assert_form(result, "stations")
    assert result["errors"] == {}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_TEMPERATURE_STATION: str(temperature_station.station_id)}
        if temperature
        else {},
    )
    _assert_form(result, "confirm_climate_unavailable")
    pthbv.assert_awaited_once()
    assert metobs.await_count == int(temperature)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_ENABLE_CLIMATE] is True
    assert result["options"][CONF_ENABLE_PRECIPITATION] is False


async def test_malformed_climate_response_still_blocks_setup(
    hass: HomeAssistant, temperature_station: Station
) -> None:
    result = await _start_flow(hass)
    result, _, _ = await _submit_content_and_comparisons(
        hass,
        result,
        station_result=[temperature_station],
        pthbv_error=SmhiApiResponseError("invalid JSON"),
    )
    assert result["errors"] == {"base": "invalid_response"}


async def test_user_flow_walks_every_step_and_creates_entry(
    hass: HomeAssistant,
    temperature_station: Station,
    wind_station: Station,
) -> None:
    """Exercise user, content, comparisons, stations and confirm end to end."""
    result = await _start_flow(hass)

    stations_by_parameter = [
        [temperature_station],
        [wind_station],
        [wind_station],
        [wind_station],
    ]
    with (
        patch.object(
            MetObsClient,
            "async_stations",
            AsyncMock(side_effect=stations_by_parameter),
        ) as metobs,
        patch.object(PthbvClient, "async_daily", AsyncMock(return_value={})) as pthbv,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], FEATURE_INPUT
        )
        _assert_form(result, "comparisons")
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], COMPARISON_INPUT
        )

    _assert_form(result, "stations")
    assert _schema_keys(result) == {
        CONF_TEMPERATURE_STATION,
        CONF_WIND_STATION,
    }
    assert result["errors"] == {}
    assert metobs.await_count == 4
    pthbv.assert_awaited_once()

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_TEMPERATURE_STATION: str(temperature_station.station_id),
            CONF_WIND_STATION: str(wind_station.station_id),
        },
    )
    _assert_form(result, "confirm")
    assert result["description_placeholders"] == {
        "location": "Göteborg",
        "temperature_station": temperature_station.name,
        "wind_station": wind_station.name,
    }

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Göteborg"
    assert result["data"][CONF_LOCATION_ID]
    assert result["data"][CONF_TEMPERATURE_STATION] == 71420
    assert result["data"][CONF_TEMPERATURE_STATION_NAME] == "Göteborg A"
    assert result["data"][CONF_WIND_STATION] == 72420
    assert result["data"][CONF_WIND_STATION_NAME] == "Vinga A"
    assert result["options"][CONF_COMPARISON_YEARS] == [1, 3, 10]


@pytest.mark.parametrize(
    ("features", "field", "error"),
    [
        (
            {
                CONF_ENABLE_TEMPERATURE: False,
                CONF_ENABLE_WIND: False,
                CONF_ENABLE_CLIMATE: False,
                CONF_ENABLE_PRECIPITATION: False,
            },
            "base",
            "select_feature",
        ),
        (
            {
                CONF_ENABLE_TEMPERATURE: True,
                CONF_ENABLE_WIND: False,
                CONF_ENABLE_CLIMATE: False,
                CONF_ENABLE_PRECIPITATION: True,
            },
            CONF_ENABLE_PRECIPITATION,
            "precipitation_requires_climate",
        ),
    ],
)
async def test_content_step_rejects_invalid_feature_combinations(
    hass: HomeAssistant,
    features: dict[str, bool],
    field: str,
    error: str,
) -> None:
    """Keep invalid feature combinations on the content step."""
    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], features)

    _assert_form(result, "content")
    assert result["errors"] == {field: error}


async def test_comparisons_step_requires_at_least_one_year(
    hass: HomeAssistant,
) -> None:
    """Reject an empty historical comparison selection."""
    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], FEATURE_INPUT
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_COMPARISON_YEARS: []}
    )

    _assert_form(result, "comparisons")
    assert result["errors"] == {CONF_COMPARISON_YEARS: "select_comparison"}


async def test_duplicate_location_aborts_at_confirmation(
    hass: HomeAssistant,
    smhi_config_entry: MockConfigEntry,
    temperature_station: Station,
) -> None:
    """Do not create a second entry for the same rounded coordinates."""
    smhi_config_entry.add_to_hass(hass)
    result = await _start_flow(hass)
    features = {
        CONF_ENABLE_TEMPERATURE: True,
        CONF_ENABLE_WIND: False,
        CONF_ENABLE_CLIMATE: False,
        CONF_ENABLE_PRECIPITATION: False,
    }
    result, _, _ = await _submit_content_and_comparisons(
        hass,
        result,
        features=features,
        station_result=[temperature_station],
    )
    _assert_form(result, "stations")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_TEMPERATURE_STATION: str(temperature_station.station_id)},
    )
    _assert_form(result, "confirm")

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_connection_error_is_reported_without_network(
    hass: HomeAssistant,
) -> None:
    """Map MetObs connection failures to the stable flow error key."""
    result = await _start_flow(hass)
    features = {
        CONF_ENABLE_TEMPERATURE: True,
        CONF_ENABLE_WIND: False,
        CONF_ENABLE_CLIMATE: False,
        CONF_ENABLE_PRECIPITATION: False,
    }
    result, metobs, _ = await _submit_content_and_comparisons(
        hass,
        result,
        features=features,
        station_error=SmhiApiConnectionError(),
    )

    _assert_form(result, "stations")
    assert result["errors"] == {"base": "cannot_connect"}
    metobs.assert_awaited_once()


async def test_climate_coverage_error_is_reported_without_network(
    hass: HomeAssistant,
) -> None:
    """Map the PTHBV coverage failure to the dedicated flow error."""
    result = await _start_flow(hass)
    features = {
        CONF_ENABLE_TEMPERATURE: False,
        CONF_ENABLE_WIND: False,
        CONF_ENABLE_CLIMATE: True,
        CONF_ENABLE_PRECIPITATION: False,
    }
    result, metobs, pthbv = await _submit_content_and_comparisons(
        hass,
        result,
        features=features,
        station_result=[],
        pthbv_error=SmhiCoverageError(),
    )

    _assert_form(result, "stations")
    assert result["errors"] == {"base": "outside_coverage"}
    metobs.assert_not_awaited()
    pthbv.assert_awaited_once()


@pytest.mark.parametrize(
    ("features", "error"),
    [
        (
            {
                CONF_ENABLE_TEMPERATURE: True,
                CONF_ENABLE_WIND: False,
                CONF_ENABLE_CLIMATE: False,
                CONF_ENABLE_PRECIPITATION: False,
            },
            "no_temperature_station",
        ),
        (
            {
                CONF_ENABLE_TEMPERATURE: False,
                CONF_ENABLE_WIND: True,
                CONF_ENABLE_CLIMATE: False,
                CONF_ENABLE_PRECIPITATION: False,
            },
            "no_wind_station",
        ),
    ],
)
async def test_no_compatible_stations_is_reported(
    hass: HomeAssistant,
    features: dict[str, bool],
    error: str,
) -> None:
    """Keep the station form open when discovery returns no candidates."""
    result = await _start_flow(hass)
    result, _, _ = await _submit_content_and_comparisons(
        hass,
        result,
        features=features,
        station_result=[],
    )

    _assert_form(result, "stations")
    assert result["errors"] == {"base": error}
    assert _schema_keys(result) == set()


async def test_options_flow_updates_options_and_schedules_reload(
    hass: HomeAssistant,
    smhi_config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persist changed options and let OptionsFlowWithReload reload the entry."""
    smhi_config_entry.add_to_hass(hass)
    schedule_reload = AsyncMock()
    monkeypatch.setattr(hass.config_entries, "async_reload", schedule_reload)

    result = await hass.config_entries.options.async_init(smhi_config_entry.entry_id)
    _assert_form(result, "init")
    updated = {
        CONF_ENABLE_TEMPERATURE: True,
        CONF_ENABLE_WIND: True,
        CONF_ENABLE_CLIMATE: True,
        CONF_ENABLE_PRECIPITATION: True,
        CONF_COMPARISON_YEARS: ["2", "5", "10"],
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], updated
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert smhi_config_entry.options == {
        **updated,
        CONF_COMPARISON_YEARS: [2, 5, 10],
    }
    schedule_reload.assert_awaited_once_with(smhi_config_entry.entry_id)


async def test_reconfigure_preserves_location_id_and_reloads(
    hass: HomeAssistant,
    smhi_config_entry: MockConfigEntry,
    temperature_station: Station,
    wind_station: Station,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Change location and stations without replacing the stable device identity."""
    smhi_config_entry.add_to_hass(hass)
    old_location_id = smhi_config_entry.data[CONF_LOCATION_ID]
    reload_entry = AsyncMock()
    monkeypatch.setattr(hass.config_entries, "async_reload", reload_entry)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": smhi_config_entry.entry_id,
        },
    )
    _assert_form(result, "reconfigure")

    updated_location = {
        CONF_USE_HOME: False,
        CONF_NAME: "Sommarstugan",
        CONF_LATITUDE: 58.0001,
        CONF_LONGITUDE: 12.0001,
    }
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], updated_location
    )
    _assert_form(result, "content")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], FEATURE_INPUT
    )
    _assert_form(result, "comparisons")

    stations_by_parameter = [
        [temperature_station],
        [wind_station],
        [wind_station],
        [wind_station],
    ]
    with (
        patch.object(
            MetObsClient,
            "async_stations",
            AsyncMock(side_effect=stations_by_parameter),
        ),
        patch.object(PthbvClient, "async_daily", AsyncMock(return_value={})),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], COMPARISON_INPUT
        )
    _assert_form(result, "stations")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_TEMPERATURE_STATION: str(temperature_station.station_id),
            CONF_WIND_STATION: str(wind_station.station_id),
        },
    )
    _assert_form(result, "confirm")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert smhi_config_entry.data[CONF_LOCATION_ID] == old_location_id
    assert smhi_config_entry.data[CONF_NAME] == "Sommarstugan"
    assert smhi_config_entry.data[CONF_LATITUDE] == 58.0001
    assert smhi_config_entry.data[CONF_LONGITUDE] == 12.0001
    assert smhi_config_entry.unique_id == "58.0001,12.0001"
    assert smhi_config_entry.title == "Sommarstugan"
    reload_entry.assert_awaited_once_with(smhi_config_entry.entry_id)
