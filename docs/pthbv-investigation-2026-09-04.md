---
id: pthbv-investigation-2026-09-04
title: PTHBV investigation and reliability fixes
---

# PTHBV investigation — 4 September 2026

This report explains why climate history is unavailable and how the integration handles failed requests. The investigation evidence and the subsequent reliability changes are recorded separately below.

## Conclusion

The observed climate failure occurs before JSON decoding: the documented SMHI PTHBV download endpoint returns HTTP 503 with an HTML `Backend fetch failed` response from Varnish. The same failure is reproducible outside the integration and from the HAdev host. A documented STRÅNG request succeeds through the same hostname and Varnish gateway, narrowing the failure to PTHBV service delivery rather than general SMHI DNS, HTTPS or host connectivity.

This identifies the failing boundary, not SMHI's internal root cause. A stopped backend, failing backend dependency, unhealthy routing or another service-side fault cannot be distinguished without SMHI's operational information. Restoration time and the duration of the incident are unknown. No working replacement endpoint has been established by this investigation.

The earlier setup fix allows configuration to finish while climate is unavailable. It does not repair or replace SMHI's climate service.

## Scope and team

- API/documentation specialist: independently review SMHI's published API, product pages, examples and service notices.
- Python/API and climate specialist: independently review URL construction, parser assumptions, cache, coordinator behavior, tests and previous verification evidence.
- Investigation lead: examine live HAdev through Home Assistant MCP, reproduce network failures from macOS and HAdev, use Context7, cross-check the specialist findings and assemble this report.

No integration configuration, runtime files, access controls, commits or releases were changed during the investigation. The report is a local artifact.

## Live environment and evidence

The inspected config entry is `Göteborg PTHBV-verifiering` on `http://hadev.local:8123`, Home Assistant Core 2026.9.0. Temperature and climate are enabled; wind and precipitation are disabled. The entry is `loaded`; coordinator diagnostics report successful overall updates and an unavailable climate source with `SmhiApiUnavailableError`.

Repository and runtime component files are byte-identical, excluding Python cache and macOS metadata. The local `dev` branch is one promotion merge behind the already-fetched `origin/dev`; this does not account for a runtime-code difference.

Tests below used SMHI's public Norrköping example coordinates or the public Göteborg A station location, not a private home position. Network probes were bounded and did not bypass certificate validation.

| Check, 2026-09-04 UTC | Result | Implication |
| --- | --- | --- |
| Official PTHBV example: monthly 2022–2023, both `p` and `t`, from macOS, 20:06:20 | HTTP 503, HTML, `Retry-After: 5` | Failure also affects SMHI's own documented example |
| Setup-shaped request: daily 2024, `t`, gzip, encoded comma, HTTP/1.1, 20:06:47 | HTTP 503 | Not specific to the full runtime interval or HTTP/2 |
| Runtime-shaped request: daily 1961–2025, `t`, gzip, from macOS, 20:07:30 | HTTP 503 | Reproduces the actual runtime request shape |
| Official example from HAdev's existing web terminal, 20:08:25 | HTTP/2 503, `Backend fetch failed` | Not restricted to the macOS client |
| Official example over HTTP as a diagnostic control, 20:09:12 | HTTP 503 | Changing transport to HTTP does not restore service; integration continues to require HTTPS |
| MetObs current Göteborg A temperature, 20:09:12 | HTTP 200, certificate validation successful | Current observation service remains reachable |
| Unmodified `PthbvClient` + `SmhiApiClient`, daily 1961–2025, `t`, 20:10:12–20:10:22 | HTTP 503 at approximately 0.07, 5.13 and 10.18 seconds; final `SmhiApiUnavailableError: SMHI returned HTTP 503` | Real retry behavior respects five-second backoff; parser is never reached |
| Daily climate normal interval 1991–2020, `t`, 20:10:22 | HTTP 503 | Reducing the range to the required normal period does not solve the current failure |
| Documented STRÅNG point example, same `opendata-download-metanalys.smhi.se` host, 20:11:21 | HTTP 200, JSON, gzip, via `lxserv2756.smhi.se (Varnish/7.6)` | Same gateway works for a different backend/product |
| Actual runtime URL from HAdev's web terminal, approximately 20:12 | HTTP 503, TLS verification result 0, 0.061 s | Actual request also fails from the dev host with successful certificate verification |
| Official frontend's CSV route for the same monthly example, 20:15:18 | HTTP 503 through the same Varnish gateway | Switching from JSON to the published CSV export does not restore this download |

