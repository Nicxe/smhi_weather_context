"""Safe asynchronous HTTP client for documented SMHI open-data services."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import json
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout

from .const import ALLOWED_HOSTS, MAX_ARCHIVE_BYTES, MAX_JSON_BYTES


class SmhiApiError(Exception):
    """Base SMHI client error."""


class SmhiApiConnectionError(SmhiApiError):
    """SMHI could not be reached."""


class SmhiApiResponseError(SmhiApiError):
    """SMHI returned invalid or unexpected data."""


class SmhiApiUnavailableError(SmhiApiConnectionError):
    """SMHI returned a transient HTTP failure."""


def _retry_delay(value: str | None, attempt: int) -> float:
    """Respect Retry-After seconds or HTTP dates, otherwise use backoff."""
    fallback: float = 0.25 * (2**attempt)
    if value is None:
        return fallback
    if value.isascii() and value.isdecimal():
        return float(value)
    try:
        retry_at = parsedate_to_datetime(value)
    except TypeError, ValueError, OverflowError:
        return fallback
    if retry_at.tzinfo is None:
        return fallback
    return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


class SmhiCoverageError(SmhiApiError):
    """Coordinates are outside the supported data area."""


def validate_smhi_url(url: str) -> None:
    """Reject non-HTTPS and non-SMHI endpoints before any request."""
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.hostname is None
        or parsed.hostname.endswith(".")
        or parsed.fragment
    ):
        raise SmhiApiResponseError("Blocked non-SMHI endpoint")
    try:
        port = parsed.port
    except ValueError as err:
        raise SmhiApiResponseError("Blocked unsafe SMHI endpoint") from err
    if parsed.username or parsed.password or port not in {None, 443}:
        raise SmhiApiResponseError("Blocked unsafe SMHI endpoint")


class SmhiApiClient:
    """Fetch bounded JSON and text from approved SMHI hosts."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session
        self._timeout = ClientTimeout(total=45, connect=10, sock_read=30)

    async def _request(
        self, url: str, *, max_bytes: int, attempts: int = 3
    ) -> ClientResponse:
        validate_smhi_url(url)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                response = await self._request_with_validated_redirects(url)
                if response.status in {408, 425, 429, 500, 502, 503, 504}:
                    status = response.status
                    delay = _retry_delay(response.headers.get("Retry-After"), attempt)
                    response.release()
                    # Do not block a config flow for a long server-requested wait,
                    # and never retry earlier than the server permits.
                    if attempt + 1 >= attempts or delay > 30:
                        raise SmhiApiUnavailableError(f"SMHI returned HTTP {status}")
                    await asyncio.sleep(delay)
                    continue
                if response.status == 400:
                    response.release()
                    raise SmhiCoverageError("Coordinates are outside SMHI coverage")
                if response.status != 200:
                    status = response.status
                    response.release()
                    raise SmhiApiResponseError(f"SMHI returned HTTP {status}")
                length = response.content_length
                if length is not None and length > max_bytes:
                    response.release()
                    raise SmhiApiResponseError("SMHI response exceeds size limit")
                return response
            except SmhiApiError:
                raise
            except (TimeoutError, ClientError) as err:
                last_error = err
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.25 * (2**attempt))
        raise SmhiApiConnectionError("Could not reach SMHI") from last_error

    async def _request_with_validated_redirects(self, url: str) -> ClientResponse:
        """Follow at most three same-host redirects after validating every hop."""
        current = url
        source_host = urlparse(url).hostname
        for _ in range(4):
            validate_smhi_url(current)
            response = await self._session.get(
                current,
                timeout=self._timeout,
                headers={"Accept-Encoding": "gzip"},
                allow_redirects=False,
            )
            if response.status not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("Location")
            response.release()
            if not location:
                raise SmhiApiResponseError("SMHI redirect is missing Location")
            redirected = urljoin(current, location)
            validate_smhi_url(redirected)
            if urlparse(redirected).hostname != source_host:
                raise SmhiApiResponseError("Blocked cross-host SMHI redirect")
            current = redirected
        raise SmhiApiResponseError("Too many SMHI redirects")

    @staticmethod
    async def _read_bounded(response: ClientResponse, max_bytes: int) -> bytes:
        payload = bytearray()
        async for chunk in response.content.iter_chunked(64 * 1024):
            payload.extend(chunk)
            if len(payload) > max_bytes:
                response.release()
                raise SmhiApiResponseError("SMHI response exceeds size limit")
        return bytes(payload)

    async def async_get_json(self, url: str) -> dict[str, Any]:
        """Return one bounded JSON object."""
        response = await self._request(url, max_bytes=MAX_JSON_BYTES)
        content_type = response.headers.get("Content-Type", "").lower()
        if "json" not in content_type:
            response.release()
            raise SmhiApiResponseError("SMHI returned an unexpected content type")
        try:
            payload = await self._read_bounded(response, MAX_JSON_BYTES)
        except (TimeoutError, ClientError) as err:
            response.release()
            raise SmhiApiConnectionError("SMHI download was interrupted") from err
        try:
            data = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise SmhiApiResponseError("SMHI returned invalid JSON") from err
        if not isinstance(data, dict):
            raise SmhiApiResponseError("SMHI JSON root is not an object")
        return data

    async def async_get_text(self, url: str) -> str:
        """Return one bounded UTF-8 text response."""
        response = await self._request(url, max_bytes=MAX_ARCHIVE_BYTES)
        content_type = response.headers.get("Content-Type", "").lower()
        if not any(value in content_type for value in ("text/", "csv")):
            response.release()
            raise SmhiApiResponseError("SMHI returned an unexpected content type")
        try:
            payload = await self._read_bounded(response, MAX_ARCHIVE_BYTES)
        except (TimeoutError, ClientError) as err:
            response.release()
            raise SmhiApiConnectionError("SMHI download was interrupted") from err
        try:
            return payload.decode("utf-8-sig")
        except UnicodeDecodeError as err:
            raise SmhiApiResponseError("SMHI returned invalid UTF-8") from err


def build_url(base: str, params: Mapping[str, str | int | float | list[str]]) -> str:
    """Build a URL without accepting arbitrary user-controlled hosts."""
    validate_smhi_url(base)
    pairs: list[tuple[str, str | int | float]] = []
    for key, value in params.items():
        if isinstance(value, list):
            pairs.extend((key, item) for item in value)
        else:
            pairs.append((key, value))
    return f"{base}?{urlencode(pairs)}"
