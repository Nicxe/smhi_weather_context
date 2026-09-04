"""Golden tests for weather-context time and statistical calculations.

Every expected value in this module is derived from a small, hand-checkable
fixture. The tests deliberately exercise physical UTC hours rather than using
wall-clock strings as time-series keys.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from math import ceil
from zoneinfo import ZoneInfo

import pytest

from custom_components.smhi_weather_context.calculations import (
    compass_direction,
    completed_local_hour,
    corresponding_hour,
    day_mean_through_hour,
    hourly_mean,
    local_hour_slots,
    mean_with_minimum,
    observations_for_local_hour,
    percentile_rank,
    vector_mean_degrees,
)
from custom_components.smhi_weather_context.models import Observation

STOCKHOLM = ZoneInfo("Europe/Stockholm")


def _observation(timestamp: datetime, value: float, quality: str = "G") -> Observation:
    """Create one normalized observation for a golden fixture."""
    assert timestamp.tzinfo is not None
    return Observation(time=timestamp, value=value, quality=quality)


def _slot(local_date: date, hour: int, fold: int = 0) -> datetime:
    """Return one physical local slot identified by wall hour and fold."""
    return next(
        slot
        for slot in local_hour_slots(local_date)
        if slot.hour == hour and slot.fold == fold
    )


def _one_per_hour(
    slots: list[datetime], count: int, *, value: float = 1.0
) -> list[Observation]:
    """Create one valid observation halfway through each selected hour."""
    return [
        _observation(slot.astimezone(UTC) + timedelta(minutes=30), value)
        for slot in slots[:count]
    ]


def test_spring_dst_day_has_23_physical_hours_and_no_two_oclock() -> None:
    """2024-03-31 jumps directly from 01 CET to 03 CEST."""
    slots = local_hour_slots(date(2024, 3, 31))

    assert len(slots) == 23
    assert [(slot.hour, slot.fold) for slot in slots[:4]] == [
        (0, 0),
        (1, 0),
        (3, 0),
        (4, 0),
    ]
    assert all(slot.hour != 2 for slot in slots)
    assert slots[0].astimezone(UTC) == datetime(2024, 3, 30, 23, tzinfo=UTC)
    assert slots[2].astimezone(UTC) == datetime(2024, 3, 31, 1, tzinfo=UTC)
    assert all(
        right.astimezone(UTC) - left.astimezone(UTC) == timedelta(hours=1)
        for left, right in pairwise(slots)
    )


def test_autumn_dst_day_has_two_distinct_two_oclock_hours() -> None:
    """2024-10-27 contains independently addressable 02#1 and 02#2."""
    slots = local_hour_slots(date(2024, 10, 27))

    assert len(slots) == 25
    assert [(slot.hour, slot.fold) for slot in slots[:6]] == [
        (0, 0),
        (1, 0),
        (2, 0),
        (2, 1),
        (3, 0),
        (4, 0),
    ]

    first_two = _slot(date(2024, 10, 27), 2, fold=0)
    second_two = _slot(date(2024, 10, 27), 2, fold=1)
    assert first_two.utcoffset() == timedelta(hours=2)
    assert second_two.utcoffset() == timedelta(hours=1)
    assert first_two.astimezone(UTC) == datetime(2024, 10, 27, 0, tzinfo=UTC)
    assert second_two.astimezone(UTC) == datetime(2024, 10, 27, 1, tzinfo=UTC)


def test_completed_hour_tracks_each_autumn_fold_in_utc_order() -> None:
    """The repeated wall hour must be completed in physical UTC order."""
    during_second_two = datetime(2024, 10, 27, 1, 30, tzinfo=UTC)
    after_second_two = datetime(2024, 10, 27, 2, 30, tzinfo=UTC)

    first_completed = completed_local_hour(during_second_two)
    second_completed = completed_local_hour(after_second_two)

    assert (first_completed.hour, first_completed.fold) == (2, 0)
    assert first_completed.astimezone(UTC) == datetime(2024, 10, 27, 0, tzinfo=UTC)
    assert (second_completed.hour, second_completed.fold) == (2, 1)
    assert second_completed.astimezone(UTC) == datetime(2024, 10, 27, 1, tzinfo=UTC)


