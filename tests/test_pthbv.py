"""Offline contract tests for the official PTHBV point API."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import date, timedelta
import json
import math
from pathlib import Path
import traceback
from urllib.parse import parse_qs, urlparse

import pytest

from custom_components.smhi_weather_context.api import SmhiApiResponseError
from custom_components.smhi_weather_context.models import Location
from custom_components.smhi_weather_context.pthbv import (
    PthbvClient,
    validate_daily_data,
    values_for_calendar_date,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_pthbv() -> dict[str, object]:
    return json.loads((FIXTURES / "api_pthbv_daily.json").read_text(encoding="utf-8"))


def complete_pthbv(start_year: int = 1991, end_year: int = 2020) -> dict[str, object]:
    """Build a compact-valued, date-complete response for the requested years."""
    current = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    dates: list[str] = []
    while current <= end:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return {
        "dates": dates,
        "coord_sys_info": {"EPSG": 4326, "name": "WGS 84"},
        "point_values": [
            {
                "east": 11.97,
                "north": 57.71,
                "p": [0.0] * len(dates),
                "t": [12.1] * len(dates),
            }
        ],
    }


class StubApi:
    """Return an offline PTHBV response and retain the requested URL."""

    def __init__(self, data: dict[str, object]) -> None:
        self.data = data
        self.urls: list[str] = []

    async def async_get_json(self, url: str) -> dict[str, object]:
        self.urls.append(url)
        return deepcopy(self.data)


@pytest.mark.asyncio
async def test_daily_builds_documented_lon_lat_url_and_repeated_variables() -> None:
    api = StubApi(complete_pthbv())

    await PthbvClient(api).async_daily(
        Location("Göteborg", 57.71, 11.97),
        1991,
        2020,
        precipitation=True,
    )

    parsed = urlparse(api.urls[0])
    assert parsed.scheme == "https"
    assert parsed.hostname == "opendata-download-metanalys.smhi.se"
    assert parsed.path == (
        "/api/category/pthbv1g/version/1/geotype/multipoint/"
        "from/1991/to/2020/period/daily/data.json"
    )
    assert parse_qs(parsed.query) == {
        "epsg": ["4326"],
        "ll": ["11.9700,57.7100"],
        "var": ["t", "p"],
    }


@pytest.mark.asyncio
async def test_daily_omits_precipitation_when_not_requested() -> None:
    api = StubApi(complete_pthbv())

    await PthbvClient(api).async_daily(Location("Göteborg", 57.71, 11.97), 1991, 2020)

    assert parse_qs(urlparse(api.urls[0]).query)["var"] == ["t"]


@pytest.mark.asyncio
async def test_daily_accepts_verified_parallel_schema() -> None:
    payload = complete_pthbv()

    result = await PthbvClient(StubApi(payload)).async_daily(
        Location("Göteborg", 57.71, 11.97),
        1991,
        2020,
        precipitation=True,
    )

    assert result == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["dates", "point_values"])
async def test_daily_requires_top_level_arrays(missing: str) -> None:
    payload = complete_pthbv()
    payload.pop(missing)

    with pytest.raises(SmhiApiResponseError, match="structure is invalid"):
        await PthbvClient(StubApi(payload)).async_daily(
            Location("Göteborg", 57.71, 11.97), 1991, 2020
        )


def invalid_empty_points(payload: dict[str, object]) -> None:
    payload["point_values"] = []


def invalid_epsg(payload: dict[str, object]) -> None:
    payload["coord_sys_info"] = {"EPSG": 3006, "name": "SWEREF99 TM"}


def invalid_array_lengths(payload: dict[str, object]) -> None:
    points = payload["point_values"]
    assert isinstance(points, list)
    assert points
    assert isinstance(points[0], dict)
    points[0]["t"] = [12.1]


def invalid_date(payload: dict[str, object]) -> None:
    dates = payload["dates"]
    assert isinstance(dates, list)
    dates[0] = "not-a-date"


def invalid_non_finite(payload: dict[str, object]) -> None:
    points = payload["point_values"]
    assert isinstance(points, list)
    assert points
    assert isinstance(points[0], dict)
    values = points[0]["t"]
    assert isinstance(values, list)
    values[0] = math.nan


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (invalid_empty_points, "structure is invalid"),
        (invalid_epsg, "coordinate system is invalid"),
        (invalid_array_lengths, "values do not match dates"),
        (invalid_date, "dates are invalid"),
        (invalid_non_finite, "contains invalid values"),
    ],
    ids=["empty-points", "wrong-epsg", "length-mismatch", "bad-date", "nan"],
)
async def test_daily_rejects_invalid_pthbv_schema(
    mutate: Callable[[dict[str, object]], None], message: str
) -> None:
    payload = complete_pthbv()
    mutate(payload)

    with pytest.raises(SmhiApiResponseError, match=message):
        await PthbvClient(StubApi(payload)).async_daily(
            Location("Göteborg", 57.71, 11.97),
            1991,
            2020,
            precipitation=True,
        )


@pytest.mark.parametrize("precipitation", [False, True])
@pytest.mark.parametrize(
    "years", [(1991, 2020), (1961, 2025), (2023, 2023), (2024, 2024)]
)
def test_validator_accepts_complete_cached_series_without_mutation_or_network(
    years: tuple[int, int], precipitation: bool, no_smhi_network: None
) -> None:
    cached = json.loads(json.dumps(complete_pthbv(*years)))
    point = cached["point_values"][0]
    if not precipitation:
        point.pop("p")
    for variable in point.keys() & {"t", "p"}:
        point[variable][:4] = [None, 0, -1.5, "2.5"]
    original = deepcopy(cached)

    result = validate_daily_data(cached, *years, precipitation=precipitation)

    assert result is cached
    assert cached == original
    assert values_for_calendar_date(result, 1, 1, "t") == dict.fromkeys(
        range(years[0] + 1, years[1] + 1), 12.1
    )


@pytest.mark.parametrize("payload", [None, [], "invalid", True, 4326, {}])
def test_validator_rejects_invalid_cached_root(payload: object) -> None:
    cached = json.loads(json.dumps(payload))

    with pytest.raises(SmhiApiResponseError, match="structure is invalid"):
        validate_daily_data(cached, 1991, 2020)


@pytest.mark.parametrize("missing", ["dates", "point_values", "coord_sys_info"])
def test_validator_requires_cached_schema(missing: str) -> None:
    payload = complete_pthbv()
    payload.pop(missing)
    cached = json.loads(json.dumps(payload))

    with pytest.raises(SmhiApiResponseError, match="is invalid"):
        validate_daily_data(cached, 1991, 2020)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("dates", None, "structure is invalid"),
        ("dates", "1991-01-01", "structure is invalid"),
        ("point_values", {}, "structure is invalid"),
        ("point_values", [], "structure is invalid"),
        ("point_values", [{}, {}], "structure is invalid"),
        ("point_values", [None], "point data is invalid"),
        ("coord_sys_info", None, "coordinate system is invalid"),
        ("coord_sys_info", "EPSG:4326", "coordinate system is invalid"),
        ("coord_sys_info", {}, "coordinate system is invalid"),
        ("coord_sys_info", {"EPSG": 3006}, "coordinate system is invalid"),
        ("coord_sys_info", {"EPSG": "4326"}, "coordinate system is invalid"),
    ],
)
def test_validator_rejects_bad_cached_schema(
    field: str, value: object, message: str
) -> None:
    payload = complete_pthbv()
    payload[field] = value
    cached = json.loads(json.dumps(payload))

    with pytest.raises(SmhiApiResponseError, match=message):
        validate_daily_data(cached, 1991, 2020, precipitation=True)


@pytest.mark.parametrize("variable", ["t", "p"])
@pytest.mark.parametrize("values", [None, {}, "1.0", [], [1.0]])
def test_validator_requires_complete_requested_cached_variables(
    variable: str, values: object
) -> None:
    cached = json.loads(json.dumps(complete_pthbv()))
    if values is None:
        cached["point_values"][0].pop(variable)
    else:
        cached["point_values"][0][variable] = values

    with pytest.raises(SmhiApiResponseError, match="values do not match dates"):
        validate_daily_data(cached, 1991, 2020, precipitation=True)


@pytest.mark.parametrize(
    "case", ["empty", "missing-start", "missing-end", "gap", "duplicate", "unordered"]
)
def test_validator_rejects_incomplete_or_unordered_cached_period(case: str) -> None:
    cached = json.loads(json.dumps(complete_pthbv()))
    dates = cached["dates"]
    arrays = [dates, cached["point_values"][0]["t"], cached["point_values"][0]["p"]]
    if case == "empty":
        for array in arrays:
            array.clear()
    elif case in {"missing-start", "missing-end", "gap"}:
        index = {"missing-start": 0, "missing-end": -1, "gap": 100}[case]
        for array in arrays:
            array.pop(index)
    elif case == "duplicate":
        dates[1] = dates[0]
    else:
        dates[1], dates[2] = dates[2], dates[1]

    with pytest.raises(SmhiApiResponseError, match="period is incomplete or unordered"):
        validate_daily_data(cached, 1991, 2020, precipitation=True)


@pytest.mark.parametrize("years", [(1992, 2021), (1991, 2019), (1990, 2020)])
def test_validator_rejects_complete_cache_for_wrong_period(
    years: tuple[int, int],
) -> None:
    cached = json.loads(json.dumps(complete_pthbv()))

    with pytest.raises(SmhiApiResponseError, match="period is incomplete or unordered"):
        validate_daily_data(cached, *years)


@pytest.mark.parametrize(
    "value",
    [None, True, {}, [], 19910101, "bad-date", "1991-02-29", "1991-01-01T00:00:00"],
)
def test_validator_rejects_malformed_cached_dates(value: object) -> None:
    cached = json.loads(json.dumps(complete_pthbv()))
    cached["dates"][0] = value

    with pytest.raises(SmhiApiResponseError, match="dates are invalid"):
        validate_daily_data(cached, 1991, 2020)


@pytest.mark.parametrize("variable", ["t", "p"])
@pytest.mark.parametrize(
    "value",
    [True, False, {}, [], "invalid", "NaN", "Infinity", "-Infinity", 10**400],
    ids=["true", "false", "object", "array", "text", "nan", "inf", "-inf", "overflow"],
)
def test_validator_rejects_invalid_cached_measurements(
    variable: str, value: object
) -> None:
    cached = json.loads(json.dumps(complete_pthbv()))
    cached["point_values"][0][variable][0] = value

    with pytest.raises(SmhiApiResponseError, match="contains invalid values"):
        validate_daily_data(cached, 1991, 2020, precipitation=True)


@pytest.mark.parametrize("field", ["dates", "t"])
def test_validator_errors_do_not_expose_cached_content(field: str) -> None:
    cached = json.loads(json.dumps(complete_pthbv()))
    private_value = "private-location-from-cache"
    values = cached["dates"] if field == "dates" else cached["point_values"][0]["t"]
    values[0] = private_value

    with pytest.raises(SmhiApiResponseError) as error:
        validate_daily_data(cached, 1991, 2020)

    assert private_value not in "".join(traceback.format_exception(error.value))


def test_values_for_calendar_date_aligns_parallel_arrays() -> None:
    values = values_for_calendar_date(load_pthbv(), 9, 3, "t")

    assert values == {1991: 12.1, 1992: 13.0, 2020: 14.2}


def test_values_for_february_29_uses_only_real_leap_dates() -> None:
    values = values_for_calendar_date(load_pthbv(), 2, 29, "t")

    assert values == {1992: -1.2}


def test_values_skip_null_malformed_and_non_finite_values() -> None:
    payload = {
        "dates": ["1991-09-03", "1992-09-03", "bad-date", "2020-09-03"],
        "point_values": [{"t": [12.1, None, 13.0, "NaN"]}],
    }

    values = values_for_calendar_date(payload, 9, 3, "t")

    assert values == {1991: 12.1}
    assert all(math.isfinite(value) for value in values.values())


def test_values_return_empty_for_missing_point_or_variable() -> None:
    assert values_for_calendar_date({"dates": [], "point_values": []}, 9, 3, "t") == {}
    assert values_for_calendar_date(load_pthbv(), 9, 3, "unknown") == {}
