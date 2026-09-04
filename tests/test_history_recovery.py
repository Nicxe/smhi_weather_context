"""Offline regressions for daily history invalidation and source recovery."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
import json
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import pytest
from test_coordinator import _coordinator, _options
from test_pthbv import complete_pthbv

from custom_components.smhi_weather_context import coordinator as coordinator_module
from custom_components.smhi_weather_context.api import (
    SmhiApiResponseError,
    SmhiApiUnavailableError,
)
from custom_components.smhi_weather_context.calculations import completed_local_hour
from custom_components.smhi_weather_context.const import (
    PARAM_TEMPERATURE,
    PARAM_WIND_SPEED,
)
from custom_components.smhi_weather_context.coordinator import (
    SmhiWeatherContextCoordinator,
)
from custom_components.smhi_weather_context.models import (
    Observation,
    WeatherContextData,
)
from custom_components.smhi_weather_context.pthbv import values_for_calendar_date
from custom_components.smhi_weather_context.storage import CacheRecord

pytestmark = pytest.mark.asyncio

DAY_A = datetime(2026, 9, 3, 10, tzinfo=UTC)
DAY_B = DAY_A + timedelta(days=1)
HISTORY_SOURCES = ("temperature_history", "wind_history", "climate")
PRIVATE_DETAIL = "private-provider-response-detail"


@pytest.fixture
def clock() -> Iterator[Mock]:
    """Freeze only the coordinator clock; keep real datetime parsing available."""
    with patch.object(coordinator_module, "datetime", wraps=datetime) as frozen:
        frozen.now.return_value = DAY_A
        yield frozen


def _climate_payload() -> dict[str, Any]:
    """Represent validated source data with different normals for the two days."""
    return {
        "dates": [
            f"{year}-09-{day:02d}" for year in range(1991, 2026) for day in (3, 4)
        ],
        "point_values": [{"t": [10.0, 20.0] * 35, "p": [2.0, 4.0] * 35}],
    }


def _archive_payload() -> str:
    """Exercise real CSV parsing and hourly calculations without external files."""
    rows = ["Datum;Tid (UTC);Varde;Kvalitet"]
    rows.extend(
        f"{year}-09-{day:02d};{hour:02d}:00:00;{value};G"
        for year in range(2016, 2026)
        for day, value in ((3, 6.0), (4, 8.0))
        for hour in range(24)
    )
    return "\n".join(rows)


def _ready(
    clock: Mock,
    *,
    temperature: bool = True,
    wind: bool = True,
    validate_cache: bool = False,
) -> tuple[
    SmhiWeatherContextCoordinator, SimpleNamespace, SimpleNamespace, SimpleNamespace
]:
    coordinator, metobs, pthbv, cache = _coordinator(
        options=_options(
            temperature=temperature, wind=wind, climate=True, precipitation=True
        )
    )
    cache.async_get.return_value = None
    metobs.async_corrected_archive.return_value = _archive_payload()
    pthbv.async_daily.return_value = _climate_payload()
    if not validate_cache:
        # Compact fixtures isolate coordinator recovery from full-series validation.
        coordinator._async_pthbv = pthbv.async_daily

    async def _current(_parameter: int, _station_id: int):
        target = completed_local_hour(clock.now.return_value)
        return [Observation(target.astimezone(UTC) + timedelta(minutes=30), 14.5)], {}

    metobs.async_latest_day.side_effect = _current
    return coordinator, metobs, pthbv, cache


async def _build_at(
    coordinator: SmhiWeatherContextCoordinator, clock: Mock, now: datetime
) -> WeatherContextData:
    clock.now.return_value = now
    return await coordinator._async_build_data()


def _fail_source(metobs: SimpleNamespace, pthbv: SimpleNamespace, source: str) -> None:
    """Fail exactly one source; every other configured source still succeeds."""
    error = SmhiApiUnavailableError(PRIVATE_DETAIL, http_status=503)
    failed_parameter = {
        "temperature_history": PARAM_TEMPERATURE,
        "wind_history": PARAM_WIND_SPEED,
    }.get(source)

    async def _archive(parameter: int, _station_id: int) -> str:
        if parameter == failed_parameter:
            raise error
        return metobs.async_corrected_archive.return_value

    metobs.async_corrected_archive.side_effect = _archive
    pthbv.async_daily.side_effect = error if source == "climate" else None


def _assert_empty_climate(
    coordinator: SmhiWeatherContextCoordinator, data: WeatherContextData
) -> None:
    assert coordinator._climate_values == {}
    assert coordinator._precipitation_values == {}
    for key in (
        "temperature_climate_normal",
        "temperature_climate_anomaly",
        "precipitation_climate_normal",
        "precipitation_10_year_mean",
        "precipitation_historical_max",
    ):
        assert data.values[key] is None, key


async def test_day_change_clears_all_derived_values_before_failed_retrieval(
    clock: Mock,
) -> None:
    """A real day-A success cannot leak any derived samples into failed day B."""
    coordinator, metobs, pthbv, _ = _ready(clock)
    first = await _build_at(coordinator, clock, DAY_A)
    assert first.values["temperature_same_hour_1_year"] == 6.0
    assert first.values["wind_same_hour_1_year"] == 6.0
    assert first.values["temperature_climate_normal"] == 10.0
    assert first.values["precipitation_climate_normal"] == 2.0
    assert coordinator._temperature_history
    assert coordinator._wind_history
    assert first.values["smhi_last_historical_update"] == DAY_A

    async def _unavailable(*_args: Any, **_kwargs: Any) -> None:
        # Inspect at the I/O boundary, before failure handling or parsing runs.
        assert coordinator._temperature_history == []
        assert coordinator._wind_history == []
        assert coordinator._climate_values == {}
        assert coordinator._precipitation_values == {}
        raise SmhiApiUnavailableError(PRIVATE_DETAIL, http_status=503)

    metobs.async_corrected_archive.side_effect = _unavailable
    pthbv.async_daily.side_effect = _unavailable
    failed = await _build_at(coordinator, clock, DAY_B)

    _assert_empty_climate(coordinator, failed)
    assert coordinator._temperature_history == []
    assert coordinator._wind_history == []
    assert failed.values["temperature_same_hour_1_year"] is None
    assert failed.values["wind_same_hour_1_year"] is None
    assert failed.values["temperature_now"] == 14.5
    assert failed.source_status["temperature"].available
    assert failed.source_status["wind_speed"].available
    assert failed.values["smhi_last_historical_update"] == DAY_A
    assert failed.values["smhi_data_fresh"] is False
    assert coordinator._history_date is None
    for source in HISTORY_SOURCES:
        status = failed.source_status[source]
        assert not status.available
        assert status.last_success == DAY_A
        assert status.last_attempt == DAY_B
        assert status.http_status == 503
        assert status.error == "SmhiApiUnavailableError"


@pytest.mark.parametrize(
    "failure", ["http_503", "response_mismatch", "precipitation_validation"]
)
async def test_climate_failure_is_atomic_and_retries_with_once_only_logs(
    clock: Mock, caplog: pytest.LogCaptureFixture, failure: str
) -> None:
    """Retrieval rejection and failed p extraction both invalidate t and p."""
    caplog.set_level(logging.INFO, logger=coordinator_module.__name__)
    coordinator, _, pthbv, _ = _ready(clock, temperature=False, wind=False)
    first = await _build_at(coordinator, clock, DAY_A)
    assert first.values["temperature_climate_normal"] == 10.0
    assert first.values["precipitation_climate_normal"] == 2.0
    if failure == "http_503":
        pthbv.async_daily.side_effect = SmhiApiUnavailableError(
            PRIVATE_DETAIL, http_status=503
        )
    elif failure == "response_mismatch":
        pthbv.async_daily.side_effect = SmhiApiResponseError(
            "PTHBV values do not match dates"
        )
    else:
        # The temperature vector is valid; precipitation raises during extraction.
        pthbv.async_daily.return_value["point_values"][0]["p"] = None

    def _extract(data, month, day, variable):
        if variable == "p":
            # Temperature must not be published until precipitation also validates.
            assert coordinator._climate_values == {}
            assert coordinator._precipitation_values == {}
        return values_for_calendar_date(data, month, day, variable)

    with patch.object(
        coordinator_module, "values_for_calendar_date", side_effect=_extract
    ) as extract:
        for attempt in (DAY_B, DAY_B + timedelta(minutes=15)):
            failed = await _build_at(coordinator, clock, attempt)
            _assert_empty_climate(coordinator, failed)
            status = failed.source_status["climate"]
            assert not status.available
            assert status.last_attempt == attempt
            assert status.last_success == DAY_A
            assert status.http_status == (503 if failure == "http_503" else None)
            assert (
                status.error
                == {
                    "http_503": "SmhiApiUnavailableError",
                    "response_mismatch": "SmhiApiResponseError",
                    "precipitation_validation": "HistoryValidationError",
                }[failure]
            )
            assert failed.values["smhi_last_historical_update"] == DAY_A
            assert coordinator._history_date is None
        if failure != "precipitation_validation":
            extract.assert_not_called()
        else:
            assert [call.args[3] for call in extract.call_args_list] == [
                "t",
                "p",
                "t",
                "p",
            ]

    pthbv.async_daily.side_effect = None
    pthbv.async_daily.return_value = _climate_payload()
    recovered_at = DAY_B + timedelta(minutes=30)
    recovered = await _build_at(coordinator, clock, recovered_at)
    assert recovered.values["temperature_climate_normal"] == 20.0
    assert recovered.values["precipitation_climate_normal"] == 4.0
    assert recovered.values["smhi_last_historical_update"] == recovered_at
    assert recovered.source_status["climate"].available
    assert recovered.source_status["climate"].last_success == recovered_at
    assert recovered.source_status["climate"].last_attempt == recovered_at
    assert recovered.source_status["climate"].error is None
    assert coordinator._history_date == completed_local_hour(DAY_B).date()

    unchanged = await _build_at(coordinator, clock, DAY_B + timedelta(minutes=45))
    assert pthbv.async_daily.await_count == 4
    assert unchanged.source_status["climate"].last_attempt == recovered_at
    assert unchanged.values["smhi_last_historical_update"] == recovered_at
    records = [r for r in caplog.records if r.name == coordinator_module.__name__]
    assert len([r for r in records if r.levelno == logging.WARNING]) == 1
    assert len([r for r in records if r.levelno == logging.INFO]) == 1
    assert "SMHI climate history is available again" in caplog.messages
    assert PRIVATE_DETAIL not in caplog.text
    if failure == "http_503":
        assert (
            caplog.messages.count(
                "SMHI climate history is unavailable (SmhiApiUnavailableError; HTTP 503)"
            )
            == 1
        )


@pytest.mark.parametrize("failed_source", HISTORY_SOURCES)
@pytest.mark.parametrize("previous_success", [False, True])
async def test_historical_update_requires_every_requested_source(
    clock: Mock, failed_source: str, previous_success: bool
) -> None:
    """A partial refresh preserves the prior complete timestamp, including None."""
    coordinator, metobs, pthbv, _ = _ready(clock)
    previous_update = None
    attempted_at = DAY_A
    if previous_success:
        first = await _build_at(coordinator, clock, DAY_A)
        assert first.values["smhi_last_historical_update"] == DAY_A
        previous_update = DAY_A
        attempted_at = DAY_B
    _fail_source(metobs, pthbv, failed_source)

    partial = await _build_at(coordinator, clock, attempted_at)

    assert partial.values["smhi_last_historical_update"] == previous_update
    assert coordinator._history_date is None
    for source in HISTORY_SOURCES:
        status = partial.source_status[source]
        assert status.available == (source != failed_source)
        assert status.last_attempt == attempted_at
        assert status.last_success == (
            previous_update if source == failed_source else attempted_at
        )
    if failed_source == "climate":
        _assert_empty_climate(coordinator, partial)
    else:
        expected_normal = 20.0 if previous_success else 10.0
        assert partial.values["temperature_climate_normal"] == expected_normal

    metobs.async_corrected_archive.side_effect = None
    pthbv.async_daily.side_effect = None
    recovered_at = attempted_at + timedelta(minutes=15)
    recovered = await _build_at(coordinator, clock, recovered_at)
    assert recovered.values["smhi_last_historical_update"] == recovered_at
    assert all(recovered.source_status[source].available for source in HISTORY_SOURCES)
    assert coordinator._history_date == completed_local_hour(attempted_at).date()


@pytest.mark.parametrize("failed_source", HISTORY_SOURCES)
async def test_same_day_failure_clears_previously_successful_source(
    clock: Mock, failed_source: str
) -> None:
    """A retry must invalidate its failed source even without a date transition."""
    coordinator, metobs, pthbv, _ = _ready(clock)
    other_failure = "wind_history" if failed_source != "wind_history" else "climate"
    _fail_source(metobs, pthbv, other_failure)
    first = await _build_at(coordinator, clock, DAY_A)
    assert first.source_status[failed_source].available
    assert coordinator._history_date is None
    if failed_source == "climate":
        assert first.values["temperature_climate_normal"] == 10.0
        assert first.values["precipitation_climate_normal"] == 2.0
    else:
        kind = failed_source.removesuffix("_history")
        assert first.values[f"{kind}_same_hour_1_year"] == 6.0

    _fail_source(metobs, pthbv, failed_source)
    retry_at = DAY_A + timedelta(minutes=15)
    failed = await _build_at(coordinator, clock, retry_at)

    assert failed.source_status[other_failure].available
    assert not failed.source_status[failed_source].available
    assert failed.source_status[failed_source].last_success == DAY_A
    assert failed.source_status[failed_source].last_attempt == retry_at
    assert failed.values["smhi_last_historical_update"] is None
    if failed_source == "climate":
        _assert_empty_climate(coordinator, failed)
    else:
        assert getattr(coordinator, f"_{failed_source}") == []
        assert failed.values[f"{kind}_same_hour_1_year"] is None


@pytest.mark.parametrize("source", ["temperature_history", "wind_history"])
async def test_archive_validation_failure_clears_day_a_observations(
    clock: Mock, source: str
) -> None:
    """Downloaded but invalid CSV is not a successful source refresh."""
    coordinator, metobs, _, _ = _ready(clock)
    first = await _build_at(coordinator, clock, DAY_A)
    kind = source.removesuffix("_history")
    assert first.values[f"{kind}_same_hour_1_year"] == 6.0
    failed_parameter = PARAM_TEMPERATURE if kind == "temperature" else PARAM_WIND_SPEED

    async def _archive(parameter: int, _station_id: int) -> str:
        if parameter == failed_parameter:
            return "invalid CSV without an observation header"
        return metobs.async_corrected_archive.return_value

    metobs.async_corrected_archive.side_effect = _archive
    failed = await _build_at(coordinator, clock, DAY_B)

    assert getattr(coordinator, f"_{source}") == []
    assert failed.values[f"{kind}_same_hour_1_year"] is None
    assert failed.values["smhi_last_historical_update"] == DAY_A
    status = failed.source_status[source]
    assert not status.available
    assert status.error == "HistoryValidationError"
    assert status.last_success == DAY_A
    assert status.last_attempt == DAY_B
    assert status.http_status is None


async def test_failed_current_temperature_is_not_overwritten_by_successful_archive(
    clock: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    """Available wind permits a refresh while temperature retains its own error."""
    coordinator, metobs, _, _ = _ready(clock)
    first = await _build_at(coordinator, clock, DAY_A)
    assert first.source_status["temperature"].last_success == DAY_A
    previous_observation = first.source_status["temperature"].last_update
    assert previous_observation != DAY_A
    successful_current = metobs.async_latest_day.side_effect

    async def _current(parameter: int, station_id: int):
        if parameter == PARAM_TEMPERATURE:
            raise SmhiApiUnavailableError(PRIVATE_DETAIL, http_status=503)
        return await successful_current(parameter, station_id)

    metobs.async_latest_day.side_effect = _current
    failed = await _build_at(coordinator, clock, DAY_B)

    status = failed.source_status["temperature"]
    assert not status.available
    assert status.error == "SmhiApiUnavailableError"
    assert status.last_update == previous_observation
    assert status.last_success == DAY_A
    assert status.last_attempt == DAY_B
    assert status.http_status == 503
    for source in ("temperature_history", "wind_history", "wind_speed"):
        assert failed.source_status[source].available
        assert failed.source_status[source].last_success == DAY_B
        assert failed.source_status[source].last_attempt == DAY_B
        assert failed.source_status[source].http_status is None
    assert "wind" not in failed.source_status
    assert failed.values.get("temperature_now") is None
    assert failed.values["wind_speed_now"] == 14.5
    assert failed.values["smhi_data_fresh"] is False
    assert failed.values["smhi_last_historical_update"] == DAY_B
    assert PRIVATE_DETAIL not in repr(failed.source_status)
    assert PRIVATE_DETAIL not in caplog.text

    metobs.async_latest_day.side_effect = successful_current
    recovered_at = DAY_B + timedelta(minutes=15)
    recovered = await _build_at(coordinator, clock, recovered_at)
    assert recovered.source_status["temperature"].available
    assert recovered.source_status["temperature"].last_success == recovered_at
    assert recovered.source_status["temperature"].last_attempt == recovered_at
    assert recovered.source_status["temperature"].error is None
    assert recovered.source_status["temperature"].http_status is None
    assert recovered.source_status["temperature_history"].last_success == DAY_B


@pytest.mark.parametrize("stale_fallback", [False, True])
async def test_validated_cache_refresh_advances_source_success_and_target_date(
    clock: Mock, stale_fallback: bool
) -> None:
    """Cache validation counts as success and recomputes the new calendar date."""
    coordinator, metobs, pthbv, cache = _ready(
        clock, temperature=False, wind=False, validate_cache=True
    )
    payload = complete_pthbv(1961, DAY_A.year - 1)
    point = payload["point_values"][0]
    point["t"] = [20.0 if day.endswith("09-04") else 10.0 for day in payload["dates"]]
    point["p"] = [4.0 if day.endswith("09-04") else 2.0 for day in payload["dates"]]
    cached = CacheRecord(
        payload=json.dumps(payload),
        stored_at=DAY_A - timedelta(days=60 if stale_fallback else 1),
        metadata={"source": "PTHBV"},
    )

    async def _cached(_key: str, *, max_age: timedelta | None = None):
        return None if stale_fallback and max_age is not None else cached

    cache.async_get.side_effect = _cached
    pthbv.async_daily.side_effect = SmhiApiUnavailableError(
        PRIVATE_DETAIL, http_status=503
    )
    first = await _build_at(coordinator, clock, DAY_A)
    assert first.values["temperature_climate_normal"] == 10.0
    assert first.values["smhi_last_historical_update"] == DAY_A
    second = await _build_at(coordinator, clock, DAY_B)

    assert second.values["temperature_climate_normal"] == 20.0
    assert second.values["precipitation_climate_normal"] == 4.0
    assert second.values["smhi_last_historical_update"] == DAY_B
    assert second.source_status["climate"].available
    assert second.source_status["climate"].last_success == DAY_B
    assert second.source_status["climate"].last_attempt == DAY_B
    assert second.source_status["climate"].http_status is None
    assert coordinator._history_date == completed_local_hour(DAY_B).date()
    assert pthbv.async_daily.await_count == (2 if stale_fallback else 0)
    cache.async_set.assert_not_awaited()
    metobs.async_latest_day.assert_not_awaited()
    metobs.async_corrected_archive.assert_not_awaited()
