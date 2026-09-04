"""Negative privacy tests for config-entry diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from types import SimpleNamespace

import pytest

from custom_components.smhi_weather_context.diagnostics import (
    async_get_config_entry_diagnostics,
)

pytestmark = pytest.mark.asyncio

MAX_DIAGNOSTICS_BYTES = 256 * 1024
REDACTED = "**REDACTED**"


def _entry(
    *,
    source_status: dict[str, SimpleNamespace] | None = None,
    values: dict[str, object] | None = None,
    source_exception: Exception | None = None,
    comparison_years: tuple[int, ...] = (1, 2, 3, 10),
) -> SimpleNamespace:
    location = SimpleNamespace(
        name="PRIVATE LOCATION SENTINEL",
        latitude=57.708870001,
        longitude=11.974560001,
    )
    options = SimpleNamespace(
        location=location,
        comparison_years=comparison_years,
        temperature_station_id=71420,
        wind_station_id=72420,
        enable_temperature=True,
        enable_wind=True,
        enable_climate=True,
        enable_precipitation=False,
        api_token="PRIVATE TOKEN SENTINEL",
        raw_url="https://example.invalid/?lat=57.708870001&lon=11.974560001",
    )
    coordinator = SimpleNamespace(
        last_update_success=False,
        last_exception=source_exception,
        internal_secret="PRIVATE RUNTIME SENTINEL",
        data=SimpleNamespace(
            source_status=source_status or {},
            values=values or {},
            raw_payload={"secret": "PRIVATE PAYLOAD SENTINEL"},
        ),
    )
    return SimpleNamespace(
        title="PRIVATE ENTRY TITLE SENTINEL",
        data={
            "name": "PRIVATE CONFIG NAME SENTINEL",
            "latitude": 57.708870001,
            "longitude": 11.974560001,
            "token": "PRIVATE ENTRY TOKEN SENTINEL",
        },
        options={"contact": "private@example.invalid"},
        runtime_data=SimpleNamespace(options=options, coordinator=coordinator),
    )


def _serialized(payload: object) -> str:
    return json.dumps(payload, default=str, sort_keys=True)


async def test_diagnostics_schema_is_a_positive_allowlist() -> None:
    """Only explicitly approved diagnostic fields may be returned."""
    status = SimpleNamespace(
        available=True,
        stale=False,
        last_update=datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
        error=None,
        raw_response="PRIVATE STATUS PAYLOAD SENTINEL",
    )
    payload = await async_get_config_entry_diagnostics(
        SimpleNamespace(),
        _entry(source_status={"temperature": status}, values={"temperature": 18.5}),
    )

    assert set(payload) == {"entry", "coordinator"}
    assert set(payload["entry"]) == {
        "title",
        "location",
        "comparison_years",
        "temperature_station_id",
        "wind_station_id",
        "features",
    }
    assert set(payload["entry"]["features"]) == {
        "temperature",
        "wind",
        "climate",
        "precipitation",
    }
    assert set(payload["coordinator"]) == {
        "last_update_success",
        "last_exception",
        "source_status",
        "calculated_keys",
    }
    assert set(payload["coordinator"]["source_status"]["temperature"]) == {
        "available",
        "stale",
        "last_update",
        "error_type",
    }
    serialized = _serialized(payload)
    assert "PRIVATE TOKEN SENTINEL" not in serialized
    assert "PRIVATE RUNTIME SENTINEL" not in serialized
    assert "PRIVATE PAYLOAD SENTINEL" not in serialized
    assert "PRIVATE STATUS PAYLOAD SENTINEL" not in serialized


async def test_diagnostics_redacts_location_config_and_exception_details() -> None:
    """Coordinates, user labels, URLs and exception messages must not leak."""
    exception = RuntimeError(
        "request failed for https://example.invalid/?lat=57.708870001&lon=11.974560001"
    )
    payload = await async_get_config_entry_diagnostics(
        SimpleNamespace(), _entry(source_exception=exception)
    )
    serialized = _serialized(payload)

    assert payload["entry"]["title"] == REDACTED
    assert payload["entry"]["location"] == REDACTED
    assert payload["coordinator"]["last_exception"] == "RuntimeError"
    for secret in (
        "57.708870001",
        "11.974560001",
        "PRIVATE LOCATION SENTINEL",
        "PRIVATE ENTRY TITLE SENTINEL",
        "PRIVATE CONFIG NAME SENTINEL",
        "PRIVATE ENTRY TOKEN SENTINEL",
        "private@example.invalid",
        "https://example.invalid/",
    ):
        assert secret not in serialized


async def test_diagnostics_never_exposes_raw_source_error_text() -> None:
    """A provider-controlled error string must be reduced to a safe error type."""
    secret_error = (
        "ClientResponseError for https://example.invalid/archive?"
        "lat=57.708870001&lon=11.974560001 body=PRIVATE ERROR BODY SENTINEL"
    )
    status = SimpleNamespace(
        available=False,
        stale=True,
        last_update=None,
        error=secret_error,
    )
    payload = await async_get_config_entry_diagnostics(
        SimpleNamespace(), _entry(source_status={"temperature": status})
    )
    serialized = _serialized(payload)

    assert secret_error not in serialized
    assert "57.708870001" not in serialized
    assert "PRIVATE ERROR BODY SENTINEL" not in serialized


async def test_diagnostics_rejects_unapproved_dynamic_source_names() -> None:
    """Unexpected runtime source names must not expand the diagnostic schema."""
    safe_status = SimpleNamespace(
        available=False,
        stale=False,
        last_update=None,
        error=None,
    )
    payload = await async_get_config_entry_diagnostics(
        SimpleNamespace(),
        _entry(
            source_status={
                "temperature": safe_status,
                "PRIVATE SOURCE NAME SENTINEL": safe_status,
            }
        ),
    )

    assert set(payload["coordinator"]["source_status"]) == {"temperature"}
    assert "PRIVATE SOURCE NAME SENTINEL" not in _serialized(payload)


async def test_diagnostics_output_is_bounded() -> None:
    """Unexpectedly large runtime data must not create an oversized support bundle."""
    oversized_values = {
        f"unexpected_calculated_key_{index:05d}": index for index in range(30_000)
    }
    payload = await async_get_config_entry_diagnostics(
        SimpleNamespace(), _entry(values=oversized_values)
    )

    assert len(_serialized(payload).encode("utf-8")) <= MAX_DIAGNOSTICS_BYTES
