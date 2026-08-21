"""Shared primitives for v0.1 domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION: Literal["0.1"] = "0.1"


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def normalize_utc(value: datetime) -> datetime:
    """Require an aware datetime and normalize it to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


class DomainModel(BaseModel):
    """Base configuration shared by mutable domain models."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )
