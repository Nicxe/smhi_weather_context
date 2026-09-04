"""Focused offline branch coverage for small core modules."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from aiohttp import ClientConnectionError
import pytest

from custom_components.smhi_weather_context import api as api_module
from custom_components.smhi_weather_context.api import (
    SmhiApiClient,
    SmhiApiConnectionError,
    SmhiApiResponseError,
    SmhiCoverageError,
    validate_smhi_url,
)
from custom_components.smhi_weather_context.binary_sensor import (
    SmhiDataFreshBinarySensor,
    async_setup_entry,
)
from custom_components.smhi_weather_context.calculations import (
    day_mean_through_hour,
    latest,
    subtract,
    valid_observations,
    vector_mean_degrees,
)
from custom_components.smhi_weather_context.const import CONF_LOCATION_ID
from custom_components.smhi_weather_context.models import (
    EntryOptions,
    Location,
    Observation,
    WeatherContextData,
)
from custom_components.smhi_weather_context.storage import SourceCache

METOBS_URL = "https://opendata-download-metobs.smhi.se/api.json"


class _FakeContent:
    """Minimal asynchronous response body."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


class _FakeResponse:
    """Minimal response implementing the client-facing aiohttp contract."""

    def __init__(
        self,
        status: int,
        *,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self.content_length = None
        self.content = _FakeContent([body])
        self.released = False

    def release(self) -> None:
        self.released = True


class _FakeSession:
    """Return queued responses without opening a network connection."""

    def __init__(self, *responses: _FakeResponse | Exception) -> None:
        self._responses = list(responses)

    async def get(self, _url: str, **_kwargs: object) -> _FakeResponse:
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _Config:
    """Minimal Home Assistant config path provider."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def path(self, *parts: str) -> str:
        return str(self._root.joinpath(*parts))


class _Hass:
    """Minimal executor facade for cache tests."""

    def __init__(self, root: Path) -> None:
        self.config = _Config(root)

    async def async_add_executor_job(self, target, *args):
        return target(*args)


def _binary_sensor_entry(value: object) -> SimpleNamespace:
    options = EntryOptions(
        location=Location("Testplats", 57.70, 11.97),
        temperature_station_id=71420,
        wind_station_id=71420,
        comparison_years=(1,),
        enable_temperature=True,
        enable_wind=False,
        enable_climate=False,
        enable_precipitation=False,
    )
    coordinator = SimpleNamespace(
        data=WeatherContextData(values={"smhi_data_fresh": value}),
        last_update_success=True,
    )
    return SimpleNamespace(
        data={CONF_LOCATION_ID: "stable-location-id"},
        runtime_data=SimpleNamespace(coordinator=coordinator, options=options),
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://opendata-download-metobs.smhi.se:not-a-port/api.json",
        "https://opendata-download-metobs.smhi.se:99999/api.json",
    ],
)
def test_url_validation_rejects_malformed_ports(url: str) -> None:
    """Malformed or out-of-range ports must fail before an HTTP request."""
    with pytest.raises(SmhiApiResponseError, match="unsafe"):
        validate_smhi_url(url)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error_type", "message"),
    [
        (400, SmhiCoverageError, "outside SMHI coverage"),
        (403, SmhiApiResponseError, "HTTP 403"),
        (503, SmhiApiResponseError, "HTTP 503"),
    ],
)
async def test_api_terminal_http_statuses_are_sanitized_and_released(
    status: int, error_type: type[Exception], message: str
) -> None:
    """Coverage, permanent, and exhausted transient failures stay bounded."""
    response = _FakeResponse(status)
    client = SmhiApiClient(_FakeSession(response))

    with pytest.raises(error_type, match=message):
        await client._request(METOBS_URL, max_bytes=16, attempts=1)

    assert response.released


@pytest.mark.asyncio
async def test_api_connection_retry_can_recover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient connection error retries and returns a later response."""

    async def _no_wait(_delay: float) -> None:
        return None

    monkeypatch.setattr(api_module.asyncio, "sleep", _no_wait)
    response = _FakeResponse(200)
    client = SmhiApiClient(_FakeSession(ClientConnectionError("offline"), response))

    assert await client._request(METOBS_URL, max_bytes=16) is response


@pytest.mark.asyncio
async def test_api_zero_attempts_normalizes_to_connection_error() -> None:
    """An exhausted request loop exposes only the integration error type."""
    with pytest.raises(SmhiApiConnectionError, match="Could not reach"):
        await SmhiApiClient(_FakeSession())._request(
            METOBS_URL, max_bytes=16, attempts=0
        )


@pytest.mark.asyncio
async def test_text_response_accepts_csv_and_decodes_utf8_bom() -> None:
    """SMHI archive text accepts CSV media types and UTF-8 BOM input."""
    response = _FakeResponse(
        200,
        body=b"\xef\xbb\xbfDatum;V\xc3\xa4rde",
        headers={"Content-Type": "text/csv; charset=utf-8"},
    )

    result = await SmhiApiClient(_FakeSession(response)).async_get_text(METOBS_URL)

    assert result == "Datum;Värde"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "content_type", "message"),
    [
        (b"plain", "application/octet-stream", "content type"),
        (b"\xff", "text/plain", "invalid UTF-8"),
    ],
)
async def test_text_response_rejects_wrong_media_type_or_encoding(
    body: bytes, content_type: str, message: str
) -> None:
    """Archive responses fail closed on type confusion and invalid encoding."""
    response = _FakeResponse(
        200,
        body=body,
        headers={"Content-Type": content_type},
    )

    with pytest.raises(SmhiApiResponseError, match=message):
        await SmhiApiClient(_FakeSession(response)).async_get_text(METOBS_URL)

    if content_type == "application/octet-stream":
        assert response.released