def test_completed_hour_skips_nonexistent_spring_hour() -> None:
    """At 03:30 CEST, 01 CET is the latest physically completed hour."""
    now = datetime(2024, 3, 31, 1, 30, tzinfo=UTC)

    completed = completed_local_hour(now)

    assert (completed.hour, completed.fold) == (1, 0)
    assert completed.astimezone(UTC) == datetime(2024, 3, 31, 0, tzinfo=UTC)


def test_hour_observations_do_not_mix_autumn_folds_or_end_boundary() -> None:
    """The end boundary belongs to the next physical hour."""
    first_two = _slot(date(2024, 10, 27), 2, fold=0)
    second_two = _slot(date(2024, 10, 27), 2, fold=1)
    observations = [
        _observation(datetime(2024, 10, 27, 0, 15, tzinfo=UTC), 2.0),
        _observation(datetime(2024, 10, 27, 0, 59, tzinfo=UTC), 4.0),
        _observation(datetime(2024, 10, 27, 1, 0, tzinfo=UTC), 20.0),
        _observation(datetime(2024, 10, 27, 1, 30, tzinfo=UTC), 22.0),
    ]

    first = observations_for_local_hour(observations, first_two)
    second = observations_for_local_hour(observations, second_two)

    assert [item.value for item in first] == [2.0, 4.0]
    assert [item.value for item in second] == [20.0, 22.0]
    assert hourly_mean(observations, first_two) == 3.0
    assert hourly_mean(observations, second_two) == 21.0


def test_corresponding_hour_preserves_fold_and_never_reuses_first_occurrence() -> None:
    """A historical singleton 02 may not stand in for current 02#2."""
    first_two = _slot(date(2024, 10, 27), 2, fold=0)
    second_two = _slot(date(2024, 10, 27), 2, fold=1)

    historical_first = corresponding_hour(first_two, 2023)

    assert historical_first is not None
    assert historical_first.date() == date(2023, 10, 27)
    assert (historical_first.hour, historical_first.fold) == (2, 0)
    assert corresponding_hour(second_two, 2023) is None


@pytest.mark.parametrize(
    ("local_date", "expected_hours"),
    [
        pytest.param(date(2024, 1, 15), 1, id="one-hour-requires-one"),
        pytest.param(date(2024, 1, 15), 2, id="two-hours-require-two"),
        pytest.param(date(2024, 1, 15), 3, id="three-hours-require-three"),
        pytest.param(date(2024, 1, 15), 4, id="four-hours-require-three"),
        pytest.param(date(2024, 1, 15), 5, id="five-hours-require-four"),
        pytest.param(date(2024, 3, 31), 23, id="spring-day-requires-eighteen"),
        pytest.param(date(2024, 1, 15), 24, id="normal-day-requires-eighteen"),
        pytest.param(date(2024, 10, 27), 25, id="autumn-day-requires-nineteen"),
    ],
)
def test_coverage_uses_exact_75_percent_ceiling(
    local_date: date, expected_hours: int
) -> None:
    """Passing count is ceil(3E/4); one fewer valid hour must fail."""
    slots = local_hour_slots(local_date)[:expected_hours]
    target = slots[-1]
    required = ceil(0.75 * expected_hours)

    passing = day_mean_through_hour(_one_per_hour(slots, required), target)
    failing = day_mean_through_hour(_one_per_hour(slots, required - 1), target)

    assert passing == (1.0, required, expected_hours)
    assert failing == (None, required - 1, expected_hours)


