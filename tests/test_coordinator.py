"""Offline runtime tests for the SMHI Weather Context coordinator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from test_pthbv import complete_pthbv

from custom_components.smhi_weather_context.api import (
    SmhiApiError,
    SmhiApiUnavailableError,
)
from custom_components.smhi_weather_context.calculations import completed_local_hour
from custom_components.smhi_weather_context.const import (
    PARAM_TEMPERATURE,
    PARAM_WIND_DIRECTION,
    PARAM_WIND_GUST,
    PARAM_WIND_SPEED,
)
from custom_components.smhi_weather_context.coordinator import (
    SmhiWeatherContextCoordinator,
)
from custom_components.smhi_weather_context.models import (
    EntryOptions,
    Location,
    Observation,
)
from custom_components.smhi_weather_context.storage import CacheRecord

pytestmark = pytest.mark.asyncio


class _Hass:
    """Minimal Home Assistant executor facade."""

    async def async_add_executor_job(self, target, *args):
        return target(*args)


class _Entry:
    """Minimal config entry accepted by DataUpdateCoordinator."""

    entry_id = "entry-runtime-qa"

    def __init__(self) -> None:
        self.unload_callbacks: list[object] = []

    def async_on_unload(self, callback) -> None:
        self.unload_callbacks.append(callback)


def _options(
    *,
    temperature: bool = True,
    wind: bool = False,
    climate: bool = False,
    precipitation: bool = False,
) -> EntryOptions:
    return EntryOptions(
        location=Location("Test location", 57.70, 11.97),
        temperature_station_id=71420,
        wind_station_id=72420,
        comparison_years=(1, 2, 3, 10),
        enable_temperature=temperature,
        enable_wind=wind,
        enable_climate=climate,
        enable_precipitation=precipitation,
    )


def _coordinator(
    *, options: EntryOptions
) -> tuple[
    SmhiWeatherContextCoordinator,
    SimpleNamespace,
    SimpleNamespace,
    SimpleNamespace,
]:
    metobs = SimpleNamespace(
        async_latest_day=AsyncMock(),
        async_validate_station=AsyncMock(return_value=True),
        async_corrected_archive=AsyncMock(),
    )
    pthbv = SimpleNamespace(async_daily=AsyncMock())
    cache = SimpleNamespace(async_get=AsyncMock(), async_set=AsyncMock())
    coordinator = SmhiWeatherContextCoordinator(
        _Hass(),
        config_entry=_Entry(),
        options=options,
        metobs=metobs,
        pthbv=pthbv,
        cache=cache,
    )
    return coordinator, metobs, pthbv, cache


def _current_observation(value: float, *, age: timedelta = timedelta()) -> Observation:
    target = completed_local_hour(datetime.now(UTC))
    return Observation(target.astimezone(UTC) + timedelta(minutes=30) - age, value)


def _skip_history_refresh(coordinator: SmhiWeatherContextCoordinator) -> None:
    coordinator._history_date = completed_local_hour(datetime.now(UTC)).date()


async def test_climate_outage_preserves_temperature_and_recovers_on_refresh() -> None:
    """A deferred climate source retries without reconfiguring or hiding observations."""
    coordinator, metobs, pthbv, cache = _coordinator(options=_options(climate=True))
    coordinator.enable_history()
    cache.async_get.return_value = None
    metobs.async_latest_day.return_value = ([_current_observation(14.5)], {})
    target = completed_local_hour(datetime.now(UTC))
    climate = {
        "dates": [
            f"{year}-{target.month:02d}-{target.day:02d}" for year in range(1991, 2021)
        ],
        "point_values": [{"t": [10.0] * 30}],
    }
    pthbv.async_daily.side_effect = [SmhiApiUnavailableError("HTTP 503"), climate]
    with patch(
        "custom_components.smhi_weather_context.coordinator.parse_archive_for_dates",
        return_value=[],
    ):
        first = await coordinator._async_build_data()
        assert first.values["temperature_now"] == 14.5
        assert first.values["temperature_climate_normal"] is None
        assert not coordinator._history_status["climate"].available
        assert coordinator._history_date is None
        recovered = await coordinator._async_build_data()
    assert recovered.values["temperature_now"] == 14.5
    assert recovered.values["temperature_climate_normal"] == 10.0
    assert coordinator._history_status["climate"].available
    assert coordinator._history_date == target.date()
    assert pthbv.async_daily.await_count == 2


async def test_partial_current_source_failure_keeps_successful_temperature() -> None:
    """One failed wind endpoint must not hide an available temperature source."""
    coordinator, metobs, _, _ = _coordinator(
        options=_options(temperature=True, wind=True)
    )
    _skip_history_refresh(coordinator)
    temperature = _current_observation(14.5)
    wind_direction = _current_observation(180.0)
    wind_gust = _current_observation(7.0)

    async def _latest_day(parameter: int, _station_id: int):
        if parameter == PARAM_TEMPERATURE:
            return [temperature], {}
        if parameter == PARAM_WIND_SPEED:
            raise SmhiApiError("offline wind speed")
        if parameter == PARAM_WIND_DIRECTION:
            return [wind_direction], {}
        if parameter == PARAM_WIND_GUST:
            return [wind_gust], {}
        raise AssertionError(f"unexpected parameter {parameter}")

    metobs.async_latest_day.side_effect = _latest_day

    data = await coordinator._async_build_data()

    assert data.values["temperature_now"] == 14.5
    assert "wind_speed_now" not in data.values
    assert data.source_status["temperature"].available
    assert not data.source_status["wind_speed"].available
    assert data.source_status["wind_speed"].error == "SmhiApiError"
    assert data.values["smhi_data_fresh"] is False


async def test_missing_observation_is_none_and_never_coerced_to_zero() -> None:
    """A successful but empty source response must remain explicitly unavailable."""
    coordinator, metobs, _, _ = _coordinator(options=_options())
    _skip_history_refresh(coordinator)
    metobs.async_latest_day.return_value = ([], {})

    data = await coordinator._async_build_data()

    assert data.values["temperature_now"] is None
    assert data.values["temperature_today_mean"] is None
    assert not data.source_status["temperature"].available
    assert data.source_status["temperature"].stale
    assert data.values["smhi_data_fresh"] is False
    assert all(
        value is None
        for key, value in data.values.items()
        if key.startswith("temperature_")
    )


async def test_stale_observation_is_exposed_but_freshness_is_false() -> None:
    """A stale value remains inspectable while its source is marked stale."""
    coordinator, metobs, _, _ = _coordinator(options=_options())
    _skip_history_refresh(coordinator)
    stale = _current_observation(8.25, age=timedelta(hours=4))
    metobs.async_latest_day.return_value = ([stale], {})

    data = await coordinator._async_build_data()

    assert data.values["temperature_now"] == 8.25
    assert data.source_status["temperature"].available
    assert data.source_status["temperature"].stale
    assert data.values["smhi_data_fresh"] is False


async def test_climate_only_entry_builds_without_any_metobs_request() -> None:
    """PTHBV-only entries must work without configured current-weather sources."""
    coordinator, metobs, _, _ = _coordinator(
        options=_options(temperature=False, wind=False, climate=True)
    )
    target = completed_local_hour(datetime.now(UTC))
    coordinator._history_date = target.date()
    coordinator._climate_values = {
        year: float(year - 1990) for year in range(1991, 2021)
    }

    data = await coordinator._async_build_data()

    assert data.values["temperature_climate_normal"] == 15.5
    assert data.values["temperature_climate_anomaly"] is None
    assert data.values["smhi_data_fresh"] is True
    metobs.async_latest_day.assert_not_awaited()


async def test_archive_uses_stale_cache_when_smhi_is_unavailable() -> None:
    """A network failure may fall back to a previously validated archive."""
    coordinator, metobs, _, cache = _coordinator(options=_options())
    stale = CacheRecord(
        payload="cached corrected archive",
        stored_at=datetime.now(UTC) - timedelta(days=60),
        metadata={"station_id": 71420},
    )
    cache.async_get.side_effect = [None, stale]
    metobs.async_corrected_archive.side_effect = SmhiApiError("offline")

    result = await coordinator._async_archive(
        "temperature_archive_71420", PARAM_TEMPERATURE, 71420
    )

    assert result == "cached corrected archive"
    assert cache.async_get.await_count == 2
    cache.async_set.assert_not_awaited()


async def test_pthbv_uses_stale_cache_when_smhi_is_unavailable() -> None:
    """Climate context must retain its last validated local payload offline."""
    coordinator, _, pthbv, cache = _coordinator(
        options=_options(temperature=False, climate=True)
    )
    target = completed_local_hour(datetime.now(UTC))
    payload = complete_pthbv(1961, target.year - 1)
    stale = CacheRecord(
        payload=json.dumps(payload),
        stored_at=datetime.now(UTC) - timedelta(days=60),
        metadata={"source": "PTHBV"},
    )
    cache.async_get.side_effect = [None, stale]
    pthbv.async_daily.side_effect = SmhiApiError("offline")

    result = await coordinator._async_pthbv(target)

    assert result == payload
    assert cache.async_get.await_count == 2
    cache.async_set.assert_not_awaited()


@pytest.mark.parametrize("payload", ["not-json", "[]", '{"dates": []}'])
async def test_invalid_climate_cache_preserves_upstream_http_failure(
    payload: str,
) -> None:
    """Unusable cache must neither hide HTTP 503 nor block future network retries."""
    coordinator, _, pthbv, cache = _coordinator(
        options=_options(temperature=False, climate=True)
    )
    cache.async_get.return_value = CacheRecord(
        payload=payload, stored_at=datetime.now(UTC), metadata={"source": "PTHBV"}
    )
    error = SmhiApiUnavailableError("HTTP 503", http_status=503)
    pthbv.async_daily.side_effect = error
    data = await coordinator._async_build_data()
    assert data.values["temperature_climate_normal"] is None
    assert data.values["smhi_last_historical_update"] is None
    assert data.source_status["climate"].http_status == 503
    assert data.source_status["climate"].last_success is None
    assert not data.source_status["climate"].available
    assert cache.async_get.await_count == 2
    pthbv.async_daily.assert_awaited_once()
    cache.async_set.assert_not_awaited()


async def test_full_climate_cache_is_rederived_for_each_calendar_day() -> None:
    """A validated full series remains useful offline without reusing daily samples."""
    coordinator, _, pthbv, cache = _coordinator(
        options=_options(temperature=False, climate=True)
    )
    target = completed_local_hour(datetime(2026, 9, 4, 12, tzinfo=UTC))
    tomorrow = target + timedelta(days=1)
    payload = complete_pthbv(1961, 2025)
    payload["point_values"][0]["t"] = [
        5.0 if raw_date.endswith("-09-04") else 9.0 for raw_date in payload["dates"]
    ]
    record = CacheRecord(
        payload=json.dumps(payload),
        stored_at=datetime(2026, 7, 1, tzinfo=UTC),
        metadata={"source": "PTHBV"},
    )
    cache.async_get.side_effect = [None, record, None, record]
    pthbv.async_daily.side_effect = SmhiApiUnavailableError("HTTP 503", http_status=503)
    with patch(
        "custom_components.smhi_weather_context.coordinator.completed_local_hour",
        side_effect=[target, tomorrow],
    ):
        first = await coordinator._async_build_data()
        second = await coordinator._async_build_data()
    assert first.values["temperature_climate_normal"] == 5.0
    assert second.values["temperature_climate_normal"] == 9.0
    assert coordinator._history_values_date == tomorrow.date()
    assert second.source_status["climate"].available
    assert pthbv.async_daily.await_count == 2
    cache.async_set.assert_not_awaited()


async def test_invalid_station_creates_repair_and_marks_source_unavailable() -> None:
    """An incompatible station requires user action and is never auto-switched."""
    coordinator, metobs, _, _ = _coordinator(options=_options())
    metobs.async_validate_station.return_value = False

    with patch(
        "custom_components.smhi_weather_context.coordinator.async_create_station_issue"
    ) as create_issue:
        await coordinator._async_validate_stations()

    create_issue.assert_called_once_with(
        coordinator.hass, "entry-runtime-qa", "temperature", 71420
    )
    _skip_history_refresh(coordinator)

    data = await coordinator._async_build_data()

    assert data.source_status["temperature"].available is False
    assert data.source_status["temperature"].error == "StationUnavailable"
    metobs.async_latest_day.assert_not_awaited()


async def test_valid_station_clears_prior_repair() -> None:
    """A newly valid explicit selection must clear its station repair."""
    coordinator, metobs, _, _ = _coordinator(options=_options())
    metobs.async_validate_station.return_value = True

    with patch(
        "custom_components.smhi_weather_context.coordinator.async_clear_station_issue",
        new=Mock(),
    ) as clear_issue:
        await coordinator._async_validate_stations()

    clear_issue.assert_called_once_with(
        coordinator.hass, "entry-runtime-qa", "temperature"
    )
