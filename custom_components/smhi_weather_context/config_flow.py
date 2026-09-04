"""Config flow for SMHI Weather Context."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .api import SmhiApiClient, SmhiApiConnectionError, SmhiApiError, SmhiCoverageError
from .const import (
    CONF_COMPARISON_YEARS,
    CONF_ENABLE_CLIMATE,
    CONF_ENABLE_PRECIPITATION,
    CONF_ENABLE_TEMPERATURE,
    CONF_ENABLE_WIND,
    CONF_LOCATION_ID,
    CONF_NAME,
    CONF_TEMPERATURE_STATION,
    CONF_TEMPERATURE_STATION_DISTANCE,
    CONF_TEMPERATURE_STATION_NAME,
    CONF_USE_HOME,
    CONF_WIND_STATION,
    CONF_WIND_STATION_DISTANCE,
    CONF_WIND_STATION_NAME,
    DEFAULT_COMPARISON_YEARS,
    DOMAIN,
    PARAM_TEMPERATURE,
    PARAM_WIND_DIRECTION,
    PARAM_WIND_GUST,
    PARAM_WIND_SPEED,
)
from .metobs import MetObsClient
from .models import Location, Station
from .pthbv import PthbvClient

COMPARISON_YEAR_OPTIONS = {str(year): str(year) for year in (1, 2, 3, 5, 10, 20, 30)}


def _location_unique_id(latitude: float, longitude: float) -> str:
    """Return deterministic identity used only for duplicate prevention."""
    return f"{latitude:.4f},{longitude:.4f}"


def _feature_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    values = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_ENABLE_TEMPERATURE,
                default=values.get(CONF_ENABLE_TEMPERATURE, True),
            ): bool,
            vol.Required(
                CONF_ENABLE_WIND, default=values.get(CONF_ENABLE_WIND, True)
            ): bool,
            vol.Required(
                CONF_ENABLE_CLIMATE,
                default=values.get(CONF_ENABLE_CLIMATE, True),
            ): bool,
            vol.Required(
                CONF_ENABLE_PRECIPITATION,
                default=values.get(CONF_ENABLE_PRECIPITATION, False),
            ): bool,
        }
    )


def _comparison_schema(defaults: list[int] | tuple[int, ...]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_COMPARISON_YEARS,
                default=[str(value) for value in defaults],
            ): cv.multi_select(COMPARISON_YEAR_OPTIONS)
        }
    )


class SmhiWeatherContextConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a SMHI Weather Context config flow."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._options: dict[str, Any] = {}
        self._temperature_stations: list[Station] = []
        self._wind_stations: list[Station] = []
        self._reconfigure_entry: ConfigEntry | None = None
        self._discovery_complete = False
        self._climate_deferred = False

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SmhiOptionsFlow:
        """Return the options flow."""
        return SmhiOptionsFlow()

    def _location_schema(self, suggested: dict[str, Any] | None = None) -> vol.Schema:
        values = suggested or {}
        return vol.Schema(
            {
                vol.Required(
                    CONF_USE_HOME, default=values.get(CONF_USE_HOME, True)
                ): bool,
                vol.Required(
                    CONF_NAME,
                    default=values.get(CONF_NAME, self.hass.config.location_name),
                ): cv.string,
                vol.Required(
                    CONF_LATITUDE,
                    default=values.get(CONF_LATITUDE, self.hass.config.latitude),
                ): cv.latitude,
                vol.Required(
                    CONF_LONGITUDE,
                    default=values.get(CONF_LONGITUDE, self.hass.config.longitude),
                ): cv.longitude,
            }
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the location."""
        if user_input is not None:
            self._set_location(user_input)
            return await self.async_step_content()
        return self.async_show_form(step_id="user", data_schema=self._location_schema())

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Safely change location and stations with explicit confirmation."""
        self._reconfigure_entry = self._get_reconfigure_entry()
        if user_input is not None:
            self._set_location(user_input)
            return await self.async_step_content()
        entry = self._reconfigure_entry
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._location_schema(
                {
                    CONF_USE_HOME: False,
                    CONF_NAME: entry.data[CONF_NAME],
                    CONF_LATITUDE: entry.data[CONF_LATITUDE],
                    CONF_LONGITUDE: entry.data[CONF_LONGITUDE],
                }
            ),
        )

    def _set_location(self, user_input: dict[str, Any]) -> None:
        if user_input[CONF_USE_HOME]:
            latitude = self.hass.config.latitude
            longitude = self.hass.config.longitude
        else:
            latitude = float(user_input[CONF_LATITUDE])
            longitude = float(user_input[CONF_LONGITUDE])
        self._data.update(
            {
                CONF_NAME: str(user_input[CONF_NAME]).strip(),
                CONF_LATITUDE: latitude,
                CONF_LONGITUDE: longitude,
            }
        )

    async def async_step_content(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select data products."""
        if user_input is not None:
            if not any(
                user_input[key]
                for key in (
                    CONF_ENABLE_TEMPERATURE,
                    CONF_ENABLE_WIND,
                    CONF_ENABLE_CLIMATE,
                )
            ):
                return self.async_show_form(
                    step_id="content",
                    data_schema=_feature_schema(user_input),
                    errors={"base": "select_feature"},
                )
            if (
                user_input[CONF_ENABLE_PRECIPITATION]
                and not user_input[CONF_ENABLE_CLIMATE]
            ):
                return self.async_show_form(
                    step_id="content",
                    data_schema=_feature_schema(user_input),
                    errors={
                        CONF_ENABLE_PRECIPITATION: "precipitation_requires_climate"
                    },
                )
            self._options.update(user_input)
            return await self.async_step_comparisons()
        defaults = (
            dict(self._reconfigure_entry.options) if self._reconfigure_entry else None
        )
        return self.async_show_form(
            step_id="content", data_schema=_feature_schema(defaults)
        )

    async def async_step_comparisons(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select historical comparison offsets."""
        if user_input is not None:
            years = sorted({int(value) for value in user_input[CONF_COMPARISON_YEARS]})
            if not years:
                return self.async_show_form(
                    step_id="comparisons",
                    data_schema=_comparison_schema(DEFAULT_COMPARISON_YEARS),
                    errors={CONF_COMPARISON_YEARS: "select_comparison"},
                )
            self._options[CONF_COMPARISON_YEARS] = years
            return await self.async_step_stations()
        defaults = (
            self._reconfigure_entry.options.get(
                CONF_COMPARISON_YEARS, DEFAULT_COMPARISON_YEARS
            )
            if self._reconfigure_entry
            else DEFAULT_COMPARISON_YEARS
        )
        return self.async_show_form(
            step_id="comparisons", data_schema=_comparison_schema(defaults)
        )

    async def _async_discover(self) -> None:
        self._climate_deferred = False
        location = Location(
            self._data[CONF_NAME],
            self._data[CONF_LATITUDE],
            self._data[CONF_LONGITUDE],
        )
        oldest_year = datetime.now(UTC).year - max(
            max(self._options[CONF_COMPARISON_YEARS]), 10
        )
        api = SmhiApiClient(async_get_clientsession(self.hass))
        metobs = MetObsClient(api)
        tasks: list[Any] = []
        if self._options[CONF_ENABLE_TEMPERATURE]:
            tasks.append(
                metobs.async_stations(PARAM_TEMPERATURE, location, oldest_year)
            )
        if self._options[CONF_ENABLE_WIND]:
            tasks.extend(
                metobs.async_stations(parameter, location, oldest_year)
                for parameter in (
                    PARAM_WIND_SPEED,
                    PARAM_WIND_DIRECTION,
                    PARAM_WIND_GUST,
                )
            )
        results = await asyncio.gather(*tasks)
        index = 0
        if self._options[CONF_ENABLE_TEMPERATURE]:
            self._temperature_stations = results[index]
            index += 1
        if self._options[CONF_ENABLE_WIND]:
            speed, direction, gust = results[index : index + 3]
            compatible = {station.station_id for station in direction} & {
                station.station_id for station in gust
            }
            self._wind_stations = [
                station for station in speed if station.station_id in compatible
            ]
        if self._options[CONF_ENABLE_CLIMATE]:
            year = datetime.now(UTC).year - 2
            try:
                await PthbvClient(api).async_daily(
                    location,
                    year,
                    year,
                    precipitation=self._options[CONF_ENABLE_PRECIPITATION],
                )
            except SmhiApiConnectionError:
                # Optional climate history must not block working observations.
                # Keep the option enabled; the coordinator retries after setup.
                self._climate_deferred = True
        self._discovery_complete = True

    @staticmethod
    def _station_options(stations: list[Station]) -> dict[str, str]:
        return {
            str(station.station_id): (
                f"{station.name} — {station.distance_km:.1f} km — "
                f"{station.from_time.year}-{station.to_time.year}"
            )
            for station in stations[:25]
        }

    async def async_step_stations(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Discover and explicitly select compatible MetObs stations."""
        errors: dict[str, str] = {}
        if not self._discovery_complete:
            try:
                await self._async_discover()
            except SmhiCoverageError:
                errors["base"] = "outside_coverage"
            except SmhiApiConnectionError:
                errors["base"] = "cannot_connect"
            except SmhiApiError:
                errors["base"] = "invalid_response"
        if self._options[CONF_ENABLE_TEMPERATURE] and not self._temperature_stations:
            errors.setdefault("base", "no_temperature_station")
        if self._options[CONF_ENABLE_WIND] and not self._wind_stations:
            errors.setdefault("base", "no_wind_station")

        fields: dict[vol.Marker, Any] = {}
        if self._temperature_stations:
            current = (
                str(self._reconfigure_entry.data.get(CONF_TEMPERATURE_STATION))
                if self._reconfigure_entry
                else str(self._temperature_stations[0].station_id)
            )
            choices = self._station_options(self._temperature_stations)
            if current not in choices:
                current = next(iter(choices))
            fields[vol.Required(CONF_TEMPERATURE_STATION, default=current)] = vol.In(
                choices
            )
        if self._wind_stations:
            current = (
                str(self._reconfigure_entry.data.get(CONF_WIND_STATION))
                if self._reconfigure_entry
                else str(self._wind_stations[0].station_id)
            )
            choices = self._station_options(self._wind_stations)
            if current not in choices:
                current = next(iter(choices))
            fields[vol.Required(CONF_WIND_STATION, default=current)] = vol.In(choices)

        if user_input is not None and not errors:
            try:
                if await self._async_validate_selection(user_input):
                    self._apply_station_selection(user_input)
                    return await self.async_step_confirm()
                errors["base"] = "station_incompatible"
            except SmhiApiConnectionError:
                errors["base"] = "cannot_connect"
            except SmhiApiError:
                errors["base"] = "invalid_response"
        return self.async_show_form(
            step_id="stations", data_schema=vol.Schema(fields), errors=errors
        )

    async def _async_validate_selection(self, user_input: dict[str, Any]) -> bool:
        """Verify the chosen stations' actual periods before confirmation."""
        metobs = MetObsClient(SmhiApiClient(async_get_clientsession(self.hass)))
        checks: list[Any] = []
        if self._options[CONF_ENABLE_TEMPERATURE]:
            checks.append(
                metobs.async_validate_station(
                    PARAM_TEMPERATURE, int(user_input[CONF_TEMPERATURE_STATION])
                )
            )
        if self._options[CONF_ENABLE_WIND]:
            station_id = int(user_input[CONF_WIND_STATION])
            checks.extend(
                metobs.async_validate_station(parameter, station_id)
                for parameter in (
                    PARAM_WIND_SPEED,
                    PARAM_WIND_DIRECTION,
                    PARAM_WIND_GUST,
                )
            )
        return all(await asyncio.gather(*checks))

    def _apply_station_selection(self, user_input: dict[str, Any]) -> None:
        if self._options[CONF_ENABLE_TEMPERATURE]:
            selected = int(user_input[CONF_TEMPERATURE_STATION])
            station = next(
                item
                for item in self._temperature_stations
                if item.station_id == selected
            )
            self._data[CONF_TEMPERATURE_STATION] = selected
            self._data[CONF_TEMPERATURE_STATION_NAME] = station.name
            self._data[CONF_TEMPERATURE_STATION_DISTANCE] = station.distance_km
        else:
            self._data[CONF_TEMPERATURE_STATION] = 0
            self._data[CONF_TEMPERATURE_STATION_NAME] = ""
            self._data[CONF_TEMPERATURE_STATION_DISTANCE] = None
        if self._options[CONF_ENABLE_WIND]:
            selected = int(user_input[CONF_WIND_STATION])
            station = next(
                item for item in self._wind_stations if item.station_id == selected
            )
            self._data[CONF_WIND_STATION] = selected
            self._data[CONF_WIND_STATION_NAME] = station.name
            self._data[CONF_WIND_STATION_DISTANCE] = station.distance_km
        else:
            self._data[CONF_WIND_STATION] = 0
            self._data[CONF_WIND_STATION_NAME] = ""
            self._data[CONF_WIND_STATION_DISTANCE] = None

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the chosen location and stations before creating/updating."""
        unique_id = _location_unique_id(
            self._data[CONF_LATITUDE], self._data[CONF_LONGITUDE]
        )
        if user_input is not None:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.unique_id == unique_id and (
                    self._reconfigure_entry is None
                    or entry.entry_id != self._reconfigure_entry.entry_id
                ):
                    return self.async_abort(reason="already_configured")
            if self._reconfigure_entry:
                data = {
                    **self._data,
                    CONF_LOCATION_ID: self._reconfigure_entry.data[CONF_LOCATION_ID],
                }
                return self.async_update_reload_and_abort(
                    self._reconfigure_entry,
                    unique_id=unique_id,
                    title=self._data[CONF_NAME],
                    data=data,
                    options=self._options,
                )
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self._data[CONF_NAME],
                data={**self._data, CONF_LOCATION_ID: uuid4().hex},
                options=self._options,
            )
        return self.async_show_form(
            step_id=(
                "confirm_climate_unavailable" if self._climate_deferred else "confirm"
            ),
            data_schema=vol.Schema({}),
            description_placeholders={
                "location": self._data[CONF_NAME],
                "temperature_station": self._data.get(
                    CONF_TEMPERATURE_STATION_NAME, "—"
                ),
                "wind_station": self._data.get(CONF_WIND_STATION_NAME, "—"),
            },
        )

    async def async_step_confirm_climate_unavailable(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm setup with an explicit warning about deferred climate data."""
        return await self.async_step_confirm(user_input)


class SmhiOptionsFlow(OptionsFlowWithReload):
    """Edit feature and comparison options and reload automatically."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update optional products."""
        if user_input is not None:
            if not any(
                user_input[key]
                for key in (
                    CONF_ENABLE_TEMPERATURE,
                    CONF_ENABLE_WIND,
                    CONF_ENABLE_CLIMATE,
                )
            ):
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._schema(user_input),
                    errors={"base": "select_feature"},
                )
            if (
                user_input[CONF_ENABLE_PRECIPITATION]
                and not user_input[CONF_ENABLE_CLIMATE]
            ):
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._schema(user_input),
                    errors={
                        CONF_ENABLE_PRECIPITATION: "precipitation_requires_climate"
                    },
                )
            if (
                user_input[CONF_ENABLE_TEMPERATURE]
                and not self.config_entry.data.get(CONF_TEMPERATURE_STATION)
            ) or (
                user_input[CONF_ENABLE_WIND]
                and not self.config_entry.data.get(CONF_WIND_STATION)
            ):
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._schema(user_input),
                    errors={"base": "reconfigure_required"},
                )
            user_input[CONF_COMPARISON_YEARS] = sorted(
                {int(value) for value in user_input[CONF_COMPARISON_YEARS]}
            )
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=self._schema(dict(self.config_entry.options))
        )

    @staticmethod
    def _schema(values: dict[str, Any]) -> vol.Schema:
        feature = _feature_schema(values).schema
        comparison = _comparison_schema(
            values.get(CONF_COMPARISON_YEARS, DEFAULT_COMPARISON_YEARS)
        ).schema
        return vol.Schema(feature | comparison)
