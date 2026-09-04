"""Offline tests for the bounded SMHI HTTP client."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

from aiohttp import ClientConnectionError, ClientPayloadError
import pytest

from custom_components.smhi_weather_context import api as api_module
from custom_components.smhi_weather_context.api import (
    SmhiApiClient,
    SmhiApiConnectionError,
    SmhiApiResponseError,
    build_url,
    validate_smhi_url,
)

METOBS_URL = "https://opendata-download-metobs.smhi.se/api.json"
PTHBV_URL = (
    "https://opendata-download-metanalys.smhi.se/api/category/pthbv1g/"
    "version/1/geotype/multipoint/from/1991/to/2020/period/daily/data.json"
)


class FakeContent:
    """Minimal asynchronous response stream."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


class InterruptedContent:
    """Simulate a response body that fails after publication starts."""

    async def iter_chunked(self, _size: int) -> AsyncIterator[bytes]:
        yield b'{"partial":'
        raise ClientPayloadError("connection closed")


class FakeResponse:
    """Minimal aiohttp response used without network access."""

    def __init__(
        self,
        status: int,
        *,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        content_length: int | None = None,
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self.content_length = content_length
        self.content = FakeContent(chunks if chunks is not None else [body])
        self.released = False

    def release(self) -> None:
        self.released = True


class FakeSession:
    """Queue responses and record every attempted HTTP request."""

    def __init__(self, *responses: FakeResponse | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.parametrize("url", [METOBS_URL, PTHBV_URL])
def test_validate_smhi_url_accepts_only_documented_https_hosts(url: str) -> None:
    validate_smhi_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://opendata-download-metobs.smhi.se/api.json",
        "https://example.org/api.json",
        "https://user@opendata-download-metobs.smhi.se/api.json",
        "https://opendata-download-metobs.smhi.se:444/api.json",
        "https://opendata-download-metobs.smhi.se./api.json",
        "https://opendata-download-metobs.smhi.se/api.json#fragment",
        "//opendata-download-metobs.smhi.se/api.json",
    ],
)
def test_validate_smhi_url_blocks_unsafe_targets(url: str) -> None:
    with pytest.raises(SmhiApiResponseError, match="Blocked"):
        validate_smhi_url(url)


def test_build_url_encodes_coordinates_and_repeats_variables() -> None:
    url = build_url(
        PTHBV_URL,
        {"epsg": 4326, "ll": "11.9700,57.7100", "var": ["t", "p"]},
    )

    assert url == (f"{PTHBV_URL}?epsg=4326&ll=11.9700%2C57.7100&var=t&var=p")


@pytest.mark.asyncio
async def test_client_requests_gzip_without_automatic_redirects() -> None:
    response = FakeResponse(
        200,
        body=b'{"ok": true}',
        headers={"Content-Type": "application/json"},
    )
    session = FakeSession(response)

    assert await SmhiApiClient(session).async_get_json(METOBS_URL) == {"ok": True}
    _, kwargs = session.calls[0]
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"] == {"Accept-Encoding": "gzip"}


@pytest.mark.asyncio
async def test_client_follows_a_validated_same_host_redirect() -> None:
    redirect = FakeResponse(302, headers={"Location": "/api/version/1.0.json"})
    final = FakeResponse(
        200,
        body=b'{"key": "1.0"}',
        headers={"Content-Type": "application/json"},
    )
    session = FakeSession(redirect, final)

    result = await SmhiApiClient(session).async_get_json(METOBS_URL)

    assert result == {"key": "1.0"}
    assert redirect.released
    assert session.calls[1][0] == (
        "https://opendata-download-metobs.smhi.se/api/version/1.0.json"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "location",
    [
        "https://opendata-download-metanalys.smhi.se/api.json",
        "https://example.org/api.json",
        "http://opendata-download-metobs.smhi.se/api.json",
    ],
)
async def test_client_blocks_unsafe_redirects(location: str) -> None:
    session = FakeSession(FakeResponse(302, headers={"Location": location}))

    with pytest.raises(SmhiApiResponseError, match="Blocked"):
        await SmhiApiClient(session).async_get_json(METOBS_URL)


@pytest.mark.asyncio
async def test_client_rejects_redirect_without_location() -> None:
    session = FakeSession(FakeResponse(302))

    with pytest.raises(SmhiApiResponseError, match="missing Location"):
        await SmhiApiClient(session).async_get_json(METOBS_URL)


