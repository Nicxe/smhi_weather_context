"""Sensor platform for SMHI Weather Context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    DEGREE,
    EntityCategory,
    UnitOfPrecipitationDepth,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import SmhiWeatherContextEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SmhiSensorDescription(SensorEntityDescription):
    """Describe one coordinator value."""

    data_key: str


TEMPERATURE_DESCRIPTIONS = (
    SmhiSensorDescription(
        key="temperature_now",
        data_key="temperature_now",
        translation_key="temperature_now",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SmhiSensorDescription(
        key="temperature_today_mean",
        data_key="temperature_today_mean",
        translation_key="temperature_today_mean",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SmhiSensorDescription(
        key="temperature_10_year_mean",
        data_key="temperature_10_year_mean",
        translation_key="temperature_10_year_mean",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SmhiSensorDescription(
        key="temperature_deviation_10_year",
        data_key="temperature_deviation_10_year",
        translation_key="temperature_deviation_10_year",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SmhiSensorDescription(
        key="temperature_historical_percentile",
        data_key="temperature_historical_percentile",
        translation_key="temperature_historical_percentile",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SmhiSensorDescription(
        key="temperature_historical_max",
        data_key="temperature_historical_max",
        translation_key="temperature_historical_max",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    SmhiSensorDescription(
        key="temperature_historical_min",
        data_key="temperature_historical_min",
        translation_key="temperature_historical_min",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
)

CLIMATE_DESCRIPTIONS = (
    SmhiSensorDescription(
        key="temperature_climate_normal",
        data_key="temperature_climate_normal",
        translation_key="temperature_climate_normal",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

CLIMATE_ANOMALY_DESCRIPTION = SmhiSensorDescription(
    key="temperature_climate_anomaly",
    data_key="temperature_climate_anomaly",
    translation_key="temperature_climate_anomaly",
    device_class=SensorDeviceClass.TEMPERATURE,
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    state_class=SensorStateClass.MEASUREMENT,
)

PRECIPITATION_DESCRIPTIONS = (
    SmhiSensorDescription(
        key="precipitation_climate_normal",
        data_key="precipitation_climate_normal",
        translation_key="precipitation_climate_normal",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SmhiSensorDescription(
        key="precipitation_10_year_mean",
        data_key="precipitation_10_year_mean",
        translation_key="precipitation_10_year_mean",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SmhiSensorDescription(
        key="precipitation_historical_max",
        data_key="precipitation_historical_max",
        translation_key="precipitation_historical_max",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
)

WIND_DESCRIPTIONS = (
    SmhiSensorDescription(
        key="wind_speed_now",
        data_key="wind_speed_now",
        translation_key="wind_speed_now",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SmhiSensorDescription(
        key="wind_direction",
        data_key="wind_direction",
        translation_key="wind_direction",
    ),
    SmhiSensorDescription(
        key="wind_direction_degrees",
        data_key="wind_direction_degrees",
        translation_key="wind_direction_degrees",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SmhiSensorDescription(
        key="wind_gust",
        data_key="wind_gust",
        translation_key="wind_gust",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SmhiSensorDescription(
        key="wind_today_mean",
        data_key="wind_today_mean",
        translation_key="wind_today_mean",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SmhiSensorDescription(
        key="wind_10_year_mean",
        data_key="wind_10_year_mean",
        translation_key="wind_10_year_mean",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SmhiSensorDescription(
        key="wind_deviation_10_year",
        data_key="wind_deviation_10_year",
        translation_key="wind_deviation_10_year",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SmhiSensorDescription(
        key="wind_historical_percentile",
        data_key="wind_historical_percentile",
        translation_key="wind_historical_percentile",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
)

DIAGNOSTIC_DESCRIPTIONS = (
    SmhiSensorDescription(
        key="smhi_last_observation",
        data_key="smhi_last_observation",
        translation_key="smhi_last_observation",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SmhiSensorDescription(
        key="smhi_last_historical_update",
        data_key="smhi_last_historical_update",
        translation_key="smhi_last_historical_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up all configured sensors."""
    options = entry.runtime_data.options
    descriptions: list[SmhiSensorDescription] = list(DIAGNOSTIC_DESCRIPTIONS)
    if options.enable_temperature:
        descriptions.extend(TEMPERATURE_DESCRIPTIONS)
        for offset in options.comparison_years:
            descriptions.extend(
                (
                    _comparison_description("temperature_same_hour", offset, True),
                    _comparison_description("temperature_today_mean", offset, False),
                )
            )
    if options.enable_wind:
        descriptions.extend(WIND_DESCRIPTIONS)
        for offset in options.comparison_years:
            descriptions.extend(
                (
                    _comparison_description("wind_same_hour", offset, True),
                    _comparison_description("wind_today_mean", offset, False),
                )
            )
    if options.enable_climate:
        descriptions.extend(CLIMATE_DESCRIPTIONS)
        if options.enable_temperature:
            descriptions.append(CLIMATE_ANOMALY_DESCRIPTION)
    if options.enable_precipitation:
        descriptions.extend(PRECIPITATION_DESCRIPTIONS)
    async_add_entities(
        SmhiContextSensor(entry, description) for description in descriptions
    )


def _comparison_description(
    prefix: str, offset: int, same_hour: bool
) -> SmhiSensorDescription:
    temperature = prefix.startswith("temperature")
    key = f"{prefix}_{offset}_year"
    return SmhiSensorDescription(
        key=key,
        data_key=key,
        translation_key=(
            "temperature_same_hour_year"
            if temperature and same_hour
            else "temperature_today_mean_year"
            if temperature
            else "wind_same_hour_year"
            if same_hour
            else "wind_today_mean_year"
        ),
        translation_placeholders={"years": str(offset)},
        device_class=(
            SensorDeviceClass.TEMPERATURE
            if temperature
            else SensorDeviceClass.WIND_SPEED
        ),
        native_unit_of_measurement=(
            UnitOfTemperature.CELSIUS if temperature else UnitOfSpeed.METERS_PER_SECOND
        ),
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=offset == 1,
    )


class SmhiContextSensor(SmhiWeatherContextEntity, SensorEntity):
    """Expose one calculated coordinator value."""

    entity_description: SmhiSensorDescription

    def __init__(self, entry: ConfigEntry, description: SmhiSensorDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the calculated value."""
        return self.coordinator.data.values.get(self.entity_description.data_key)

    @property
    def available(self) -> bool:
        """Expose missing or source-specific values as unavailable, never zero."""
        return super().available and self.native_value is not None
