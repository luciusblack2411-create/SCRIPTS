"""Immutable RAW command evidence."""

from __future__ import annotations

import codecs
from datetime import datetime
from hashlib import sha256 as sha256_digest
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, field_validator, model_validator

from .base import SCHEMA_VERSION, normalize_utc, utc_now


class RawCommandOutput(BaseModel):
    """Exact text captured for one CommandExecution.

    The model is frozen so accidental mutation of assessment evidence fails
    fast. Parsers must consume this object without modifying it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["0.1"] = SCHEMA_VERSION
    id: UUID = Field(default_factory=uuid4)
    command_execution_id: UUID

    captured_at: datetime = Field(default_factory=utc_now)
    content: str
    encoding: str = Field(default="utf-8", min_length=1, max_length=64)

    sha256: str = Field(min_length=64, max_length=64)
    byte_length: NonNegativeInt
    is_truncated: bool = False

    @field_validator("captured_at")
    @classmethod
    def timestamp_is_utc(cls, value: datetime) -> datetime:
        return normalize_utc(value)

    @field_validator("encoding")
    @classmethod
    def encoding_must_exist(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("encoding must not be blank")
        try:
            return codecs.lookup(cleaned).name
        except LookupError as exc:
            raise ValueError(f"unknown encoding: {cleaned}") from exc

    @field_validator("sha256")
    @classmethod
    def sha256_must_be_hex(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if len(cleaned) != 64:
            raise ValueError("sha256 must contain exactly 64 hexadecimal characters")
        try:
            int(cleaned, 16)
        except ValueError as exc:
            raise ValueError("sha256 must be hexadecimal") from exc
        return cleaned

    @model_validator(mode="after")
    def integrity_metadata_matches_content(self) -> RawCommandOutput:
        payload = self.content.encode(self.encoding)
        expected_hash = sha256_digest(payload).hexdigest()
        if self.byte_length != len(payload):
            raise ValueError("byte_length does not match encoded RAW content")
        if self.sha256 != expected_hash:
            raise ValueError("sha256 does not match encoded RAW content")
        return self

    @classmethod
    def from_text(
        cls,
        *,
        command_execution_id: UUID,
        content: str,
        encoding: str = "utf-8",
        captured_at: datetime | None = None,
        is_truncated: bool = False,
    ) -> RawCommandOutput:
        """Build RAW evidence and calculate integrity metadata consistently."""
        normalized_encoding = codecs.lookup(encoding).name
        payload = content.encode(normalized_encoding)
        return cls(
            command_execution_id=command_execution_id,
            captured_at=captured_at or utc_now(),
            content=content,
            encoding=normalized_encoding,
            sha256=sha256_digest(payload).hexdigest(),
            byte_length=len(payload),
            is_truncated=is_truncated,
        )