def test_calculations_cover_rejected_data_and_empty_results() -> None:
    """Bad quality/non-finite samples cannot become current weather values."""
    observations = [
        Observation(datetime(2026, 9, 3, tzinfo=UTC), 12.0, "g"),
        Observation(datetime(2026, 9, 3, 1, tzinfo=UTC), 13.0, "Y"),
        Observation(datetime(2026, 9, 3, 2, tzinfo=UTC), 99.0, "R"),
        Observation(datetime(2026, 9, 3, 3, tzinfo=UTC), float("nan"), "G"),
    ]

    assert valid_observations(observations) == observations[:2]
    assert latest(observations) == observations[1]
    assert latest([]) is None
    assert vector_mean_degrees([]) is None
    assert vector_mean_degrees([float("nan")]) is None


def test_nonexistent_local_hour_and_subtraction_boundaries() -> None:
    """Spring DST gaps remain unavailable and anomalies preserve real zero."""
    nonexistent = datetime(2024, 3, 31, 2, tzinfo=ZoneInfo("Europe/Stockholm"))

    assert day_mean_through_hour([], nonexistent) == (None, 0, 0)
    assert subtract(None, 3.0) is None
    assert subtract(3.0, None) is None
    assert subtract(3.0, 3.0) == 0.0
    assert subtract(3.456, 1.111) == 2.34


@pytest.mark.asyncio
async def test_binary_sensor_setup_and_truth_conversion() -> None:
    """The disabled-by-default diagnostic reflects both fresh and stale data."""
    entry = _binary_sensor_entry("fresh")
    entities: list[SmhiDataFreshBinarySensor] = []

    await async_setup_entry(None, entry, lambda added: entities.extend(added))

    assert len(entities) == 1
    assert entities[0].is_on is True
    assert entities[0].unique_id == "stable-location-id_smhi_data_fresh"

    entry.runtime_data.coordinator.data.values["smhi_data_fresh"] = 0
    assert entities[0].is_on is False
    entry.runtime_data.coordinator.data.values.clear()
    assert entities[0].is_on is False


@pytest.mark.asyncio
async def test_cache_key_validation_and_normalization(tmp_path: Path) -> None:
    """Cache keys are local safe names and never become path traversal input."""
    cache = SourceCache(_Hass(tmp_path), "entry-a")

    with pytest.raises(ValueError, match="Invalid cache key"):
        cache._path("../")

    assert cache._path("station:71420") == cache._path("station71420")
    assert cache._path("station-71_420").parent == cache._root


@pytest.mark.asyncio
async def test_cache_normalizes_naive_timestamp_and_enforces_age(
    tmp_path: Path,
) -> None:
    """Legacy naive timestamps become UTC while expired records are rejected."""
    cache = SourceCache(_Hass(tmp_path), "entry-a")
    await cache.async_set("history", "trusted", {"station": 71420})
    path = cache._path("history")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["stored_at"] = "2026-09-03T12:00:00"
    path.write_text(json.dumps(raw), encoding="utf-8")

    record = await cache.async_get("history")

    assert record is not None
    assert record.stored_at == datetime(2026, 9, 3, 12, tzinfo=UTC)
    assert await cache.async_get("history", max_age=timedelta(seconds=0)) is None


@pytest.mark.asyncio
async def test_cache_accepts_fresh_record_with_age_limit(tmp_path: Path) -> None:
    """A checksum-valid record inside the age window remains usable."""
    cache = SourceCache(_Hass(tmp_path), "entry-a")
    await cache.async_set("history", "trusted")

    record = await cache.async_get("history", max_age=timedelta(days=1))

    assert record is not None
    assert record.payload == "trusted"
    assert record.metadata == {}


@pytest.mark.asyncio
async def test_cache_rejects_symlinked_entry_root(tmp_path: Path) -> None:
    """A config-entry cache root may not redirect writes outside its directory."""
    cache = SourceCache(_Hass(tmp_path), "entry-a")
    outside = tmp_path / "outside"
    outside.mkdir()
    cache._root.parent.mkdir(parents=True)
    cache._root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError, match="Unsafe cache path"):
        await cache.async_set("history", "blocked")

    assert list(outside.iterdir()) == []
