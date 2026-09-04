"""Negative security tests for the persistent source cache."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.smhi_weather_context.storage import CACHE_VERSION, SourceCache

pytestmark = pytest.mark.asyncio


class _Config:
    """Minimal Home Assistant config path provider."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def path(self, *parts: str) -> str:
        return str(self._root.joinpath(*parts))


class _Hass:
    """Minimal Home Assistant executor facade."""

    def __init__(self, root: Path) -> None:
        self.config = _Config(root)

    async def async_add_executor_job(self, target, *args):
        return target(*args)


def _serialized_record(cache: SourceCache, key: str) -> dict[str, Any]:
    return json.loads(cache._path(key).read_text(encoding="utf-8"))


async def test_corrupt_json_and_unknown_version_are_rejected(tmp_path: Path) -> None:
    """Malformed or incompatible cache records must fail closed."""
    cache = SourceCache(_Hass(tmp_path), "entry-a")
    path = cache._path("history")
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")

    assert await cache.async_get("history") is None

    await cache.async_set("history", "trusted")
    record = _serialized_record(cache, "history")
    record["version"] = CACHE_VERSION + 1
    path.write_text(json.dumps(record), encoding="utf-8")

    assert await cache.async_get("history") is None


async def test_payload_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    """A modified payload must never be returned as a valid cache hit."""
    cache = SourceCache(_Hass(tmp_path), "entry-a")
    await cache.async_set("history", "trusted")

    path = cache._path("history")
    record = _serialized_record(cache, "history")
    record["payload"] = "tampered"
    path.write_text(json.dumps(record), encoding="utf-8")

    assert await cache.async_get("history") is None


async def test_checksum_covers_security_relevant_metadata(tmp_path: Path) -> None:
    """Cache provenance metadata must not be mutable outside the checksum."""
    cache = SourceCache(_Hass(tmp_path), "entry-a")
    await cache.async_set(
        "history",
        "trusted",
        {"station_id": 1, "parameter": 1, "source_host": "smhi.example"},
    )

    path = cache._path("history")
    record = _serialized_record(cache, "history")
    record["metadata"]["station_id"] = 999999
    path.write_text(json.dumps(record), encoding="utf-8")

    assert await cache.async_get("history") is None


async def test_cache_file_symlink_is_rejected_for_read_and_write(
    tmp_path: Path,
) -> None:
    """A cache record symlink must never be followed in either direction."""
    cache = SourceCache(_Hass(tmp_path), "entry-a")
    path = cache._path("history")
    path.parent.mkdir(parents=True)
    external = tmp_path / "outside.json"
    external.write_text("outside", encoding="utf-8")
    path.symlink_to(external)

    assert await cache.async_get("history") is None
    with pytest.raises(OSError, match="Unsafe cache path"):
        await cache.async_set("history", "replacement")
    assert external.read_text(encoding="utf-8") == "outside"


async def test_temporary_symlink_is_rejected_without_touching_target(
    tmp_path: Path,
) -> None:
    """The atomic-write temporary path must not permit a symlink attack."""
    cache = SourceCache(_Hass(tmp_path), "entry-a")
    path = cache._path("history")
    path.parent.mkdir(parents=True)
    temporary = path.with_suffix(".tmp")
    external = tmp_path / "outside.txt"
    external.write_text("outside", encoding="utf-8")
    temporary.symlink_to(external)

    with pytest.raises(OSError, match="Unsafe cache path"):
        await cache.async_set("history", "replacement")
    assert external.read_text(encoding="utf-8") == "outside"
    assert not path.exists()


async def test_removing_one_entry_preserves_other_entry_cache(tmp_path: Path) -> None:
    """Entry removal must be narrowly scoped to that entry's private cache."""
    hass = _Hass(tmp_path)
    first = SourceCache(hass, "entry-a")
    second = SourceCache(hass, "entry-b")
    await first.async_set("history", "first")
    await second.async_set("history", "second")

    await first.async_remove()

    assert not first._root.exists()
    second_record = await second.async_get("history")
    assert second_record is not None
    assert second_record.payload == "second"


async def test_failed_atomic_replace_preserves_previous_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed publication must leave the previous complete record readable."""
    cache = SourceCache(_Hass(tmp_path), "entry-a")
    await cache.async_set("history", "previous", {"generation": 1})
    original_replace = Path.replace

    def _fail_temporary_replace(self: Path, target: Path) -> Path:
        if self.suffix == ".tmp":
            raise OSError("simulated atomic replace failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", _fail_temporary_replace)

    with pytest.raises(OSError, match="simulated atomic replace failure"):
        await cache.async_set("history", "partial", {"generation": 2})

    record = await cache.async_get("history")
    assert record is not None
    assert record.payload == "previous"
    assert record.metadata == {"generation": 1}


async def test_unpublished_temporary_record_is_never_read(tmp_path: Path) -> None:
    """A leftover temporary file must not be treated as a cache hit."""
    cache = SourceCache(_Hass(tmp_path), "entry-a")
    path = cache._path("history")
    path.parent.mkdir(parents=True)
    path.with_suffix(".tmp").write_text(
        json.dumps(
            {
                "version": CACHE_VERSION,
                "stored_at": "2026-09-03T12:00:00+00:00",
                "payload": "partial",
                "sha256": "not-relevant",
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )

    assert await cache.async_get("history") is None
