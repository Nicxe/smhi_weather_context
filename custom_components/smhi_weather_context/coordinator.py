"""Data coordinator for SMHI Weather Context."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from functools import partial
import json
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SmhiApiError
from .calculations import (
    compass_direction,
    completed_local_hour,
    corresponding_hour,
    day_mean_through_hour,
    hourly_mean,
    latest,
    mean_with_minimum,
    percentile_rank,
    subtract,
)
from .const import (
    ATTRIBUTION,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MIN_CLIMATE_NORMAL_SAMPLES,
    MIN_TEN_YEAR_SAMPLES,
    PARAM_TEMPERATURE,
    PARAM_WIND_DIRECTION,
    PARAM_WIND_GUST,
    PARAM_WIND_SPEED,
    STALE_AFTER,
)
from .metobs import MetObsClient, parse_archive_for_dates
from .models import EntryOptions, Observation, SourceStatus, WeatherContextData
from .pthbv import PthbvClient, values_for_calendar_date
from .repairs import async_clear_station_issue, async_create_station_issue
from .storage import SourceCache

_LOGGER = logging.getLogger(__name__)


class SmhiWeatherContextCoordinator(DataUpdateCoordinator[WeatherContextData]):
    """Coordinate current observations and daily historical context."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        config_entry: ConfigEntry,
        options: EntryOptions,
        metobs: MetObsClient,
        pthbv: PthbvClient,
        cache: SourceCache,
        history_enabled: bool = True,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_UPDATE_INTERVAL,
            config_entry=config_entry,
        )
        self.options = options
        self._entry = config_entry
        self.metobs = metobs
        self.pthbv = pthbv
        self.cache = cache
        self._history_date: date | None = None
        self._temperature_history: list[Observation] = []
        self._wind_history: list[Observation] = []
        self._climate_values: dict[int, float] = {}
        self._precipitation_values: dict[int, float] = {}
        self._history_cached_at: datetime | None = None
        self._history_status: dict[str, SourceStatus] = {}
        self._stations_validated_at: datetime | None = None
        self._invalid_station_kinds: set[str] = set()
        self._history_enabled = history_enabled

    def enable_history(self) -> None:
        """Allow heavy history initialization after first setup completes."""
        self._history_enabled = True

    async def _async_update_data(self) -> WeatherContextData:
        try:
            await self._async_validate_stations()
            return await self._async_build_data()
        except SmhiApiError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_validate_stations(self) -> None:
        now = datetime.now(UTC)
        if (
            self._stations_validated_at is not None
            and now - self._stations_validated_at < timedelta(days=1)
        ):
            return
        checks: list[tuple[str, int, int]] = []
        if self.options.enable_temperature:
            checks.append(
                (
                    "temperature",
                    PARAM_TEMPERATURE,
                    self.options.temperature_station_id,
                )
            )
        if self.options.enable_wind:
            checks.extend(
                ("wind", parameter, self.options.wind_station_id)
                for parameter in (
                    PARAM_WIND_SPEED,
                    PARAM_WIND_DIRECTION,
                    PARAM_WIND_GUST,
                )
            )
        results = await asyncio.gather(
            *(
                self.metobs.async_validate_station(parameter, station_id)
                for _, parameter, station_id in checks
            )
        )
        by_kind: dict[str, list[tuple[int, bool]]] = {}
        for (kind, _, station_id), valid in zip(checks, results, strict=True):
            by_kind.setdefault(kind, []).append((station_id, valid))
        for kind, validations in by_kind.items():
            invalid = next(
                ((station_id, valid) for station_id, valid in validations if not valid),
                None,
            )
            if invalid is not None:
                station_id = invalid[0]
                self._invalid_station_kinds.add(kind)
                async_create_station_issue(
                    self.hass,
                    self._entry.entry_id,
                    kind,
                    station_id,
                )
            else:
                self._invalid_station_kinds.discard(kind)
                async_clear_station_issue(self.hass, self._entry.entry_id, kind)
        self._stations_validated_at = now

    async def _async_build_data(self) -> WeatherContextData:
        now = datetime.now(UTC)
        target = completed_local_hour(now)
        current_tasks: dict[str, Any] = {}
        statuses: dict[str, SourceStatus] = {}
        if (
            self.options.enable_temperature
            and "temperature" in self._invalid_station_kinds
        ):
            statuses["temperature"] = SourceStatus(
                available=False, error="StationUnavailable"
            )
        elif self.options.enable_temperature:
            current_tasks["temperature"] = self.metobs.async_latest_day(
                PARAM_TEMPERATURE, self.options.temperature_station_id
            )
        if self.options.enable_wind and "wind" in self._invalid_station_kinds:
            statuses.update(
                {
                    key: SourceStatus(available=False, error="StationUnavailable")
                    for key in ("wind_speed", "wind_direction", "wind_gust")
                }
            )
        elif self.options.enable_wind:
            current_tasks.update(
                {
                    "wind_speed": self.metobs.async_latest_day(
                        PARAM_WIND_SPEED, self.options.wind_station_id
                    ),
                    "wind_direction": self.metobs.async_latest_day(
                        PARAM_WIND_DIRECTION, self.options.wind_station_id
                    ),
                    "wind_gust": self.metobs.async_latest_day(
                        PARAM_WIND_GUST, self.options.wind_station_id
                    ),
                }
            )
        names = list(current_tasks)
        results = await asyncio.gather(*current_tasks.values(), return_exceptions=True)
        current: dict[str, tuple[list[Observation], dict[str, Any]]] = {}
        for name, result in zip(names, results, strict=True):
            if isinstance(result, BaseException):
                statuses[name] = SourceStatus(
                    available=False, error=type(result).__name__
                )
                continue
            current[name] = result
            latest_item = latest(result[0])
            stale = latest_item is None or now - latest_item.time > STALE_AFTER
            statuses[name] = SourceStatus(
                available=latest_item is not None,
                stale=stale,
                last_update=latest_item.time if latest_item else None,
            )

        if not current and names:
            raise UpdateFailed("No current SMHI source is available")

        if self._history_enabled and self._history_date != target.date():
            await self._async_load_history(target)

        data = WeatherContextData(
            source_status={**statuses, **self._history_status}, updated_at=now
        )
        if "temperature" in current:
            self._populate_temperature(data, current["temperature"][0], target, now)
        if "wind_speed" in current:
            self._populate_wind(
                data,
                current["wind_speed"][0],
                current.get("wind_direction", ([], {}))[0],
                current.get("wind_gust", ([], {}))[0],
                target,
                now,
            )
        latest_current = [
            item
            for observations, _raw in current.values()
            if (item := latest(observations)) is not None
        ]
        data.values["smhi_last_observation"] = (
            max(item.time for item in latest_current) if latest_current else None
        )
        if self.options.enable_climate:
            self._populate_climate(data, target)
        data.values["smhi_last_historical_update"] = self._history_cached_at
        data.values["smhi_data_fresh"] = all(
            status.available and not status.stale
            for status in data.source_status.values()
        )
        return data

    async def _async_load_history(self, target: datetime) -> None:
        years_back = set(self.options.comparison_years) | set(range(1, 11))
        years = {target.year - offset for offset in years_back}
        tasks: dict[str, Any] = {}
        if (
            self.options.enable_temperature
            and "temperature" not in self._invalid_station_kinds
        ):
            tasks["temperature"] = self._async_archive(
                f"temperature_archive_{self.options.temperature_station_id}",
                PARAM_TEMPERATURE,
                self.options.temperature_station_id,
            )
        if self.options.enable_wind and "wind" not in self._invalid_station_kinds:
            tasks["wind"] = self._async_archive(
                f"wind_archive_{self.options.wind_station_id}",
                PARAM_WIND_SPEED,
                self.options.wind_station_id,
            )
        if self.options.enable_climate:
            tasks["climate"] = self._async_pthbv(target)
        names = list(tasks)
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        had_error = False
        for name, result in zip(names, results, strict=True):
            previous_status = self._history_status.get(name)
            if isinstance(result, BaseException):
                had_error = True
                self._history_status[name] = SourceStatus(
                    available=False, error=type(result).__name__
                )
                if previous_status is None or previous_status.available:
                    _LOGGER.warning(
                        "SMHI %s history is unavailable (%s)",
                        name,
                        type(result).__name__,
                    )
                continue
            self._history_status[name] = SourceStatus(
                available=True, last_update=datetime.now(UTC)
            )
            try:
                if name == "temperature":
                    self._temperature_history = await self.hass.async_add_executor_job(
                        partial(
                            parse_archive_for_dates,
                            result,
                            month=target.month,
                            day=target.day,
                            years=years,
                        )
                    )
                elif name == "wind":
                    self._wind_history = await self.hass.async_add_executor_job(
                        partial(
                            parse_archive_for_dates,
                            result,
                            month=target.month,
                            day=target.day,
                            years=years,
                        )
                    )
                elif name == "climate":
                    self._climate_values = values_for_calendar_date(
                        result, target.month, target.day, "t"
                    )
                    self._precipitation_values = values_for_calendar_date(
                        result, target.month, target.day, "p"
                    )
            except SmhiApiError, TypeError, ValueError:
                had_error = True
                self._history_status[name] = SourceStatus(
                    available=False, error="HistoryValidationError"
                )
                if previous_status is None or previous_status.available:
                    _LOGGER.warning("SMHI %s history could not be validated", name)
            else:
                if previous_status is not None and not previous_status.available:
                    _LOGGER.info("SMHI %s history is available again", name)
        self._history_date = None if had_error else target.date()
        self._history_cached_at = datetime.now(UTC)

    async def _async_archive(self, key: str, parameter: int, station_id: int) -> str:
        fresh = await self.cache.async_get(key, max_age=timedelta(days=28))
        if fresh:
            return fresh.payload
        try:
            payload = await self.metobs.async_corrected_archive(parameter, station_id)
        except SmhiApiError:
            stale = await self.cache.async_get(key)
            if stale:
                return stale.payload
            raise
        await self.cache.async_set(
            key, payload, {"parameter": parameter, "station_id": station_id}
        )
        return payload

    async def _async_pthbv(self, target: datetime) -> dict[str, Any]:
        location_identity = (
            f"{self.options.location.latitude:.4f}_"
            f"{self.options.location.longitude:.4f}_"
            f"p{int(self.options.enable_precipitation)}"
        )
        key = f"pthbv_daily_{location_identity}_through_{target.year - 1}"
        fresh = await self.cache.async_get(key, max_age=timedelta(days=28))
        if fresh:
            return self._decode_cached_pthbv(fresh.payload)
        try:
            data = await self.pthbv.async_daily(
                self.options.location,
                1961,
                target.year - 1,
                precipitation=self.options.enable_precipitation,
            )
        except SmhiApiError:
            stale = await self.cache.async_get(key)
            if stale:
                return self._decode_cached_pthbv(stale.payload)
            raise
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        await self.cache.async_set(key, payload, {"source": "PTHBV"})
        return data

    @staticmethod
    def _decode_cached_pthbv(payload: str) -> dict[str, Any]:
        """Decode a validated object root from private cache."""
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise SmhiApiError("Cached PTHBV data is invalid")
        return value

    @staticmethod
    def _target_for_year(target: datetime, year: int) -> datetime | None:
        return corresponding_hour(target, year)

    def _history_metrics(
        self, observations: list[Observation], target: datetime
    ) -> tuple[dict[int, float | None], dict[int, float | None]]:
        hourly: dict[int, float | None] = {}
        daily: dict[int, float | None] = {}
        for offset in sorted(set(self.options.comparison_years) | set(range(1, 11))):
            historical_target = self._target_for_year(target, target.year - offset)
            if historical_target is None:
                hourly[offset] = None
                daily[offset] = None
                continue
            hourly[offset] = hourly_mean(observations, historical_target)
            daily[offset] = day_mean_through_hour(observations, historical_target)[0]
        return hourly, daily

    def _common_attributes(
        self,
        station_id: int | None,
        observation_time: datetime | None,
        sample_count: int | None = None,
        source: str = "MetObs",
        *,
        station_name: str = "",
        station_distance_km: float | None = None,
        comparison_period: str | None = None,
        data_quality: str = "good",
        quality_flag: str | None = None,
        last_source_update: datetime | None = None,
    ) -> dict[str, Any]:
        attributes: dict[str, Any] = {
            "source_product": source,
            "station_id": station_id,
            "station_name": station_name or None,
            "station_distance_km": station_distance_km,
            "observation_time": observation_time,
            "comparison_period": comparison_period,
            "sample_count": sample_count,
            "data_quality": data_quality,
            "quality_flag": quality_flag,
            "last_source_update": last_source_update or observation_time,
            "attribution": ATTRIBUTION,
        }
        return {key: value for key, value in attributes.items() if value is not None}

    def _populate_temperature(
        self,
        data: WeatherContextData,
        current: list[Observation],
        target: datetime,
        now: datetime,
    ) -> None:
        current_latest = latest(current)
        today_mean, today_count, _ = day_mean_through_hour(current, target)
        historical_hour, historical_day = self._history_metrics(
            self._temperature_history, target
        )
        ten_mean, ten_count = mean_with_minimum(
            (historical_day[offset] for offset in range(1, 11)),
            MIN_TEN_YEAR_SAMPLES,
        )
        historical_samples = [
            value for value in historical_day.values() if value is not None
        ]
        data.values.update(
            {
                "temperature_now": current_latest.value if current_latest else None,
                "temperature_today_mean": today_mean,
                "temperature_10_year_mean": ten_mean,
                "temperature_deviation_10_year": subtract(today_mean, ten_mean),
                "temperature_historical_percentile": percentile_rank(
                    today_mean,
                    historical_samples,
                    minimum_samples=MIN_TEN_YEAR_SAMPLES,
                ),
                "temperature_historical_max": max(historical_samples, default=None),
                "temperature_historical_min": min(historical_samples, default=None),
            }
        )
        station_id = self.options.temperature_station_id
        for offset in self.options.comparison_years:
            hour_key = f"temperature_same_hour_{offset}_year"
            day_key = f"temperature_today_mean_{offset}_year"
            data.values[hour_key] = historical_hour.get(offset)
            data.values[day_key] = historical_day.get(offset)
            for key in (hour_key, day_key):
                value = data.values[key]
                data.attributes[key] = self._common_attributes(
                    station_id,
                    target,
                    1 if value is not None else 0,
                    station_name=self.options.temperature_station_name,
                    station_distance_km=self.options.temperature_station_distance_km,
                    comparison_period=f"{offset} year",
                    data_quality="good" if value is not None else "unavailable",
                    last_source_update=self._history_cached_at,
                )
        data.attributes["temperature_now"] = self._common_attributes(
            station_id,
            current_latest.time if current_latest else None,
            station_name=self.options.temperature_station_name,
            station_distance_km=self.options.temperature_station_distance_km,
            data_quality=(
                "stale"
                if current_latest and now - current_latest.time > STALE_AFTER
                else "good"
            ),
            quality_flag=current_latest.quality if current_latest else None,
        )
        data.attributes["temperature_today_mean"] = self._common_attributes(
            station_id,
            target,
            today_count,
            station_name=self.options.temperature_station_name,
            station_distance_km=self.options.temperature_station_distance_km,
            data_quality="good" if today_mean is not None else "partial",
        )
        data.attributes["temperature_10_year_mean"] = self._common_attributes(
            station_id,
            target,
            ten_count,
            station_name=self.options.temperature_station_name,
            station_distance_km=self.options.temperature_station_distance_km,
            comparison_period="10 years",
            data_quality="good" if ten_mean is not None else "partial",
            last_source_update=self._history_cached_at,
        )
        data.source_status.setdefault(
            "temperature",
            SourceStatus(
                available=current_latest is not None,
                stale=current_latest is None or now - current_latest.time > STALE_AFTER,
                last_update=current_latest.time if current_latest else None,
            ),
        )

    def _populate_climate(self, data: WeatherContextData, target: datetime) -> None:
        """Populate PTHBV climate and optional precipitation context."""
        climate_samples = [
            value
            for year, value in self._climate_values.items()
            if 1991 <= year <= 2020
        ]
        climate_normal, climate_count = mean_with_minimum(
            climate_samples, MIN_CLIMATE_NORMAL_SAMPLES
        )
        today_mean = data.values.get("temperature_today_mean")
        comparable_temperature = (
            float(today_mean) if isinstance(today_mean, (int, float)) else None
        )
        data.values["temperature_climate_normal"] = climate_normal
        data.values["temperature_climate_anomaly"] = subtract(
            comparable_temperature, climate_normal
        )
        data.attributes["temperature_climate_normal"] = self._common_attributes(
            None, target, climate_count, "PTHBV"
        )
        data.attributes["temperature_climate_anomaly"] = self._common_attributes(
            None, target, climate_count, "MetObs and PTHBV"
        )
        if not self.options.enable_precipitation:
            return
        normal_values = [
            value
            for year, value in self._precipitation_values.items()
            if 1991 <= year <= 2020
        ]
        normal, normal_count = mean_with_minimum(
            normal_values, MIN_CLIMATE_NORMAL_SAMPLES
        )
        recent_values = [
            self._precipitation_values.get(target.year - offset)
            for offset in range(1, 11)
        ]
        recent, recent_count = mean_with_minimum(recent_values, MIN_TEN_YEAR_SAMPLES)
        all_values = list(self._precipitation_values.values())
        data.values.update(
            {
                "precipitation_climate_normal": normal,
                "precipitation_10_year_mean": recent,
                "precipitation_historical_max": max(all_values, default=None),
            }
        )
        data.attributes["precipitation_climate_normal"] = self._common_attributes(
            None, target, normal_count, "PTHBV"
        )
        data.attributes["precipitation_10_year_mean"] = self._common_attributes(
            None, target, recent_count, "PTHBV"
        )

    def _populate_wind(
        self,
        data: WeatherContextData,
        speed: list[Observation],
        direction: list[Observation],
        gust: list[Observation],
        target: datetime,
        now: datetime,
    ) -> None:
        speed_latest = latest(speed)
        direction_latest = latest(direction)
        gust_latest = latest(gust)
        today_mean, today_count, _ = day_mean_through_hour(speed, target)
        historical_hour, historical_day = self._history_metrics(
            self._wind_history, target
        )
        ten_mean, ten_count = mean_with_minimum(
            (historical_day[offset] for offset in range(1, 11)),
            MIN_TEN_YEAR_SAMPLES,
        )
        historical_samples = [
            value for value in historical_day.values() if value is not None
        ]
        degrees = direction_latest.value if direction_latest else None
        data.values.update(
            {
                "wind_speed_now": speed_latest.value if speed_latest else None,
                "wind_direction_degrees": degrees,
                "wind_direction": compass_direction(degrees),
                "wind_gust": gust_latest.value if gust_latest else None,
                "wind_today_mean": today_mean,
                "wind_10_year_mean": ten_mean,
                "wind_deviation_10_year": subtract(today_mean, ten_mean),
                "wind_historical_percentile": percentile_rank(
                    today_mean,
                    historical_samples,
                    minimum_samples=MIN_TEN_YEAR_SAMPLES,
                ),
            }
        )
        station_id = self.options.wind_station_id
        for offset in self.options.comparison_years:
            hour_key = f"wind_same_hour_{offset}_year"
            day_key = f"wind_today_mean_{offset}_year"
            data.values[hour_key] = historical_hour.get(offset)
            data.values[day_key] = historical_day.get(offset)
            for key in (hour_key, day_key):
                value = data.values[key]
                data.attributes[key] = self._common_attributes(
                    station_id,
                    target,
                    1 if value is not None else 0,
                    station_name=self.options.wind_station_name,
                    station_distance_km=self.options.wind_station_distance_km,
                    comparison_period=f"{offset} year",
                    data_quality="good" if value is not None else "unavailable",
                    last_source_update=self._history_cached_at,
                )
        data.attributes["wind_speed_now"] = self._common_attributes(
            station_id,
            speed_latest.time if speed_latest else None,
            station_name=self.options.wind_station_name,
            station_distance_km=self.options.wind_station_distance_km,
            data_quality=(
                "stale"
                if speed_latest and now - speed_latest.time > STALE_AFTER
                else "good"
            ),
            quality_flag=speed_latest.quality if speed_latest else None,
        )
        data.attributes["wind_direction"] = self._common_attributes(
            station_id,
            direction_latest.time if direction_latest else None,
            station_name=self.options.wind_station_name,
            station_distance_km=self.options.wind_station_distance_km,
            quality_flag=direction_latest.quality if direction_latest else None,
        )
        data.attributes["wind_direction_degrees"] = dict(
            data.attributes["wind_direction"]
        )
        data.attributes["wind_gust"] = self._common_attributes(
            station_id,
            gust_latest.time if gust_latest else None,
            station_name=self.options.wind_station_name,
            station_distance_km=self.options.wind_station_distance_km,
            quality_flag=gust_latest.quality if gust_latest else None,
        )
        data.attributes["wind_today_mean"] = self._common_attributes(
            station_id,
            target,
            today_count,
            station_name=self.options.wind_station_name,
            station_distance_km=self.options.wind_station_distance_km,
            data_quality="good" if today_mean is not None else "partial",
        )
        data.attributes["wind_10_year_mean"] = self._common_attributes(
            station_id,
            target,
            ten_count,
            station_name=self.options.wind_station_name,
            station_distance_km=self.options.wind_station_distance_km,
            comparison_period="10 years",
            data_quality="good" if ten_mean is not None else "partial",
            last_source_update=self._history_cached_at,
        )
        data.source_status.setdefault(
            "wind_speed",
            SourceStatus(
                available=speed_latest is not None,
                stale=speed_latest is None or now - speed_latest.time > STALE_AFTER,
                last_update=speed_latest.time if speed_latest else None,
            ),
        )
