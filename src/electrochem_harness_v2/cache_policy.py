"""Versioned, expiring cache envelopes with input fingerprints."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any


CACHE_SCHEMA_VERSION = 1
DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60
FINGERPRINT_FIELDS = ("prompt", "adapter", "model", "context", "topic")
_SENSITIVE_KEYS = frozenset({
    "api_key", "apikey", "authorization", "access_token", "refresh_token",
    "token", "password", "passwd", "secret", "client_secret", "credentials",
})


def fingerprint(value: Any) -> str:
    """Return a stable SHA-256 fingerprint without retaining the input value."""
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def cache_fingerprints(*, prompt: Any, adapter: Any, model: Any, context: Any, topic: Any) -> dict[str, str]:
    return {
        name: fingerprint(value)
        for name, value in (
            ("prompt", prompt),
            ("adapter", adapter),
            ("model", model),
            ("context", context),
            ("topic", topic),
        )
    }


def _utc_datetime(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).strip().casefold().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(("_api_key", "_token", "_password", "_secret"))


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize(item)
            for key, item in value.items()
            if not _is_sensitive_key(key)
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    return value


@dataclass(frozen=True)
class CachePolicy:
    """Create and classify cache entries under one schema and default TTL."""

    ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    schema_version: int = CACHE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive.")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive.")

    def create(
        self,
        payload: Any,
        *,
        prompt: Any,
        adapter: Any,
        model: Any,
        context: Any,
        topic: Any,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        created_at = _utc_datetime(now)
        return {
            "schema_version": self.schema_version,
            "created_at": created_at.isoformat(),
            "expires_at": (created_at + timedelta(seconds=self.ttl_seconds)).isoformat(),
            "ttl_seconds": self.ttl_seconds,
            "fingerprints": cache_fingerprints(
                prompt=prompt,
                adapter=adapter,
                model=model,
                context=context,
                topic=topic,
            ),
            "payload": _sanitize(payload),
        }

    def classify(
        self,
        entry: Any,
        *,
        prompt: Any,
        adapter: Any,
        model: Any,
        context: Any,
        topic: Any,
        now: datetime | None = None,
    ) -> str:
        """Return ``fresh``, ``stale``, or ``incompatible``."""
        if not isinstance(entry, dict) or entry.get("schema_version") != self.schema_version:
            return "incompatible"
        expected = cache_fingerprints(
            prompt=prompt,
            adapter=adapter,
            model=model,
            context=context,
            topic=topic,
        )
        fingerprints = entry.get("fingerprints")
        if not isinstance(fingerprints, dict) or any(fingerprints.get(name) != expected[name] for name in FINGERPRINT_FIELDS):
            return "incompatible"
        try:
            expires_at = datetime.fromisoformat(str(entry["expires_at"]).replace("Z", "+00:00"))
            expires_at = _utc_datetime(expires_at)
        except (KeyError, TypeError, ValueError):
            return "incompatible"
        return "fresh" if _utc_datetime(now) < expires_at else "stale"


def create_cache_entry(
    payload: Any,
    *,
    prompt: Any,
    adapter: Any,
    model: Any,
    context: Any,
    topic: Any,
    ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    now: datetime | None = None,
    schema_version: int = CACHE_SCHEMA_VERSION,
) -> dict[str, Any]:
    return CachePolicy(ttl_seconds=ttl_seconds, schema_version=schema_version).create(
        payload,
        prompt=prompt,
        adapter=adapter,
        model=model,
        context=context,
        topic=topic,
        now=now,
    )


def classify_cache_entry(
    entry: Any,
    *,
    prompt: Any,
    adapter: Any,
    model: Any,
    context: Any,
    topic: Any,
    now: datetime | None = None,
    schema_version: int = CACHE_SCHEMA_VERSION,
) -> str:
    return CachePolicy(schema_version=schema_version).classify(
        entry,
        prompt=prompt,
        adapter=adapter,
        model=model,
        context=context,
        topic=topic,
        now=now,
    )
