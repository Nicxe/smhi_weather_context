#!/usr/bin/env python3
"""Run small, bounded probes against the documented SMHI services."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path
import sys

from aiohttp import ClientSession

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.smhi_weather_context.api import SmhiApiClient  # noqa: E402
from custom_components.smhi_weather_context.const import (  # noqa: E402
    METOBS_BASE_URL,
    PARAM_TEMPERATURE,
)
from custom_components.smhi_weather_context.metobs import MetObsClient  # noqa: E402
from custom_components.smhi_weather_context.models import Location  # noqa: E402
from custom_components.smhi_weather_context.pthbv import PthbvClient  # noqa: E402


async def _probe(latitude: float, longitude: float, station_id: int) -> None:
    async with ClientSession() as session:
        api = SmhiApiClient(session)
        metobs = MetObsClient(api)
        pthbv = PthbvClient(api)
        await api.async_get_json(
            f"{METOBS_BASE_URL}/parameter/{PARAM_TEMPERATURE}.json"
        )
        observations, _ = await metobs.async_latest_day(PARAM_TEMPERATURE, station_id)
        if not observations:
            raise RuntimeError("MetObs returned no accepted temperature observations")
        year = datetime.now(UTC).year - 2
        climate = await pthbv.async_daily(
            Location("probe", latitude, longitude), year, year
        )
        print(
            "SMHI probe passed: parameter metadata, current MetObs temperature, "
            f"and {len(climate['dates'])} bounded PTHBV daily values"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latitude", type=float, default=58.5812)
    parser.add_argument("--longitude", type=float, default=16.1580)
    parser.add_argument("--station-id", type=int, default=71420)
    args = parser.parse_args()
    asyncio.run(_probe(args.latitude, args.longitude, args.station_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
