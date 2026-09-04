"""Privacy-safe diagnostics for SMHI Weather Context."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

ALLOWED_SOURCES = frozenset(
    {
        "temperature",
        "temperature_history",
        "wind_speed",
        "wind_direction",
        "wind_gust",
        "wind_history",
        "climate",
    }
)
SAFE_ERROR_TYPE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]{0,63}$")
SAFE_VALUE_KEY = re.compile(r"^(?:temperature|wind)_(?:same_hour|today_mean)_\d+_year$")
KNOWN_VALUE_KEYS = frozenset(
    {
        "temperature_now",
        "temperature_today_mean",
        "temperature_10_year_mean",
        "temperature_deviation_10_year",
        "temperature_climate_normal",
        "temperature_climate_anomaly",
        "temperature_historical_percentile",
        "temperature_historical_max",
        "temperature_historical_min",
        "wind_speed_now",
        "wind_direction",
        "wind_direction_degrees",
        "wind_gust",
        "wind_today_mean",
        "wind_10_year_mean",
        "wind_deviation_10_year",
        "wind_historical_percentile",
        "precipitation_climate_normal",
        "precipitation_10_year_mean",
        "precipitation_historical_max",
        "smhi_last_observation",
        "smhi_last_historical_update",
        "smhi_data_fresh",
    }
)


def _safe_error_type(value: str | None) -> str | None:
    """Return only a short class-like identifier, never provider text."""
    return value if value and SAFE_ERROR_TYPE.fullmatch(value) else None


def _safe_http_status(value: object) -> int | None:
    """Expose only an HTTP status number, never a provider-controlled string."""
    return value if type(value) is int and 100 <= value <= 599 else None


def _safe_timestamp(value: object) -> datetime | None:
    """Exclude unexpected text from timestamp fields."""
    return value if isinstance(value, datetime) else None


def _safe_calculated_keys(values: dict[str, Any]) -> list[str]:
    """Return a bounded allowlist of public entity keys."""
    return sorted(
        key
        for key in values
        if key in KNOWN_VALUE_KEYS or SAFE_VALUE_KEY.fullmatch(key)
    )[:128]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return bounded diagnostics without location or provider-response details."""
    options = entry.runtime_data.options
    coordinator = entry.runtime_data.coordinator
    source_status = getattr(
        coordinator, "source_status", coordinator.data.source_status
    )
    return {
        "entry": {
            "title": "**REDACTED**",
            "location": "**REDACTED**",
            "comparison_years": options.comparison_years,
            "temperature_station_id": options.temperature_station_id,
            "wind_station_id": options.wind_station_id,
            "features": {
                "temperature": options.enable_temperature,
                "wind": options.enable_wind,
                "climate": options.enable_climate,
                "precipitation": options.enable_precipitation,
            },
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": (
                type(coordinator.last_exception).__name__
                if coordinator.last_exception
                else None
            ),
            "source_status": {
                key: {
                    "available": status.available,
                    "stale": status.stale,
                    "last_update": _safe_timestamp(status.last_update),
                    "last_attempt": _safe_timestamp(
                        getattr(status, "last_attempt", None)
                    ),
                    "last_success": _safe_timestamp(
                        getattr(status, "last_success", None)
                    ),
                    "http_status": _safe_http_status(
                        getattr(status, "http_status", None)
                    ),
                    "error_type": _safe_error_type(status.error),
                }
                for key, status in source_status.items()
                if key in ALLOWED_SOURCES
            },
            "calculated_keys": _safe_calculated_keys(coordinator.data.values),
        },
    }
