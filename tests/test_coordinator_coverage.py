"""Focused offline branch coverage for the SMHI coordinator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from test_pthbv import complete_pthbv

from custom_components.smhi_weather_context.api import SmhiApiError
from custom_components.smhi_weather_context.const import (
    ATTRIBUTION,
    PARAM_TEMPERATURE,
    PARAM_WIND_SPEED,
)
from custom_components.smhi_weather_context.coordinator import (
    SmhiWeatherContextCoordinator,
)
from custom_components.smhi_weather_context.models import (
    EntryOptions,
    Location,
    Observation,
    WeatherContextData,
)
from custom_components.smhi_weather_context.storage import CacheRecord

pytestmark = pytest.mark.asyncio

LOCAL_TZ = ZoneInfo("Europe/Stockholm")


class _Hass:
    """Minimal executor facade with explicit keyword support for unit isolation."""

    async def async_add_executor_job(self, target, *args, **kwargs):
        return target(*args, **kwargs)


class _Entry:
    """Minimal config entry accepted by DataUpdateCoordinator."""

    entry_id = "entry-coordinator-coverage"

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
    comparison_years: tuple[int, ...] = (1, 2, 3, 10),
) -> EntryOptions:
    return EntryOptions(
        location=Location("Coverage location", 57.70, 11.97),
        temperature_station_id=71420,
        wind_station_id=72420,
        comparison_years=comparison_years,
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


def _target(year: int = 2025, month: int = 1, day: int = 15, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=LOCAL_TZ)


def _observation(target: datetime, value: float, *, quality: str = "G") -> Observation:
    return Observation(target.astimezone(UTC) + timedelta(minutes=30), value, quality)


def _history_for_years(target: datetime, values: range) -> list[Observation]:
    observations: list[Observation] = []
    for offset, value in enumerate(values, start=1):
        historical_target = SmhiWeatherContextCoordinator._target_for_year(
            target, target.year - offset
        )
        assert historical_target is not None
        observations.append(_observation(historical_target, float(value)))
    return observations


def _record(payload: str, *, days_old: int = 0) -> CacheRecord:
    return CacheRecord(
        payload=payload,
        stored_at=datetime.now(UTC) - timedelta(days=days_old),
        metadata={},
    )


async def test_update_wraps_smhi_error_without_network_details() -> None:
    """Coordinator updates convert source failures to Home Assistant failures."""
    coordinator, _, _, _ = _coordinator(options=_options())
    coordinator._async_validate_stations = AsyncMock(
        side_effect=SmhiApiError("source unavailable")
    )

    with pytest.raises(UpdateFailed, match="source unavailable"):
        await coordinator._async_update_data()


async def test_update_returns_successful_coordinator_data() -> None:
    """A successful update validates stations before returning built data."""
    coordinator, _, _, _ = _coordinator(options=_options())
    expected = WeatherContextData(values={"temperature_now": 4.0})
    coordinator._async_validate_stations = AsyncMock()
    coordinator._async_build_data = AsyncMock(return_value=expected)

    result = await coordinator._async_update_data()

    assert result is expected
    coordinator._async_validate_stations.assert_awaited_once_with()
    coordinator._async_build_data.assert_awaited_once_with()


async def test_station_validation_is_throttled_and_tracks_each_kind() -> None:
    """Daily validation reports one bad wind parameter without changing temperature."""
    coordinator, metobs, _, _ = _coordinator(
        options=_options(temperature=True, wind=True)
    )
    metobs.async_validate_station.side_effect = [True, True, False, True]

    with (
        patch(
            "custom_components.smhi_weather_context.coordinator."
            "async_create_station_issue"
        ) as create_issue,
        patch(
            "custom_components.smhi_weather_context.coordinator."
            "async_clear_station_issue"
        ) as clear_issue,
    ):
        await coordinator._async_validate_stations()
        await coordinator._async_validate_stations()

    assert metobs.async_validate_station.await_count == 4
    assert coordinator._invalid_station_kinds == {"wind"}
    clear_issue.assert_called_once_with(
        coordinator.hass, "entry-coordinator-coverage", "temperature"
    )
    create_issue.assert_called_once_with(
        coordinator.hass, "entry-coordinator-coverage", "wind", 72420
    )


async def test_station_validation_accepts_entry_without_metobs_sources() -> None:
    """A climate-only entry has no station validation requests."""
    coordinator, metobs, _, _ = _coordinator(
        options=_options(temperature=False, climate=True)
    )

    await coordinator._async_validate_stations()

    metobs.async_validate_station.assert_not_awaited()
    assert coordinator._stations_validated_at is not None


async def test_invalid_wind_is_isolated_from_valid_temperature() -> None:
    """An invalid wind station marks all wind sources but keeps temperature live."""
    coordinator, metobs, _, _ = _coordinator(
        options=_options(temperature=True, wind=True)
    )
    coordinator._invalid_station_kinds.add("wind")
    target = coordinator._target_for_year(_target(), 2025)
    assert target is not None
    metobs.async_latest_day.return_value = ([_observation(target, 5.0)], {})
    coordinator._history_date = target.date()

    with patch(
        "custom_components.smhi_weather_context.coordinator.completed_local_hour",
        return_value=target,
    ):
        data = await coordinator._async_build_data()

    assert data.values["temperature_now"] == 5.0
    assert all(
        data.source_status[key].error == "StationUnavailable"
        for key in ("wind_speed", "wind_direction", "wind_gust")
    )
    metobs.async_latest_day.assert_awaited_once_with(PARAM_TEMPERATURE, 71420)


async def test_all_requested_current_sources_can_fail_together() -> None:
    """A cycle fails when every requested current source fails."""
    coordinator, metobs, _, _ = _coordinator(
        options=_options(temperature=True, wind=True)
    )
    metobs.async_latest_day.side_effect = SmhiApiError("offline")

    with pytest.raises(UpdateFailed, match="No current SMHI source"):
        await coordinator._async_build_data()

    assert metobs.async_latest_day.await_count == 4


async def test_build_reloads_history_and_keeps_partial_wind_metrics() -> None:
    """Successful wind speed remains useful when direction and gust fail."""
    coordinator, metobs, _, _ = _coordinator(
        options=_options(temperature=False, wind=True)
    )
    target = _target()
    speed = _observation(target, 4.5)

    async def _latest(parameter: int, _station: int):
        if parameter == PARAM_WIND_SPEED:
            return [speed], {}
        raise SmhiApiError("partial wind outage")

    metobs.async_latest_day.side_effect = _latest
    coordinator._async_load_history = AsyncMock()

    with patch(
        "custom_components.smhi_weather_context.coordinator.completed_local_hour",
        return_value=target,
    ):
        data = await coordinator._async_build_data()

    coordinator._async_load_history.assert_awaited_once_with(target)
    assert data.values["wind_speed_now"] == 4.5
    assert data.values["smhi_last_observation"] == speed.time
    assert data.values["wind_direction"] is None
    assert data.values["wind_gust"] is None
    assert data.source_status["wind_direction"].error == "SmhiApiError"
    assert data.source_status["wind_gust"].error == "SmhiApiError"


async def test_history_loads_temperature_wind_and_climate_sources() -> None:
    """A successful daily refresh maps all three history products."""
    coordinator, _, _, _ = _coordinator(
        options=_options(temperature=True, wind=True, climate=True, precipitation=True)
    )
    target = _target()
    temperature_history = [_observation(_target(2024), 1.0)]
    wind_history = [_observation(_target(2024), 2.0)]
    climate = {
        "dates": ["1991-01-15", "1992-01-15"],
        "point_values": [{"t": [3.0, 4.0], "p": [5.0, 6.0]}],
    }
    coordinator._async_archive = AsyncMock(side_effect=["temperature", "wind"])
    coordinator._async_pthbv = AsyncMock(return_value=climate)
    coordinator.hass.async_add_executor_job = AsyncMock(
        side_effect=[temperature_history, wind_history]
    )

    await coordinator._async_load_history(target)

    assert coordinator._temperature_history == temperature_history
    assert coordinator._wind_history == wind_history
    assert coordinator._climate_values == {1991: 3.0, 1992: 4.0}
    assert coordinator._precipitation_values == {1991: 5.0, 1992: 6.0}
    assert coordinator._history_date == target.date()
    assert all(status.available for status in coordinator._history_status.values())


async def test_failed_history_is_retried_on_next_refresh(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed history source leaves the date unset so the next cycle retries it."""
    caplog.set_level(logging.INFO)
    coordinator, _, _, _ = _coordinator(options=_options())
    target = _target()
    coordinator._async_archive = AsyncMock(
        side_effect=[
            SmhiApiError("offline"),
            SmhiApiError("still offline"),
            "valid archive",
        ]
    )
    coordinator.hass.async_add_executor_job = AsyncMock(return_value=[])

    await coordinator._async_load_history(target)
    assert coordinator._history_date is None
    assert coordinator._history_status["temperature"].error == "SmhiApiError"

    await coordinator._async_load_history(target)
    assert coordinator._history_date is None

    await coordinator._async_load_history(target)
    assert coordinator._history_date == target.date()
    assert coordinator._history_status["temperature"].available
    assert coordinator._async_archive.await_count == 3
    assert (
        caplog.messages.count("SMHI temperature history is unavailable (SmhiApiError)")
        == 1
    )
    assert "SMHI temperature history is available again" in caplog.messages


