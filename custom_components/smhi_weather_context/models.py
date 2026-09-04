"""Typed models for SMHI Weather Context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class DataQuality(StrEnum):
    """Normalized data quality."""

    GOOD = "good"
    STALE = "stale"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class Location:
    """A configured location."""

    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class Station:
    """A MetObs station for one parameter."""

    station_id: int
    name: str
    latitude: float
    longitude: float
    height: float | None
    active: bool
    from_time: datetime
    to_time: datetime
    distance_km: float = 0.0
    has_current: bool = False
    has_archive: bool = False


@dataclass(frozen=True, slots=True)
class Observation:
    """A timestamped meteorological observation."""

    time: datetime
    value: float
    quality: str = "G"


@dataclass(frozen=True, slots=True)
class SourceStatus:
    """Status for one upstream source."""

    available: bool
    stale: bool = False
    last_update: datetime | None = None
    error: str | None = None


@dataclass(slots=True)
class WeatherContextData:
    """Coordinator data exposed to entities."""

    values: dict[str, float | str | datetime | None] = field(default_factory=dict)
    attributes: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_status: dict[str, SourceStatus] = field(default_factory=dict)
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EntryOptions:
    """Normalized config entry settings."""

    location: Location
    temperature_station_id: int
    wind_station_id: int
    comparison_years: tuple[int, ...]
    enable_temperature: bool
    enable_wind: bool
    enable_climate: bool
    enable_precipitation: bool
    temperature_station_name: str = ""
    wind_station_name: str = ""
    temperature_station_distance_km: float | None = None
    wind_station_distance_km: float | None = None
