"""MetObs station discovery and observation parsing."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from io import StringIO
import math
from typing import Any

from .api import SmhiApiClient, SmhiApiResponseError, build_url
from .const import METOBS_BASE_URL
from .models import Location, Observation, Station


def _from_millis(value: float) -> datetime:
    return datetime.fromtimestamp(float(value) / 1000, tz=UTC)


def _distance_km(a: Location, latitude: float, longitude: float) -> float:
    radius = 6371.0088
    lat1, lat2 = math.radians(a.latitude), math.radians(latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(longitude - a.longitude)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


class MetObsClient:
    """Documented MetObs download API."""

    def __init__(self, client: SmhiApiClient) -> None:
        self._client = client

    async def async_stations(
        self, parameter: int, location: Location, oldest_year: int
    ) -> list[Station]:
        """Return active stations with enough metadata history, ranked deterministically."""
        data = await self._client.async_get_json(
            build_url(
                f"{METOBS_BASE_URL}/parameter/{parameter}.json",
                {"measuringStations": "core"},
            )
        )
        raw_stations = data.get("station")
        if not isinstance(raw_stations, list):
            raise SmhiApiResponseError("MetObs station list is missing")
        cutoff = datetime(oldest_year, 1, 1, tzinfo=UTC)
        stations: list[Station] = []
        for raw in raw_stations:
            if not isinstance(raw, dict) or not raw.get("active"):
                continue
            try:
                start = _from_millis(raw["from"])
                end = _from_millis(raw["to"])
                station = Station(
                    station_id=int(raw["id"]),
                    name=str(raw["name"]),
                    latitude=float(raw["latitude"]),
                    longitude=float(raw["longitude"]),
                    height=float(raw["height"])
                    if raw.get("height") is not None
                    else None,
                    active=True,
                    from_time=start,
                    to_time=end,
                    distance_km=round(
                        _distance_km(
                            location, float(raw["latitude"]), float(raw["longitude"])
                        ),
                        1,
                    ),
                    has_current=True,
                    has_archive=start <= cutoff,
                )
            except KeyError, TypeError, ValueError, OverflowError:
                continue
            if station.has_archive:
                stations.append(station)
        return sorted(
            stations,
            key=lambda item: (
                not item.has_archive,
                not item.active,
                item.distance_km,
                item.station_id,
            ),
        )

    async def async_validate_station(self, parameter: int, station_id: int) -> bool:
        """Confirm current and corrected periods for a selected station."""
        data = await self._client.async_get_json(
            f"{METOBS_BASE_URL}/parameter/{parameter}/station/{station_id}.json"
        )
        periods = {
            item.get("key") for item in data.get("period", []) if isinstance(item, dict)
        }
        return {"latest-day", "corrected-archive"}.issubset(periods)

    async def async_latest_day(
        self, parameter: int, station_id: int
    ) -> tuple[list[Observation], dict[str, Any]]:
        """Fetch the latest day for one parameter and station."""
        data = await self._client.async_get_json(
            f"{METOBS_BASE_URL}/parameter/{parameter}/station/{station_id}/"
            "period/latest-day/data.json"
        )
        values = data.get("value")
        if not isinstance(values, list):
            raise SmhiApiResponseError("MetObs values are missing")
        observations: list[Observation] = []
        for raw in values:
            if not isinstance(raw, dict):
                continue
            try:
                quality = str(raw.get("quality", "")).upper()
                value = float(raw["value"])
                if quality in {"G", "Y"} and math.isfinite(value):
                    observations.append(
                        Observation(
                            time=_from_millis(raw["date"]),
                            value=value,
                            quality=quality,
                        )
                    )
            except KeyError, TypeError, ValueError, OverflowError:
                continue
        return observations, data

    async def async_corrected_archive(self, parameter: int, station_id: int) -> str:
        """Fetch corrected historical CSV for one station and parameter."""
        return await self._client.async_get_text(
            f"{METOBS_BASE_URL}/parameter/{parameter}/station/{station_id}/"
            "period/corrected-archive/data.csv"
        )


def parse_archive_for_dates(
    text: str,
    *,
    month: int,
    day: int,
    years: set[int],
) -> list[Observation]:
    """Extract only relevant calendar dates from a MetObs archive CSV."""
    lines = text.splitlines()
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.startswith(("Datum;Tid (UTC)", "Datum;Tid"))
        ),
        None,
    )
    if header_index is None:
        raise SmhiApiResponseError("MetObs archive data header is missing")
    reader = csv.reader(StringIO("\n".join(lines[header_index + 1 :])), delimiter=";")
    observations: list[Observation] = []
    for row in reader:
        if len(row) < 4:
            continue
        try:
            date_value = datetime.strptime(row[0], "%Y-%m-%d").replace(tzinfo=UTC)
            if (
                date_value.year not in years
                or date_value.month != month
                or date_value.day != day
            ):
                continue
            timestamp = datetime.strptime(
                f"{row[0]} {row[1]}", "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=UTC)
            quality = row[3].strip().upper()
            value = float(row[2])
            if quality in {"G", "Y"} and math.isfinite(value):
                observations.append(
                    Observation(time=timestamp, value=value, quality=quality)
                )
        except ValueError, IndexError:
            continue
    return observations