@pytest.mark.parametrize("error", [ValueError("bad csv"), TypeError("bad schema")])
async def test_history_parse_failure_is_retryable(error: Exception) -> None:
    """Malformed cached history is rejected and never marks the date complete."""
    coordinator, _, _, _ = _coordinator(options=_options())
    coordinator._async_archive = AsyncMock(return_value="invalid archive")
    coordinator.hass.async_add_executor_job = AsyncMock(side_effect=error)

    await coordinator._async_load_history(_target())

    assert coordinator._history_date is None
    assert coordinator._history_status["temperature"].error == "HistoryValidationError"


async def test_history_with_only_invalid_stations_completes_without_tasks() -> None:
    """Invalid station kinds are skipped instead of causing source I/O."""
    coordinator, _, _, _ = _coordinator(options=_options(temperature=True, wind=True))
    coordinator._invalid_station_kinds.update({"temperature", "wind"})
    target = _target()

    await coordinator._async_load_history(target)

    assert coordinator._history_date == target.date()
    assert coordinator._history_status == {}


async def test_archive_cache_fresh_fetch_write_and_total_failure() -> None:
    """Archive caching covers fresh hits, validated writes, and no-fallback errors."""
    fresh_coordinator, fresh_metobs, _, fresh_cache = _coordinator(options=_options())
    fresh_cache.async_get.return_value = _record("fresh")

    assert (
        await fresh_coordinator._async_archive("archive", PARAM_TEMPERATURE, 71420)
        == "fresh"
    )
    fresh_metobs.async_corrected_archive.assert_not_awaited()

    write_coordinator, write_metobs, _, write_cache = _coordinator(options=_options())
    write_cache.async_get.return_value = None
    write_metobs.async_corrected_archive.return_value = "downloaded"

    assert (
        await write_coordinator._async_archive("archive", PARAM_TEMPERATURE, 71420)
        == "downloaded"
    )
    write_cache.async_set.assert_awaited_once_with(
        "archive", "downloaded", {"parameter": PARAM_TEMPERATURE, "station_id": 71420}
    )

    failed_coordinator, failed_metobs, _, failed_cache = _coordinator(
        options=_options()
    )
    failed_cache.async_get.side_effect = [None, None]
    failed_metobs.async_corrected_archive.side_effect = SmhiApiError("offline")

    with pytest.raises(SmhiApiError, match="offline"):
        await failed_coordinator._async_archive("archive", PARAM_TEMPERATURE, 71420)