def test_spring_day_mean_uses_all_23_physical_hours() -> None:
    """Values 1 through 23 have the hand-calculated mean 12."""
    slots = local_hour_slots(date(2024, 3, 31))
    observations = [
        _observation(slot.astimezone(UTC) + timedelta(minutes=30), index)
        for index, slot in enumerate(slots, start=1)
    ]

    result = day_mean_through_hour(observations, slots[-1])

    assert result == (12.0, 23, 23)


def test_autumn_day_mean_counts_both_repeated_hours() -> None:
    """Both 02 values contribute: (2 + 20 + 23*0) / 25 = 0.88."""
    slots = local_hour_slots(date(2024, 10, 27))
    observations = []
    for slot in slots:
        value = 0.0
        if (slot.hour, slot.fold) == (2, 0):
            value = 2.0
        elif (slot.hour, slot.fold) == (2, 1):
            value = 20.0
        observations.append(
            _observation(slot.astimezone(UTC) + timedelta(minutes=30), value)
        )

    result = day_mean_through_hour(observations, slots[-1])

    assert result == (0.88, 25, 25)


def test_day_mean_weights_physical_hours_not_raw_observation_count() -> None:
    """Hour means 5 and 20 must be equally weighted: (5 + 20) / 2 = 12.5."""
    slots = local_hour_slots(date(2024, 1, 15))[:2]
    first_start = slots[0].astimezone(UTC)
    second_start = slots[1].astimezone(UTC)
    observations = [
        _observation(first_start + timedelta(minutes=10), 0.0),
        _observation(first_start + timedelta(minutes=40), 10.0),
        _observation(second_start + timedelta(minutes=30), 20.0),
    ]

    result = day_mean_through_hour(observations, slots[-1])

    assert result == (12.5, 2, 2)


def test_february_29_has_no_implicit_replacement_date() -> None:
    """A non-leap comparison year may use neither February 28 nor March 1."""
    leap_hour = datetime(2024, 2, 29, 10, tzinfo=STOCKHOLM)

    assert corresponding_hour(leap_hour, 2023) is None

    historical_leap_hour = corresponding_hour(leap_hour, 2020)
    assert historical_leap_hour is not None
    assert historical_leap_hour.date() == date(2020, 2, 29)
    assert historical_leap_hour.hour == 10


def test_ten_year_mean_requires_seven_equally_weighted_years() -> None:
    """The seven yearly means 1..7 average to 4; six years are insufficient."""
    seven_years = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, None, None, None]
    six_years = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, None, None, None, None]

    assert mean_with_minimum(seven_years, minimum_samples=7) == (4.0, 7)
    assert mean_with_minimum(six_years, minimum_samples=7) == (None, 6)


def test_february_29_ten_year_window_cannot_reach_fixed_minimum() -> None:
    """2014..2023 contain only the leap dates 2016 and 2020."""
    leap_day_year_values = [None, None, 2.0, None, None, None, 4.0, None, None, None]

    assert mean_with_minimum(leap_day_year_values, minimum_samples=7) == (None, 2)


def test_climate_normal_1991_2020_requires_24_valid_years() -> None:
    """Twenty-four values 1..24 average to 12.5; twenty-three must fail."""
    valid_24 = [float(value) for value in range(1, 25)] + [None] * 6
    valid_23 = [float(value) for value in range(1, 24)] + [None] * 7

    assert len(valid_24) == 30
    assert mean_with_minimum(valid_24, minimum_samples=24) == (12.5, 24)
    assert mean_with_minimum(valid_23, minimum_samples=24) == (None, 23)


def test_february_29_climate_normal_has_only_eight_possible_samples() -> None:
    """1991..2020 contain eight leap days, below the fixed minimum of 24."""
    leap_years = {1992, 1996, 2000, 2004, 2008, 2012, 2016, 2020}
    values = [1.0 if year in leap_years else None for year in range(1991, 2021)]

    assert mean_with_minimum(values, minimum_samples=24) == (None, 8)


def test_percentile_uses_exact_midrank_for_ties() -> None:
    """For 20, (one lower + half of three ties) / eight = 31.25 percent."""
    samples = [10.0, 20.0, 20.0, 20.0, 30.0, 40.0, 50.0, 60.0]

    assert percentile_rank(20.0, samples, minimum_samples=7) == 31.25