@pytest.mark.asyncio
async def test_client_limits_redirect_hops() -> None:
    redirects = [
        FakeResponse(302, headers={"Location": f"/api/redirect/{index}"})
        for index in range(4)
    ]

    with pytest.raises(SmhiApiResponseError, match="Too many"):
        await SmhiApiClient(FakeSession(*redirects)).async_get_json(METOBS_URL)


@pytest.mark.asyncio
async def test_client_rejects_oversized_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_module, "MAX_JSON_BYTES", 8)
    response = FakeResponse(
        200,
        body=b"{}",
        headers={"Content-Type": "application/json"},
        content_length=9,
    )

    with pytest.raises(SmhiApiResponseError, match="size limit"):
        await SmhiApiClient(FakeSession(response)).async_get_json(METOBS_URL)

    assert response.released


@pytest.mark.asyncio
async def test_client_rejects_oversized_stream_without_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_module, "MAX_JSON_BYTES", 8)
    response = FakeResponse(
        200,
        headers={"Content-Type": "application/json"},
        chunks=[b'{"a":', b'"123456789"}'],
    )

    with pytest.raises(SmhiApiResponseError, match="size limit"):
        await SmhiApiClient(FakeSession(response)).async_get_json(METOBS_URL)

    assert response.released


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "content_type", "message"),
    [
        (b"{}", "text/html", "content type"),
        (b"not-json", "application/json", "invalid JSON"),
        (b"[]", "application/json", "root is not an object"),
    ],
)
async def test_client_rejects_invalid_json_responses(
    body: bytes, content_type: str, message: str
) -> None:
    response = FakeResponse(
        200,
        body=body,
        headers={"Content-Type": content_type},
    )

    with pytest.raises(SmhiApiResponseError, match=message):
        await SmhiApiClient(FakeSession(response)).async_get_json(METOBS_URL)


@pytest.mark.asyncio
async def test_client_retries_transient_status(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr(api_module.asyncio, "sleep", sleep)
    unavailable = FakeResponse(503)
    success = FakeResponse(
        200,
        body=b'{"ok": true}',
        headers={"Content-Type": "application/json"},
    )

    result = await SmhiApiClient(FakeSession(unavailable, success)).async_get_json(
        METOBS_URL
    )

    assert result == {"ok": True}
    assert unavailable.released
    sleep.assert_awaited_once_with(0.25)


@pytest.mark.asyncio
async def test_client_retries_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 429 is transient and uses the same bounded retry policy."""
    sleep = AsyncMock()
    monkeypatch.setattr(api_module.asyncio, "sleep", sleep)
    limited = FakeResponse(429)
    success = FakeResponse(
        200,
        body=b'{"ok": true}',
        headers={"Content-Type": "application/json"},
    )

    result = await SmhiApiClient(FakeSession(limited, success)).async_get_json(
        METOBS_URL
    )

    assert result == {"ok": True}
    assert limited.released
    sleep.assert_awaited_once_with(0.25)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [304, 404])
async def test_client_rejects_non_success_statuses(status: int) -> None:
    response = FakeResponse(status)

    with pytest.raises(SmhiApiResponseError, match=f"HTTP {status}"):
        await SmhiApiClient(FakeSession(response)).async_get_json(METOBS_URL)

    assert response.released


@pytest.mark.asyncio
async def test_client_normalizes_interrupted_response_body() -> None:
    response = FakeResponse(
        200,
        headers={"Content-Type": "application/json"},
    )
    response.content = InterruptedContent()

    with pytest.raises(SmhiApiConnectionError, match="interrupted"):
        await SmhiApiClient(FakeSession(response)).async_get_json(METOBS_URL)

    assert response.released


@pytest.mark.asyncio
async def test_text_client_normalizes_interrupted_response_body() -> None:
    response = FakeResponse(200, headers={"Content-Type": "text/csv"})
    response.content = InterruptedContent()

    with pytest.raises(SmhiApiConnectionError, match="interrupted"):
        await SmhiApiClient(FakeSession(response)).async_get_text(METOBS_URL)

    assert response.released


@pytest.mark.asyncio
async def test_client_normalizes_connection_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_module.asyncio, "sleep", AsyncMock())
    session = FakeSession(
        ClientConnectionError("offline"),
        ClientConnectionError("offline"),
        ClientConnectionError("offline"),
    )

    with pytest.raises(SmhiApiConnectionError, match="Could not reach"):
        await SmhiApiClient(session).async_get_json(METOBS_URL)