async def test_pthbv_cache_fresh_fetch_write_and_total_failure() -> None:
    """PTHBV caching follows the same fresh, write, and stale-fallback contract."""
    target = _target()
    payload = complete_pthbv(1961, target.year - 1)
    encoded = json.dumps(payload)
    fresh_coordinator, _, fresh_pthbv, fresh_cache = _coordinator(
        options=_options(temperature=False, climate=True)
    )
    fresh_cache.async_get.return_value = _record(encoded)

    assert await fresh_coordinator._async_pthbv(target) == payload
    fresh_pthbv.async_daily.assert_not_awaited()

    invalid_coordinator, _, invalid_pthbv, invalid_cache = _coordinator(
        options=_options(temperature=False, climate=True)
    )
    invalid_cache.async_get.return_value = _record("[]")
    invalid_pthbv.async_daily.return_value = payload

    assert await invalid_coordinator._async_pthbv(target) == payload
    invalid_pthbv.async_daily.assert_awaited_once()

    write_coordinator, _, write_pthbv, write_cache = _coordinator(
        options=_options(temperature=False, climate=True, precipitation=True)
    )
    write_cache.async_get.return_value = None
    write_pthbv.async_daily.return_value = payload

    assert await write_coordinator._async_pthbv(target) == payload
    write_pthbv.async_daily.assert_awaited_once_with(
        write_coordinator.options.location,
        1961,
        2024,
        precipitation=True,
    )
    cached_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    write_cache.async_set.assert_awaited_once_with(
        "pthbv_daily_57.7000_11.9700_p1_through_2024",
        cached_payload,
        {"source": "PTHBV"},
    )

    failed_coordinator, _, failed_pthbv, failed_cache = _coordinator(
        options=_options(temperature=False, climate=True)
    )
    failed_cache.async_get.side_effect = [None, None]
    failed_pthbv.async_daily.side_effect = SmhiApiError("offline")

    with pytest.raises(SmhiApiError, match="offline"):
        await failed_coordinator._async_pthbv(target)


