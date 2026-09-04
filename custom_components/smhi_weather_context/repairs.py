"""Actionable repair issues for SMHI Weather Context."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN


def _issue_id(entry_id: str, kind: str) -> str:
    return f"{entry_id}_{kind}_station"


def async_create_station_issue(
    hass: HomeAssistant, entry_id: str, kind: str, station_id: int
) -> None:
    """Create a repair instead of silently replacing a station."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id(entry_id, kind),
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="station_unavailable",
        translation_placeholders={"kind": kind, "station_id": str(station_id)},
    )


def async_clear_station_issue(hass: HomeAssistant, entry_id: str, kind: str) -> None:
    """Remove a station issue after explicit configuration is valid again."""
    ir.async_delete_issue(hass, DOMAIN, _issue_id(entry_id, kind))
