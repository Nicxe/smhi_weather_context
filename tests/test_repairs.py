"""Offline repair-registry contract tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.helpers import issue_registry as ir

from custom_components.smhi_weather_context.const import DOMAIN
from custom_components.smhi_weather_context.repairs import (
    async_clear_station_issue,
    async_create_station_issue,
)


def test_create_station_issue_is_actionable_and_stable() -> None:
    """An invalid station creates one deterministic, translated error repair."""
    hass = SimpleNamespace()

    with patch.object(ir, "async_create_issue") as create_issue:
        async_create_station_issue(hass, "entry-repair-qa", "wind", 72420)

    create_issue.assert_called_once_with(
        hass,
        DOMAIN,
        "entry-repair-qa_wind_station",
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="station_unavailable",
        translation_placeholders={"kind": "wind", "station_id": "72420"},
    )


def test_clear_station_issue_uses_same_identity() -> None:
    """Repair cleanup targets the exact issue created for that entry and source."""
    hass = SimpleNamespace()

    with patch.object(ir, "async_delete_issue") as delete_issue:
        async_clear_station_issue(hass, "entry-repair-qa", "temperature")

    delete_issue.assert_called_once_with(
        hass, DOMAIN, "entry-repair-qa_temperature_station"
    )
