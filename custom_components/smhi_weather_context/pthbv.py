"""PTHBV gridded climate data client."""

from __future__ import annotations

from datetime import date, timedelta
from itertools import pairwise
import math
from typing import Any

from .api import SmhiApiClient, SmhiApiResponseError, build_url
from .const import PTHBV_BASE_URL
from .models import Location


class PthbvClient:
    """Client for SMHI's official PTHBV point-download service."""

    def __init__(self, client: SmhiApiClient) -> None:
        self._client = client

    async def async_daily(
        self,
        location: Location,
        start_year: int,
        end_year: int,
        *,
        precipitation: bool = False,
    ) -> dict[str, Any]:
        """Fetch daily temperature and optional precipitation for one point."""
        base = (
            f"{PTHBV_BASE_URL}/from/{start_year}/to/{end_year}/period/daily/data.json"
        )
        variables = ["t", "p"] if precipitation else ["t"]
        url = build_url(
            base,
            {
                "epsg": 4326,
                "ll": f"{location.longitude:.4f},{location.latitude:.4f}",
                "var": variables,
            },
        )
        data = await self._client.async_get_json(url)
        dates = data.get("dates")
        points = data.get("point_values")
        if (
            not isinstance(dates, list)
            or not isinstance(points, list)
            or len(points) != 1
        ):
            raise SmhiApiResponseError("PTHBV response structure is invalid")
        point = points[0]
        if not isinstance(point, dict):
            raise SmhiApiResponseError("PTHBV point data is invalid")
        coordinate_system = data.get("coord_sys_info")
        if (
            not isinstance(coordinate_system, dict)
            or coordinate_system.get("EPSG") != 4326
        ):
            raise SmhiApiResponseError("PTHBV coordinate system is invalid")
        try:
            parsed_dates = [date.fromisoformat(str(value)) for value in dates]
        except ValueError as err:
            raise SmhiApiResponseError("PTHBV dates are invalid") from err
        if (
            not parsed_dates
            or parsed_dates != sorted(set(parsed_dates))
            or parsed_dates[0] != date(start_year, 1, 1)
            or parsed_dates[-1] != date(end_year, 12, 31)
            or len(parsed_dates)
            != (date(end_year, 12, 31) - date(start_year, 1, 1)).days + 1
            or any(
                right - left != timedelta(days=1)
                for left, right in pairwise(parsed_dates)
            )
        ):
            raise SmhiApiResponseError("PTHBV period is incomplete or unordered")
        for variable in variables:
            values = point.get(variable)
            if not isinstance(values, list) or len(values) != len(dates):
                raise SmhiApiResponseError("PTHBV values do not match dates")
            for value in values:
                if value is None:
                    continue
                try:
                    finite = math.isfinite(float(value))
                except (TypeError, ValueError) as err:
                    raise SmhiApiResponseError("PTHBV contains invalid values") from err
                if not finite:
                    raise SmhiApiResponseError("PTHBV contains invalid values")
        return data


def values_for_calendar_date(
    data: dict[str, Any], month: int, day: int, variable: str
) -> dict[int, float]:
    """Extract one calendar date per available PTHBV year."""
    dates = data.get("dates", [])
    points = data.get("point_values", [])
    if not points or not isinstance(points[0], dict):
        return {}
    values = points[0].get(variable, [])
    result: dict[int, float] = {}
    for raw_date, raw_value in zip(dates, values, strict=False):
        try:
            parsed = date.fromisoformat(str(raw_date))
            value = float(raw_value)
        except TypeError, ValueError:
            continue
        if math.isfinite(value) and parsed.month == month and parsed.day == day:
            result[parsed.year] = value
    return result