async def test_temperature_metrics_cover_complete_and_leap_missing_history() -> None:
    """Temperature metrics expose complete history and honest leap-day gaps."""
    coordinator, _, _, _ = _coordinator(options=_options())
    target = _target()
    coordinator._temperature_history = _history_for_years(target, range(1, 11))
    data = WeatherContextData()

    coordinator._populate_temperature(
        data,
        [_observation(target, 11.0)],
        target,
        target + timedelta(hours=1),
    )

    assert data.values["temperature_now"] == 11.0
    assert data.values["temperature_today_mean"] == 11.0
    assert data.values["temperature_10_year_mean"] == 5.5
    assert data.values["temperature_deviation_10_year"] == 5.5
    assert data.values["temperature_historical_min"] == 1.0
    assert data.values["temperature_historical_max"] == 10.0
    assert data.values["temperature_historical_percentile"] == 100.0
    assert data.values["temperature_same_hour_1_year"] == 1.0

    leap_coordinator, _, _, _ = _coordinator(options=_options())
    leap_target = _target(2024, 2, 29)
    leap_data = WeatherContextData()

    leap_coordinator._populate_temperature(
        leap_data, [], leap_target, leap_target + timedelta(hours=1)
    )

    assert leap_data.values["temperature_now"] is None
    assert leap_data.values["temperature_10_year_mean"] is None
    assert leap_data.values["temperature_same_hour_1_year"] is None
    assert leap_data.values["temperature_historical_max"] is None
    assert leap_data.source_status["temperature"].available is False


async def test_climate_and_precipitation_metrics_cover_full_and_missing_data() -> None:
    """Climate metrics enforce normal-period and recent-sample minimums."""
    coordinator, _, _, _ = _coordinator(
        options=_options(temperature=False, climate=True, precipitation=True)
    )
    target = _target()
    coordinator._climate_values = dict.fromkeys(range(1991, 2021), 10.0)
    coordinator._precipitation_values = {
        year: float(year - 1990) for year in range(1991, 2025)
    }
    data = WeatherContextData(values={"temperature_today_mean": 12.0})

    coordinator._populate_climate(data, target)

    assert data.values["temperature_climate_normal"] == 10.0
    assert data.values["temperature_climate_anomaly"] == 2.0
    assert data.values["precipitation_climate_normal"] == 15.5
    assert data.values["precipitation_10_year_mean"] == 29.5
    assert data.values["precipitation_historical_max"] == 34.0
    assert data.attributes["precipitation_climate_normal"]["sample_count"] == 30
    assert data.attributes["precipitation_10_year_mean"]["sample_count"] == 10

    missing_coordinator, _, _, _ = _coordinator(
        options=_options(temperature=False, climate=True, precipitation=True)
    )
    missing_coordinator._climate_values = dict.fromkeys(range(1992, 2021, 4), -1.0)
    missing_data = WeatherContextData(values={"temperature_today_mean": "unknown"})

    missing_coordinator._populate_climate(missing_data, _target(2024, 2, 29))

    assert missing_data.values["temperature_climate_normal"] is None
    assert missing_data.values["temperature_climate_anomaly"] is None
    assert missing_data.values["precipitation_climate_normal"] is None
    assert missing_data.values["precipitation_10_year_mean"] is None
    assert missing_data.values["precipitation_historical_max"] is None


async def test_wind_metrics_cover_complete_and_missing_observations() -> None:
    """Wind metrics keep direction and gust optional without inventing values."""
    coordinator, _, _, _ = _coordinator(options=_options(temperature=False, wind=True))
    target = _target()
    coordinator._wind_history = _history_for_years(target, range(1, 11))
    data = WeatherContextData()

    coordinator._populate_wind(
        data,
        [_observation(target, 11.0)],
        [_observation(target, 90.0)],
        [_observation(target, 18.0)],
        target,
        target + timedelta(hours=1),
    )

    assert data.values["wind_speed_now"] == 11.0
    assert data.values["wind_direction_degrees"] == 90.0
    assert data.values["wind_direction"] == "O"
    assert data.values["wind_gust"] == 18.0
    assert data.values["wind_today_mean"] == 11.0
    assert data.values["wind_10_year_mean"] == 5.5
    assert data.values["wind_historical_percentile"] == 100.0
    assert data.values["wind_same_hour_10_year"] == 10.0

    missing_data = WeatherContextData()
    coordinator._wind_history = []
    coordinator._populate_wind(
        missing_data,
        [],
        [],
        [],
        target,
        target + timedelta(hours=1),
    )

    assert missing_data.values["wind_speed_now"] is None
    assert missing_data.values["wind_direction"] is None
    assert missing_data.values["wind_gust"] is None
    assert missing_data.values["wind_10_year_mean"] is None
    assert missing_data.source_status["wind_speed"].available is False


async def test_common_attributes_drop_unknown_optional_values() -> None:
    """Coordinator attributes never publish meaningless null metadata."""
    coordinator, _, _, _ = _coordinator(options=_options())

    attributes = coordinator._common_attributes(None, None, source="PTHBV")

    assert attributes == {
        "source_product": "PTHBV",
        "data_quality": "good",
        "attribution": ATTRIBUTION,
    }
