"""Constants for SMHI Weather Context."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "smhi_weather_context"
NAME = "SMHI Weather Context"
ATTRIBUTION = "Weather observations and climate context from SMHI"

PLATFORMS = ["sensor", "binary_sensor"]

CONF_NAME = "name"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_USE_HOME = "use_home"
CONF_LOCATION_ID = "location_id"
CONF_ENABLE_TEMPERATURE = "enable_temperature"
CONF_ENABLE_WIND = "enable_wind"
CONF_ENABLE_CLIMATE = "enable_climate"
CONF_ENABLE_PRECIPITATION = "enable_precipitation"
CONF_COMPARISON_YEARS = "comparison_years"
CONF_TEMPERATURE_STATION = "temperature_station"
CONF_WIND_STATION = "wind_station"
CONF_TEMPERATURE_STATION_NAME = "temperature_station_name"
CONF_WIND_STATION_NAME = "wind_station_name"
CONF_TEMPERATURE_STATION_DISTANCE = "temperature_station_distance_km"
CONF_WIND_STATION_DISTANCE = "wind_station_distance_km"

DEFAULT_NAME = "Home"
DEFAULT_COMPARISON_YEARS = [1, 2, 3, 10]
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=30)
STALE_AFTER = timedelta(hours=2)

PARAM_TEMPERATURE = 1
PARAM_WIND_DIRECTION = 3
PARAM_WIND_SPEED = 4
PARAM_WIND_GUST = 21

METOBS_HOST = "opendata-download-metobs.smhi.se"
METANALYSIS_HOST = "opendata-download-metanalys.smhi.se"
ALLOWED_HOSTS = frozenset({METOBS_HOST, METANALYSIS_HOST})
METOBS_BASE_URL = f"https://{METOBS_HOST}/api/version/1.0"
PTHBV_BASE_URL = (
    f"https://{METANALYSIS_HOST}/api/category/pthbv1g/version/1/geotype/multipoint"
)

MAX_JSON_BYTES = 12 * 1024 * 1024
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MIN_HISTORY_COVERAGE = 0.75
MIN_TEN_YEAR_SAMPLES = 7
MIN_CLIMATE_NORMAL_SAMPLES = 24

STOCKHOLM_TIME_ZONE = "Europe/Stockholm"
