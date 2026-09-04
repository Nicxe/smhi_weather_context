"""Pure weather-context calculations."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
import math
from statistics import fmean
from zoneinfo import ZoneInfo

from .const import MIN_HISTORY_COVERAGE, STOCKHOLM_TIME_ZONE
from .models import Observation

LOCAL_TZ = ZoneInfo(STOCKHOLM_TIME_ZONE)
COMPASS_16 = (
    "N",
    "NNO",
    "NO",
    "ONO",
    "O",
    "OSO",
    "SO",
    "SSO",
    "S",
    "SSV",
    "SV",
    "VSV",
    "V",
    "VNV",
    "NV",
    "NNV",
)


def valid_observations(observations: Iterable[Observation]) -> list[Observation]:
    """Return finite observations accepted by SMHI quality control."""
    return [
        item
        for item in observations
        if math.isfinite(item.value) and item.quality.upper() in {"G", "Y"}
    ]


def latest(observations: Iterable[Observation]) -> Observation | None:
    """Return the newest valid observation."""
    items = valid_observations(observations)
    return max(items, key=lambda item: item.time, default=None)


def completed_local_hour(now: datetime) -> datetime:
    """Return the start of the most recently completed local hour."""
    utc = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    return (utc - timedelta(hours=1)).astimezone(LOCAL_TZ)


def local_hour_slots(local_date: date) -> list[datetime]:
    """Return physical local-hour starts, preserving repeated DST hours."""
    midnight = datetime.combine(local_date, datetime.min.time(), tzinfo=LOCAL_TZ)
    next_midnight = datetime.combine(
        local_date + timedelta(days=1), datetime.min.time(), tzinfo=LOCAL_TZ
    )
    cursor = midnight.astimezone(UTC)
    end = next_midnight.astimezone(UTC)
    slots: list[datetime] = []
    while cursor < end:
        slots.append(cursor.astimezone(LOCAL_TZ))
        cursor += timedelta(hours=1)
    return slots


def corresponding_hour(target: datetime, year: int) -> datetime | None:
    """Find the same wall hour and DST occurrence in another year."""
    local = target.astimezone(LOCAL_TZ)
    try:
        target_date = date(year, local.month, local.day)
    except ValueError:
        return None
    matches = [
        slot
        for slot in local_hour_slots(target_date)
        if slot.hour == local.hour and slot.fold == local.fold
    ]
    return matches[0] if matches else None


def observations_for_local_hour(
    observations: Iterable[Observation], target: datetime
) -> list[Observation]:
    """Return observations within the exact local calendar hour."""
    target_local = target.astimezone(LOCAL_TZ)
    start_utc = target_local.astimezone(UTC)
    end_utc = start_utc + timedelta(hours=1)
    return [
        item
        for item in valid_observations(observations)
        if start_utc <= item.time.astimezone(UTC) < end_utc
    ]


def hourly_mean(observations: Iterable[Observation], target: datetime) -> float | None:
    """Calculate a mean for one exact local hour."""
    items = observations_for_local_hour(observations, target)
    return round(fmean(item.value for item in items), 2) if items else None


def _slots_through(target: datetime) -> list[datetime]:
    """Return physical local slots through an exact wall-hour occurrence."""
    local_target = target.astimezone(LOCAL_TZ)
    slots = local_hour_slots(local_target.date())
    for index, slot in enumerate(slots):
        if slot.hour == local_target.hour and slot.fold == local_target.fold:
            return slots[: index + 1]
    return []


def day_mean_through_hour(
    observations: Iterable[Observation],
    target: datetime,
    *,
    minimum_coverage: float = MIN_HISTORY_COVERAGE,
) -> tuple[float | None, int, int]:
    """Calculate local-day mean through target with an explicit coverage gate."""
    local_target = target.astimezone(LOCAL_TZ)
    slots = _slots_through(local_target)
    expected = len(slots)
    values: list[float] = []
    clean = valid_observations(observations)
    for slot in slots:
        start = slot.astimezone(UTC)
        end = start + timedelta(hours=1)
        items = [
            item.value for item in clean if start <= item.time.astimezone(UTC) < end
        ]
        if items:
            values.append(fmean(items))
    if expected == 0 or len(values) / expected < minimum_coverage:
        return None, len(values), expected
    return round(fmean(values), 2), len(values), expected


def mean_with_minimum(
    values: Iterable[float | None], minimum_samples: int
) -> tuple[float | None, int]:
    """Return a mean only when enough finite samples are present."""
    present = [value for value in values if value is not None and math.isfinite(value)]
    if len(present) < minimum_samples:
        return None, len(present)
    return round(fmean(present), 2), len(present)


def percentile_rank(
    value: float | None, samples: Sequence[float], *, minimum_samples: int = 1
) -> float | None:
    """Return midrank percentile (0-100), handling ties deterministically."""
    if value is None:
        return None
    clean = [sample for sample in samples if math.isfinite(sample)]
    if len(clean) < minimum_samples:
        return None
    below = sum(sample < value for sample in clean)
    equal = sum(sample == value for sample in clean)
    return 100 * (below + 0.5 * equal) / len(clean)


def vector_mean_degrees(values: Iterable[float]) -> float | None:
    """Return circular vector mean in meteorological degrees."""
    clean = [value % 360 for value in values if math.isfinite(value)]
    if not clean:
        return None
    sine = fmean(math.sin(math.radians(value)) for value in clean)
    cosine = fmean(math.cos(math.radians(value)) for value in clean)
    if math.isclose(sine, 0.0, abs_tol=1e-12) and math.isclose(
        cosine, 0.0, abs_tol=1e-12
    ):
        return None
    return round(math.degrees(math.atan2(sine, cosine)) % 360, 1) % 360


def compass_direction(degrees: float | None) -> str | None:
    """Map degrees to a 16-sector compass abbreviation."""
    if degrees is None or not math.isfinite(degrees):
        return None
    return COMPASS_16[int((degrees % 360 + 11.25) // 22.5) % 16]


def subtract(value: float | None, baseline: float | None) -> float | None:
    """Return a rounded anomaly when both operands are available."""
    if value is None or baseline is None:
        return None
    return round(value - baseline, 2)