The SSH web terminal runs as the existing host-network app on HAdev. These are host-side probes, not commands executed inside the Core container. Core-container access would require changing the app's protection mode; that was not done. The live Core state was inspected through Home Assistant MCP, and the integration's unchanged Python client was exercised locally.

IPv6-only access from macOS failed to connect, while IPv4 completed TLS and received the service's 503 response. IPv6 unavailability therefore does not explain the observed application-level error.

## Request and response contract

Current integration request:

```text
GET https://opendata-download-metanalys.smhi.se/api/category/pthbv1g/version/1/geotype/multipoint/from/{start_year}/to/{end_year}/period/daily/data.json
    ?epsg=4326&ll={longitude},{latitude}&var=t
Accept-Encoding: gzip
```

With precipitation enabled, `var=p` is added as a separate query parameter. Setup probes one completed year, currently 2024. Runtime asks for 1961 through the previous year, currently 2025. The 1991–2020 climate normal is selected from that longer series.

SMHI's `get_point` template labels the coordinates latitude/longitude, whereas its concrete introduction example uses longitude/latitude. The latter is consistent with the integration and with the returned `east` and `north` coordinates in a previously crawled successful response. This documentation inconsistency is not evidence that reversing our coordinates will repair the present 503 response.

Context7 was used with `/websites/opendata_smhi_se` and `/websites/developers_home-assistant_io`. Some Context7-generated `APIDOC` examples contradict each other on API version, query syntax and response fields. Those generated examples are not treated as authoritative schema evidence; the actual SMHI links, original page content and real payloads take precedence.

The web retrieval service returned an older, explicitly cached successful response for SMHI's official monthly example, labelled as crawled three days earlier. Its shape is:

```json
{
  "dates": ["2022-01", "2022-02"],
  "coord_sys_info": {"EPSG": 4326, "name": "WGS 84"},
  "point_values": [{"east": 16.158, "north": 58.5812, "p": [38.2, 66.8], "t": [0.7, 1.0]}]
}
```

This abbreviated real response supports the container-field and coordinate conventions. It is monthly data, not a daily parser fixture, and its historical crawl timestamp is not evidence of current service recovery.

### Current SMHI frontend and service notices