def test_percentile_all_ties_is_50_and_minimum_is_enforced() -> None:
    """All ties have midrank 50; six samples do not satisfy a minimum of seven."""
    assert percentile_rank(20.0, [20.0] * 7, minimum_samples=7) == 50.0
    assert percentile_rank(20.0, [20.0] * 6, minimum_samples=7) is None


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        pytest.param(5.0, 0.0, id="below-all"),
        pytest.param(45.0, 100.0, id="above-all"),
    ],
)
def test_percentile_extremes(target: float, expected: float) -> None:
    """The empirical midrank scale has exact endpoints zero and one hundred."""
    assert percentile_rank(target, [10.0, 20.0, 30.0, 40.0]) == expected


def test_circular_mean_crosses_north_instead_of_south() -> None:
    """Equal observations at 350 and 10 degrees have a northward mean of zero."""
    assert vector_mean_degrees([350.0, 10.0]) == pytest.approx(0.0, abs=1e-9)


def test_circular_mean_of_opposites_is_undefined() -> None:
    """Equal vectors at 0 and 180 degrees cancel exactly."""
    assert vector_mean_degrees([0.0, 180.0]) is None


def test_circular_mean_is_permutation_and_rotation_safe() -> None:
    """0 and 90 average to 45 regardless of order or full rotations."""
    assert vector_mean_degrees([0.0, 90.0]) == 45.0
    assert vector_mean_degrees([450.0, 360.0]) == 45.0
    assert vector_mean_degrees([90.0, 0.0]) == 45.0


@pytest.mark.parametrize(
    ("degrees", "expected"),
    [
        pytest.param(0.0, "N", id="north"),
        pytest.param(22.5, "NNO", id="north-northeast"),
        pytest.param(45.0, "NO", id="northeast"),
        pytest.param(67.5, "ONO", id="east-northeast"),
        pytest.param(90.0, "O", id="east"),
        pytest.param(112.5, "OSO", id="east-southeast"),
        pytest.param(135.0, "SO", id="southeast"),
        pytest.param(157.5, "SSO", id="south-southeast"),
        pytest.param(180.0, "S", id="south"),
        pytest.param(202.5, "SSV", id="south-southwest"),
        pytest.param(225.0, "SV", id="southwest"),
        pytest.param(247.5, "VSV", id="west-southwest"),
        pytest.param(270.0, "V", id="west"),
        pytest.param(292.5, "VNV", id="west-northwest"),
        pytest.param(315.0, "NV", id="northwest"),
        pytest.param(337.5, "NNV", id="north-northwest"),
    ],
)
def test_compass_direction_uses_swedish_16_sector_names(
    degrees: float, expected: str
) -> None:
    """Every sector centre maps to its Swedish abbreviation."""
    assert compass_direction(degrees) == expected


@pytest.mark.parametrize(
    ("degrees", "expected"),
    [
        pytest.param(11.249, "N", id="just-below-nno"),
        pytest.param(11.25, "NNO", id="nno-inclusive-boundary"),
        pytest.param(348.749, "NNV", id="just-below-north-wrap"),
        pytest.param(348.75, "N", id="north-wrap-inclusive-boundary"),
        pytest.param(-1.0, "N", id="negative-degree-normalization"),
        pytest.param(360.0, "N", id="full-turn-normalization"),
    ],
)
def test_compass_sector_boundaries_are_half_open(degrees: float, expected: str) -> None:
    """Sector boundaries are centred on multiples of 22.5 degrees."""
    assert compass_direction(degrees) == expected


def test_compass_direction_rejects_unavailable_and_nonfinite_values() -> None:
    """No textual direction may be fabricated without a finite angle."""
    assert compass_direction(None) is None
    assert compass_direction(float("nan")) is None
    assert compass_direction(float("inf")) is None
