"""Offline contract tests for the SMHI MetObs client and parsers."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
import math
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from custom_components.smhi_weather_context.api import SmhiApiResponseError
from custom_components.smhi_weather_context.const import METOBS_BASE_URL
from custom_components.smhi_weather_context.metobs import (
    MetObsClient,
    parse_archive_for_dates,
)
from custom_components.smhi_weather_context.models import Location

FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class StubApi:
    """Return one offline response and retain requested URLs."""

    def __init__(
        self, *, json_data: dict[str, object] | None = None, text: str = ""
    ) -> None:
        self.json_data = json_data or {}
        self.text = text
        self.urls: list[str] = []

    async def async_get_json(self, url: str) -> dict[str, object]:
        self.urls.append(url)
        return deepcopy(self.json_data)

    async def async_get_text(self, url: str) -> str:
        self.urls.append(url)
        return self.text


def test_metobs_uses_pinned_documented_numeric_version() -> None:
    assert METOBS_BASE_URL.endswith("/api/version/1.0")


@pytest.mark.asyncio
async def test_station_discovery_requests_only_core_network() -> None:
    api = StubApi(json_data=load_json("api_metobs_stations.json"))
    client = MetObsClient(api)

    await client.async_stations(1, Location("Göteborg", 57.71, 11.97), 2000)

    query = parse_qs(urlparse(api.urls[0]).query)
    assert query == {"measuringStations": ["core"]}


@pytest.mark.asyncio
async def test_station_discovery_filters_and_ranks_deterministically() -> None:
    api = StubApi(json_data=load_json("api_metobs_stations.json"))
    stations = await MetObsClient(api).async_stations(
        1, Location("Göteborg", 57.71, 11.97), 2000
    )

    assert [station.station_id for station in stations] == [71420, 71380]
    assert all(station.active and station.has_archive for station in stations)
    assert stations[0].distance_km < stations[1].distance_km
    assert stations[0].from_time < datetime(1970, 1, 1, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("periods", "expected"),
    [
        (["latest-day", "corrected-archive"], True),
        (["latest-day", "latest-months"], False),
    ],
)
async def test_station_validation_requires_current_and_archive_periods(
    periods: list[str], expected: bool
) -> None:
    payload = {"period": [{"key": value} for value in periods]}
    api = StubApi(json_data=payload)

    result = await MetObsClient(api).async_validate_station(1, 71420)

    assert result is expected
    assert api.urls == [f"{METOBS_BASE_URL}/parameter/1/station/71420.json"]


@pytest.mark.asyncio
async def test_latest_day_parses_verified_values_and_utc_milliseconds() -> None:
    api = StubApi(json_data=load_json("api_metobs_latest_day.json"))

    observations, raw = await MetObsClient(api).async_latest_day(1, 71420)

    assert [(item.value, item.quality) for item in observations] == [
        (16.6, "Y"),
        (15.9, "G"),
    ]
    assert observations[-1].time == datetime(2026, 9, 3, 15, tzinfo=UTC)
    assert raw["station"]["measuringStations"] == "CORE"
    assert api.urls[0].endswith(
        "/parameter/1/station/71420/period/latest-day/data.json"
    )


@pytest.mark.asyncio
async def test_latest_day_rejects_red_and_unknown_quality_codes() -> None:
    payload = load_json("api_metobs_latest_day.json")
    payload["value"] = [
        {"date": 1788447600000, "value": "15.9", "quality": "G"},
        {"date": 1788447600000, "value": "15.8", "quality": "Y"},
        {"date": 1788447600000, "value": "99.0", "quality": "R"},
        {"date": 1788447600000, "value": "99.0", "quality": "X"},
    ]

    observations, _ = await MetObsClient(StubApi(json_data=payload)).async_latest_day(
        1, 71420
    )

    assert [item.quality for item in observations] == ["G", "Y"]


@pytest.mark.asyncio
async def test_latest_day_rejects_non_finite_values() -> None:
    payload = load_json("api_metobs_latest_day.json")
    payload["value"] = [
        {"date": 1788447600000, "value": value, "quality": "G"}
        for value in ("NaN", "Infinity", "-Infinity")
    ]

    observations, _ = await MetObsClient(StubApi(json_data=payload)).async_latest_day(
        1, 71420
    )

    assert observations == []
    assert all(math.isfinite(item.value) for item in observations)


@pytest.mark.asyncio
async def test_latest_day_requires_value_array() -> None:
    with pytest.raises(SmhiApiResponseError, match="values are missing"):
        await MetObsClient(StubApi(json_data={})).async_latest_day(1, 71420)


def test_archive_parser_finds_dynamic_header_and_selected_dates() -> None:
    text = (FIXTURES / "api_metobs_corrected_archive.csv").read_text(
        encoding="utf-8-sig"
    )

    observations = parse_archive_for_dates(text, month=9, day=3, years={1991, 2020})

    assert [(item.time, item.value, item.quality) for item in observations] == [
        (datetime(1991, 9, 3, 0, tzinfo=UTC), 12.1, "G"),
        (datetime(1991, 9, 3, 1, tzinfo=UTC), 12.3, "Y"),
        (datetime(2020, 9, 3, 0, tzinfo=UTC), 14.2, "G"),
    ]


def test_archive_parser_rejects_red_and_unknown_quality_codes() -> None:
    text = "\n".join(
        [
            "metadata may change in length",
            "Datum;Tid (UTC);Lufttemperatur;Kvalitet",
            "1991-09-03;00:00:00;12.1;G",
            "1991-09-03;01:00:00;12.2;Y",
            "1991-09-03;02:00:00;99.0;R",
            "1991-09-03;03:00:00;99.0;X",
        ]
    )

    observations = parse_archive_for_dates(text, month=9, day=3, years={1991})

    assert [item.quality for item in observations] == ["G", "Y"]


def test_archive_parser_requires_data_header() -> None:
    with pytest.raises(SmhiApiResponseError, match="header is missing"):
        parse_archive_for_dates("metadata only", month=9, day=3, years={1991})


@pytest.mark.asyncio
async def test_corrected_archive_uses_csv_data_endpoint() -> None:
    api = StubApi(text="archive")

    assert await MetObsClient(api).async_corrected_archive(1, 71420) == "archive"
    assert api.urls == [
        f"{METOBS_BASE_URL}/parameter/1/station/71420/period/corrected-archive/data.csv"
    ]
