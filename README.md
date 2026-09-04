# SMHI Weather Context

![SMHI Weather Context icon](custom_components/smhi_weather_context/icon.png)

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://www.hacs.xyz/docs/faq/custom_repositories/)
[![Validation](https://github.com/Nicxe/smhi_weather_context/actions/workflows/validate.yml/badge.svg?branch=main)](https://github.com/Nicxe/smhi_weather_context/actions/workflows/validate.yml)
[![Tests](https://github.com/Nicxe/smhi_weather_context/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Nicxe/smhi_weather_context/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Is today warmer than the same day last year? Is the wind unusually strong? **SMHI Weather Context** brings current observations, historical comparisons, and climate context from SMHI into Home Assistant.

Choose weather stations for your Swedish location and compare temperature and wind with previous years. Add a separate climate perspective based on the 1991–2020 climate normal, with optional precipitation data.

This is an unofficial, independent integration. It is not developed or supported by SMHI and does not replace Home Assistant's built-in SMHI forecast integration. The interface is available in English and Swedish, where it is called **SMHI Väderperspektiv**.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Setup](#setup)
- [Entities and dashboards](#entities-and-dashboards)
- [Understanding the data](#understanding-the-data)
- [Troubleshooting](#troubleshooting)
- [Privacy](#privacy)
- [Updating and removing](#updating-and-removing)
- [Development and support](#development-and-support)

## Features

- Current temperature, wind speed, wind direction, and wind gust observations.
- Comparisons with the corresponding local hour and elapsed part of the day in previous years.
- Configurable comparison years, with 1, 2, 3, and 10 years selected by default.
- Ten-year averages, deviations, and historical percentiles when enough valid data is available.
- A separate climate perspective using SMHI's 1991–2020 normal.
- Optional gridded precipitation context.
- Separate temperature and wind stations, chosen by you rather than switched automatically.
- Multiple locations, configured entirely through the Home Assistant interface.
- Data-quality indicators, redacted diagnostics, and repair guidance when a station becomes incompatible.

This integration provides sensors, not forecasts, weather warnings, maps, or a custom dashboard card.

## Requirements

- Home Assistant **2026.9.0 or newer**. This is the tested baseline; older versions are not supported.
- A location in Sweden with suitable SMHI station coverage. Climate features also require PTHBV coverage.
- Internet access to SMHI's open-data services. No API key, account, or subscription is required.
- [HACS](https://www.hacs.xyz/docs/use/) installed and configured for the recommended installation method.

## Installation

### HACS: add this custom repository first

**This integration is not included in the HACS default repositories.** Searching HACS alone will not find it: you must add the repository first.

> HACS downloads the packaged `smhi_weather_context.zip` from a published GitHub release. Until the first release is published, use the manual installation below. A source-code commit or a draft release is not an installable HACS release.

1. Open **HACS** in Home Assistant.
2. Select the **three-dot menu** in the top-right corner, then **Custom repositories**.
3. Enter `https://github.com/Nicxe/smhi_weather_context` as the repository URL.
4. Select **Integration** as the type and click **Add**.
5. Search for **SMHI Weather Context**, open its page, and select **Download**. Confirm the version when prompted.
6. **Restart Home Assistant.** Downloading through HACS alone does not load the integration.
7. Continue with [Setup](#setup) to add your location.

You can also open the repository in HACS using this shortcut:

[![Open this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Nicxe&repository=smhi_weather_context&category=integration)

These steps follow the [official HACS custom repository instructions](https://www.hacs.xyz/docs/faq/custom_repositories/).

**No dashboard resource is needed.** Add the repository to HACS as an **Integration**, not as a Dashboard repository. Do not add a JavaScript resource under **Settings → Dashboards → Resources**.

### Manual installation

1. Download the source archive from **Code → Download ZIP** on the [main branch](https://github.com/Nicxe/smhi_weather_context/tree/main).
2. Extract it and locate `custom_components/smhi_weather_context` inside the downloaded source.
3. Copy that entire `smhi_weather_context` folder into your Home Assistant configuration directory's `custom_components` folder. Create `custom_components` if needed. Back up an existing installation before replacing it.
4. Check the resulting layout:

   ```text
   config/
   └── custom_components/
       └── smhi_weather_context/
           ├── __init__.py
           ├── manifest.json
           ├── translations/
           └── ...
   ```

5. Restart Home Assistant and continue with [Setup](#setup).

If you download the packaged `smhi_weather_context.zip` from [Releases](https://github.com/Nicxe/smhi_weather_context/releases) instead, extract its contents **directly into** `config/custom_components/smhi_weather_context/`. The release ZIP is flat: it does not contain a parent component folder. Do not confuse it with GitHub's automatically generated source-code ZIP.

## Setup

After installation and restart:

1. Go to **Settings → Devices & services → Add integration**.
2. Search for **SMHI Weather Context** (or **SMHI Väderperspektiv** when using Swedish).
3. Use your Home Assistant home position, or enter a name and coordinates for another Swedish location.
4. Choose temperature, wind, climate context, and optional precipitation features.
5. Select which previous years to compare with.
6. Choose compatible temperature and wind stations. They may be different stations; review the displayed distance and available history.
7. Review the summary and finish setup.

[![Add SMHI Weather Context to Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=smhi_weather_context)

Repeat these steps to add another location. No YAML configuration is needed.

The first historical and climate downloads can take longer than current observations. Some comparison sensors may initially be unavailable while data loads.

Use **Configure** on the integration entry to change enabled features and comparison years. Use the entry's **Reconfigure** action to change its location or station selections. Enabling a feature without a compatible selected station may require reconfiguration first.

Stations are never changed automatically. If a station becomes incompatible, follow the repair notice and choose another station.

## Entities and dashboards

Entities depend on enabled features. Common current readings and one-year comparisons are enabled by default. Additional comparison years, some percentiles, historical minima and maxima, and technical diagnostics are disabled by default.

To enable an optional entity, open **Settings → Devices & services → Entities**, filter by this integration, select the entity, and enable it in its settings. Add enabled sensors to standard Home Assistant dashboard cards; no extra frontend download is required.

Missing or insufficient data is shown as **Unavailable**, never as zero or a substituted nearby hour. The [entity reference](docs/entities.md) lists sensors and attributes (currently in Swedish).

## Understanding the data

| Perspective | Source | What it represents |
| --- | --- | --- |
| Current observations | SMHI MetObs | Measurements at your selected station |
| Historical comparisons | SMHI MetObs corrected archive | Previous observations from the same station and parameter |
| Climate and precipitation | SMHI PTHBV | Daily gridded data for an approximately 4 × 4 km area |

A PTHBV grid point is **not** a weather station. The climate anomaly compares the station's average so far today with a gridded full-day climate normal; it is contextual information, not a like-for-like station record.

Current observations are checked every 30 minutes and considered stale after two hours. Valid historical archives and climate data are normally cached for 28 days; historical calculations are refreshed when the local date changes. Previously validated cached data may remain usable during a temporary historical-service outage.

Quality safeguards include:

- At least 75% of the relevant hourly observations for a historical daily average.
- At least seven valid yearly values for a ten-year average.
- At least 24 valid years for a 1991–2020 climate normal.
- Explicit handling of Sweden's 23-hour and 25-hour daylight-saving transition days.
- No invented February 29 values. The climate normal is unavailable that day because the reference period contains only eight leap days.

Method details are in [Data sources](docs/data-sources.md) and [Calculations](docs/calculations.md), currently in Swedish.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Not found in HACS | Add the custom repository using the URL and **Integration** type above. |
| HACS has no version to download | Check for a non-draft release containing `smhi_weather_context.zip`. Otherwise use manual installation. |
| Missing from Add integration | Restart Home Assistant and verify the folder contains `manifest.json` at the correct level. Refresh the browser and search again. |
| Historical or climate sensors unavailable | Allow the initial download to finish. Check station coverage, sample-count attributes, and SMHI service availability. |
| Only some sensors appear | Check enabled features and disabled entities. |
| A station repair is shown | Reconfigure the entry and select a compatible station. |
| Optional precipitation unavailable | The climate service may be temporarily unavailable or lack sufficient data. Current temperature and wind can still work. |

See [Troubleshooting notes](docs/troubleshooting.md) for more detail (currently in Swedish). Include your Home Assistant version, integration version, and relevant redacted logs when reporting a problem.

## Privacy

There is no telemetry, analytics, or login. Weather requests use HTTPS to `opendata-download-metobs.smhi.se` and `opendata-download-metanalys.smhi.se`.

Your configured coordinates are stored locally in Home Assistant. Climate requests send the precise coordinates to SMHI to select a grid point. Downloaded diagnostics remove location names and coordinates. Never post exact coordinates, complete location-bearing request URLs, credentials, or raw cache files in public issues. See [Privacy and security](docs/privacy.md).

## Updating and removing

For a HACS installation, download updates through HACS and restart Home Assistant. For a manual installation, back up and replace the component folder with the new version, then restart. Keep your integration entries to preserve their configuration.

To uninstall, first remove all SMHI Weather Context entries under **Settings → Devices & services**. This lets the integration clean up its own cached data. Then remove the downloaded integration through HACS, or remove only its `custom_components/smhi_weather_context` folder for a manual installation, and restart Home Assistant. Do not edit Home Assistant's `.storage` files manually.

## Development and support

Contributions target **`dev`**. Releases follow **`dev → beta → main`**, using real merge commits for branch promotions. `beta` produces prereleases, `main` produces stable releases, and `dev` never publishes. Semantic-release prepares draft releases for maintainer review; newly created branches do not automatically release.

The repository includes Ruff lint and formatting checks, strict typing, Home Assistant tests with coverage thresholds, hassfest, HACS validation, dependency checks, and reproducible release packages with checksums and an SPDX software bill of materials. See [Testing](docs/testing.md), [Architecture](docs/architecture.md), and [Repository instructions](AGENTS.md). Advanced technical documents are currently in Swedish.

Use [GitHub Issues](https://github.com/Nicxe/smhi_weather_context/issues) for bugs and feature requests. Follow [SECURITY.md](SECURITY.md) for security concerns.

## License and attribution

The integration code is distributed under the [MIT License](LICENSE). Weather observations and climate data are provided by **SMHI** and remain subject to [SMHI's data usage terms](https://www.smhi.se/data/om-smhis-data/villkor-for-anvandning). Calculated comparisons are derived values, not official SMHI forecasts or warnings.
