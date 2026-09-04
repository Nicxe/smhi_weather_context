"""Versioned atomic source cache."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, cast

from homeassistant.core import HomeAssistant

from .const import DOMAIN

CACHE_VERSION = 1


@dataclass(frozen=True, slots=True)
class CacheRecord:
    """One cached upstream payload."""

    payload: str
    stored_at: datetime
    metadata: dict[str, Any]


class SourceCache:
    """Store source responses in a component-owned .storage subdirectory."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._root = Path(hass.config.path(".storage", DOMAIN, entry_id))

    def _path(self, key: str) -> Path:
        safe = "".join(char for char in key if char.isalnum() or char in {"-", "_"})
        if not safe:
            raise ValueError("Invalid cache key")
        digest = hashlib.sha256(safe.encode()).hexdigest()[:24]
        return self._root / f"{digest}.json"

    @staticmethod
    def _checksum(payload: str, metadata: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"payload": payload, "metadata": metadata},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    async def async_get(
        self, key: str, *, max_age: timedelta | None = None
    ) -> CacheRecord | None:
        """Load a valid cached payload without blocking the event loop."""
        return cast(
            CacheRecord | None,
            await self._hass.async_add_executor_job(self._get, key, max_age),
        )

    def _get(self, key: str, max_age: timedelta | None) -> CacheRecord | None:
        path = self._path(key)
        try:
            if path.is_symlink():
                return None
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("version") != CACHE_VERSION:
                return None
            stored_at = datetime.fromisoformat(raw["stored_at"])
            if stored_at.tzinfo is None:
                stored_at = stored_at.replace(tzinfo=UTC)
            if max_age is not None and datetime.now(UTC) - stored_at > max_age:
                return None
            payload = str(raw["payload"])
            metadata = dict(raw.get("metadata", {}))
            if raw.get("sha256") != self._checksum(payload, metadata):
                return None
            return CacheRecord(
                payload=payload,
                stored_at=stored_at,
                metadata=metadata,
            )
        except OSError, ValueError, TypeError, KeyError, json.JSONDecodeError:
            return None

    async def async_set(
        self, key: str, payload: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Atomically write a cache record."""
        await self._hass.async_add_executor_job(self._set, key, payload, metadata or {})

    def _set(self, key: str, payload: str, metadata: dict[str, Any]) -> None:
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self._path(key)
        if path.is_symlink() or self._root.is_symlink():
            raise OSError("Unsafe cache path")
        temporary = path.with_suffix(".tmp")
        if temporary.is_symlink():
            raise OSError("Unsafe cache path")
        temporary.write_text(
            json.dumps(
                {
                    "version": CACHE_VERSION,
                    "stored_at": datetime.now(UTC).isoformat(),
                    "payload": payload,
                    "sha256": self._checksum(payload, metadata),
                    "metadata": metadata,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(path)

    async def async_remove(self) -> None:
        """Remove this config entry's private cache on entry removal."""
        await self._hass.async_add_executor_job(shutil.rmtree, self._root, True)