The API specialist traced the official [gridded precipitation and temperature product page](https://www.smhi.se/data/nederbord-och-fuktighet/nederbord/griddad-nederbord--och-temperaturdata) to its published download application. The lead independently inspected the linked app bundle `https://sid-proxy.smhi.se/pt-hbv/assets/-25ylFNv.js`.

The application still builds point-JSON and CSV requests against `https://opendata-download-metanalys.smhi.se/api/category/pthbv1g/version/1`, with `epsg`, longitude/latitude and repeated `var` parameters. Its result table reads `dates` and `point_values`, including `east`, `north`, `p` and `t`. `sid-proxy.smhi.se` serves the frontend assets; it is not an identified replacement weather-data endpoint. Thus the integration agrees with the current published application, not only with a potentially old documentation example.

The one-year limit for daily downloads is documented for the all-Sweden NetCDF export. No equivalent one-year limit was found for point JSON, and the one-year JSON probe also returns 503.

The specialist reviewed SMHI's updates page and RSS feed; the lead independently read the live feed. No PTHBV outage or migration notice was present. Notices found for MESAN and PMP concern other products and are not evidence that PTHBV version 1 should be replaced. The public feed is not a complete view of SMHI's internal incident management.

## Why the warning persists

1. The HTTP client receives a retryable status and raises `SmhiApiUnavailableError` after bounded retries (`api.py`).
2. `PthbvClient.async_daily` consequently never reaches its JSON/schema/date validation (`pthbv.py`). Malformed JSON would instead produce `SmhiApiResponseError`.
3. `_async_load_history` records only the exception class and logs the climate source as unavailable (`coordinator.py`, the reported line 274).
4. `_history_date` remains unset after a history failure, permitting another attempt at the next normal coordinator update. The configured interval is 30 minutes. The log is deliberately emitted on the available-to-unavailable transition, so a single log occurrence does not mean only one download attempt.
5. The inspected entry has a MetObs temperature archive cache but no PTHBV cache. There is therefore no previously downloaded climate series available for fallback in this entry.

Home Assistant's logging guidance recommends logging an unavailable transition once, and recovery once, rather than repeating warnings on every poll. That policy explains the log count; it does not establish that the service has recovered.

## Confirmed integration limitations

These limitations deserve separate fixes; they do not cause the remote 503 response:

- **Reproduced date-correctness bug:** if previous-day climate values remain in memory, there is no usable PTHBV cache, and the next day's download fails, `_async_load_history` leaves the old `_climate_values` intact. `_populate_climate` then uses those values for the new target date. In an offline reproduction with previous-day values of 5.0, the climate source was unavailable but `temperature_climate_normal` was still 5.0 and the common history timestamp was set. Values must be tied to the calendar date they were derived for, or cleared when a new date cannot be populated. This is not the cause of the current entry's missing initial climate data.
- The runtime warning and diagnostics drop the safe HTTP status and have no per-source last-attempt or last-success fields. An end user cannot distinguish 429, 500, 502, 503 or 504 from the displayed exception class.
- `_history_cached_at` is updated even when a historical source fails. The common last-history-update field must not be interpreted as proof that climate data was successfully downloaded.
- Current temperature and temperature history both use the `temperature` status key. Merging the history statuses over the current statuses can obscure which temperature source is available or stale.
- Temperature-only climate configuration still requests the complete 1961–previous-year series. Requesting only the 1991–2020 normal period would reduce load for that feature, but the smaller normal-period probe also failed during this investigation.
- A fresh successful PTHBV payload is still required to complete end-to-end verification of today's daily data and calculated climate values. Passing offline tests cannot close this gap.

## Verification

The unchanged code passed 78 focused tests covering the HTTP client, PTHBV parser, coordinator and config flow:

```bash
python3 -m pytest tests/test_api.py tests/test_pthbv.py tests/test_coordinator.py tests/test_config_flow.py -q
```

The real HTTP client was also exercised with an `aiohttp.TraceConfig` that recorded only elapsed time, status, response type, server and `Retry-After`. It reproduced the failure and the expected retry intervals without changing the integration.

## Next actions

1. Obtain SMHI's service-side diagnosis using the public official example, timestamps and request identifiers below. A different API, changed coordinates or relaxed JSON validation is not a substantiated fix for this response.
2. Correct the stale-calendar-day case, then add privacy-safe per-source diagnostics and accurate success timestamps, with regression tests for the failure and recovery paths. Only reuse a full cached series after validating it for the requested product, period and variables; derive values for the current target date explicitly.
3. When PTHBV returns HTTP 200 again, verify a complete daily response with the real parser and compare the resulting 1991–2020 normal against independently calculated values in HAdev.

No message has been sent to SMHI. The following details can be used in a support report without disclosing the Home Assistant home position:

```text
SMHI's documented PTHBV monthly 2022–2023 example returns HTTP 503
"Backend fetch failed" with Retry-After: 5.

Observed: 2026-09-04 20:08:25 UTC
Gateway: lxserv2756.smhi.se (Varnish/7.6)
X-Varnish: 315039563
Body XID: 300668460

At 20:11:21 UTC the documented STRANG point endpoint on the same hostname
and gateway returned HTTP 200, application/json, gzip.
STRANG x-request-id: 07d67779-d8e3-469d-9545-9ad6f3f769df

Please confirm the current PTHBV service status, whether the documented
version/1 endpoint remains supported, and any restoration estimate.
```

## Implemented reliability fixes

The following changes are implemented locally after the investigation, with user approval. They do not change SMHI's endpoint or repair the upstream HTTP 503 response.

- Daily temperature, wind and climate samples are invalidated when the local comparison date changes. A failed source also clears its derived values, including both climate temperature and precipitation. Values from one day cannot be presented as another day's normal.
- Cached PTHBV data must pass the same complete daily-period, coordinate-system, single-point and requested-variable checks as downloaded data. An invalid cache does not block a new network attempt. If the request and cache both fail, the original HTTP failure remains visible.
- Climate temperature and precipitation are published together only after both extraction steps succeed.
- Current temperature and temperature history have separate status entries. One cannot overwrite the other's failure or freshness.
- The common last-historical-update time advances only after all requested history sources have refreshed successfully. Failed or partial refreshes retain the previous complete update time, or no time if there has been no complete success.
- Diagnostics expose safe HTTP status numbers and per-source refresh timestamps, without URLs, response bodies, precise coordinates or user labels. Repeated failures still produce one warning per unavailable transition; recovery produces one informational message.

### Diagnostic field meanings

The timestamps describe source refreshes within the current integration runtime, not a persistent HTTP download ledger. They reset when Home Assistant restarts or the integration reloads. A successfully validated cache read counts as a successful refresh; it does not prove that SMHI is currently reachable.

| Field | Meaning |
| --- | --- |
| `last_attempt` | Start of the most recent source refresh, including a possible cache read |
| `last_success` | Most recent refresh that successfully loaded and validated source data; retained across failures |
| `last_update` | Observation timestamp for current weather; successful refresh timestamp for history |
| `http_status` | HTTP status associated with a failed source refresh, such as 503; null for successful refreshes, including usable cache fallback |
| `error_type` | Short error identifier, never the provider's response text |
| `temperature_history`, `wind_history` | Historical-source status, distinct from current observation status |

### Local and live verification

The changed component files are byte-identical in `/Users/niklas/GitHub/smhi_weather_context` and HAdev's `/config/custom_components/smhi_weather_context`, excluding runtime Python cache. The five previous runtime files were backed up to `/tmp/smhi-runtime-backup.Zv4Odu` before deployment. No config entry or `.storage` file was edited directly.

Local verification passes 343 tests with 99.94% total branch-aware coverage and greater than 95% coverage for every integration module. Ruff lint and formatting, strict mypy, dependency audit and deterministic release-artifact checks pass. The test environment uses the repository's pinned Home Assistant test dependency (Core 2026.1.2); the live environment below runs Core 2026.9.0.

The official hassfest source validator also passes all 23 standard checks: one integration, zero invalid integrations, exit code 0. It runs in an isolated local Python environment against the read-only working tree using official Core revision `568136f8406f2cd04234e3d0f436ce2983a4564a`. This is a source-based run, not the workflow container. The separate HACS action remains unrun because its official wrapper requires Docker and the local Docker daemon is inactive. No remote workflow is triggered for this uncommitted change.

After a valid configuration check and restart, Home Assistant MCP confirms the existing test entry is loaded. At 20:35 UTC, current temperature is 15.3 °C; its one-year same-hour comparison is 19.5 °C and ten-year daily mean is 17.32 °C. Both current temperature and temperature history report available separately.

Climate remains unavailable. Its live diagnostics show `http_status: 503`, `last_attempt: 2026-09-04T20:35:10.281851+00:00` and `last_success: null`. The runtime warning now explicitly includes `HTTP 503`. These are successful checks of the failure behavior, not evidence of restored climate data. The successful-fetch and recovery calculations are covered offline; a real daily PTHBV HTTP 200 response remains required for full live climate verification.

A second targeted refresh advances climate's `last_attempt` to `2026-09-04T20:36:21.602326+00:00`, retains `last_success: null` and HTTP 503, and leaves the warning count at one. A separate request to the public Göteborg A MetObs endpoint confirms the live temperature of 15.3 °C, observation time 20:00 UTC and quality flag `G`.

No commit, push, tag or release is created as part of this implementation.

## Sources

- [SMHI PTHBV introduction and concrete example](https://opendata.smhi.se/pthbv/introduction)
- [SMHI PTHBV point request documentation](https://opendata.smhi.se/pthbv/get_point)
- [SMHI PTHBV parameters](https://opendata.smhi.se/pthbv/parameters)
- [SMHI PTHBV all-points export and its daily-range restriction](https://opendata.smhi.se/pthbv/get_all_points)
- [SMHI gridded precipitation and temperature product and download application](https://www.smhi.se/data/nederbord-och-fuktighet/nederbord/griddad-nederbord--och-temperaturdata)
- [SMHI published download application bundle inspected in this investigation](https://sid-proxy.smhi.se/pt-hbv/assets/-25ylFNv.js)
- [SMHI open-data updates](https://www.smhi.se/data/om-smhis-data/uppdateringar-oppna-data)
- [SMHI open-data update feed](https://www.smhi.se/rss/uppdateringar-oppna-data-fran-smhi)
- [SMHI STRÅNG point request documentation](https://opendata.smhi.se/metanalys/strang/get_point)
- [Home Assistant: fetching data](https://developers.home-assistant.io/docs/integration_fetching_data)
- [Home Assistant: log once when unavailable and when recovered](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/log-when-unavailable)
- [Home Assistant: entity availability](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/entity-unavailable)
